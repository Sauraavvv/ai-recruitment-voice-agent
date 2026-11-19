"""Call jobs (phase-05 P5-T4): `initiate_call` and the stuck-attempt reconciler.

initiate_call(attempt_id):
  queued only → concurrency slot (none free → retry in 15 s) → re-check eligibility (incl. the
  global pause: a paused attempt is cancelled with failure_reason ineligible:calling_paused;
  a paused or out-of-window retry or callback is put back on the schedule instead) →
  initiating → provider → store provider_call_id.
  A provider timeout leaves the attempt `initiating` with failure_reason=initiate_timeout; the
  reconciler then asks the provider whether the call exists. Never retried blindly.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from arq import Retry

from app.config import Settings, get_settings
from app.database.connection import get_sessionmaker
from app.database.models import CallAttempt, CallAttemptType, CallEndReason, CallStatus, Job
from app.providers.telephony import create_telephony_provider, status_callback_url
from app.providers.telephony.base import (
    ProviderCallStatus,
    TelephonyError,
    TelephonyProvider,
    TelephonyTimeoutError,
)
from app.repositories import call_repo, candidate_repo
from app.services import (
    call_service,
    call_slots,
    call_state,
    retry_service,
    settings_service,
    sync_service,
)
from app.utils.calling_window import CallingWindow
from app.utils.log import get_logger
from app.utils.redis import get_redis

logger = get_logger(__name__)

NO_SLOT_RETRY_S = 15
# A retry or callback that can't dial right now goes back on the schedule instead of being
# cancelled (phase-09): the window closed while it waited for a line, or calling was paused
RESCHEDULE_ON = frozenset({call_service.Ineligible.OUTSIDE_WINDOW, call_service.Ineligible.PAUSED})
MAX_SLOT_WAITS = 240  # 1 hour of waiting for a free line, then give up


def _provider(ctx: dict[str, Any], settings: Settings) -> TelephonyProvider:
    provider: TelephonyProvider | None = ctx.get("telephony")
    if provider is None:
        provider = create_telephony_provider(settings)
        ctx["telephony"] = provider
    return provider


async def _fail(session: Any, attempt: CallAttempt, reason: str, end_reason: str) -> None:
    changed = call_state.transition(
        attempt, CallStatus.FAILED, end_reason=end_reason, failure_reason=reason
    )
    call_service.record_if_ended(session, attempt, changed)
    await session.commit()


async def initiate_call(ctx: dict[str, Any], attempt_id: str, ignore_window: bool = False) -> str:
    # The Settings page's values (pause, window, concurrency) apply to calls already queued
    settings = await settings_service.effective_new_session(ctx.get("settings") or get_settings())
    redis = get_redis()
    aid = uuid.UUID(attempt_id)
    async with get_sessionmaker()() as session:
        attempt = await call_repo.get(session, aid, lock=True)
        if attempt is None or attempt.call_status != CallStatus.QUEUED:
            await session.rollback()
            return "skipped"

        if not await call_slots.acquire(
            redis,
            attempt_id,
            size=settings.max_concurrent_calls,
            ttl_s=settings.max_call_duration_s,
        ):
            await session.rollback()
            if ctx.get("job_try", 1) >= MAX_SLOT_WAITS:
                async with get_sessionmaker()() as s2:
                    again = await call_repo.get(s2, aid, lock=True)
                    if again is not None:
                        await _fail(s2, again, "no_free_line", CallEndReason.TECHNICAL_FAILURE)
                        await call_service.evaluate_retry(s2, aid, settings)
                return "no_slot"
            raise Retry(defer=NO_SLOT_RETRY_S)

        candidate = await candidate_repo.get(session, attempt.candidate_id, include_deleted=True)
        problem = await call_service.check_eligibility(
            session,
            candidate,
            settings,
            own_attempt_id=attempt.id,
            ignore_window=ignore_window,
        )
        automatic = attempt.attempt_type in (CallAttemptType.RETRY, CallAttemptType.CALLBACK)
        if automatic and problem is None:
            job = await session.get(Job, candidate.job_id) if candidate else None
            problem = retry_service.stop_reason(candidate, job)  # e.g. declined meanwhile
        if automatic and problem in RESCHEDULE_ON:
            # A retry or callback that waited too long for a line: back on the schedule
            now = datetime.now(UTC)
            at = now
            if problem == call_service.Ineligible.OUTSIDE_WINDOW:
                at = CallingWindow.from_settings(settings).next_open(now)
            retry_service.reschedule(attempt, at)
            await session.commit()
            await call_slots.release(redis, attempt_id, size=settings.max_concurrent_calls)
            logger.info("call_rescheduled", call_attempt_id=attempt_id, reason=problem)
            return "rescheduled"
        if problem or candidate is None:
            changed = call_state.transition(
                attempt,
                CallStatus.CANCELLED,
                end_reason=CallEndReason.CANCELLED,
                failure_reason=f"ineligible:{problem}",
            )
            call_service.record_if_ended(session, attempt, changed)
            await session.commit()
            await sync_service.request_sync(settings, ctx.get("redis"))
            await call_slots.release(redis, attempt_id, size=settings.max_concurrent_calls)
            logger.info("call_cancelled_ineligible", call_attempt_id=attempt_id, reason=problem)
            return "cancelled"

        call_state.transition(attempt, CallStatus.INITIATING)
        await session.commit()

        try:
            placed = await _provider(ctx, settings).initiate_call(
                to_phone=candidate.phone,
                call_attempt_id=attempt_id,
                status_callback_url=status_callback_url(settings),
            )
        except TelephonyTimeoutError:
            attempt.failure_reason = "initiate_timeout"
            await session.commit()
            logger.warning("call_initiate_timeout", call_attempt_id=attempt_id)
            return "timeout"
        except TelephonyError as exc:
            await _fail(session, attempt, f"initiate_failed: {exc}", CallEndReason.PROVIDER_FAILED)
            await call_service.evaluate_retry(session, aid, settings)
            await sync_service.request_sync(settings, ctx.get("redis"))
            await call_slots.release(redis, attempt_id, size=settings.max_concurrent_calls)
            logger.warning("call_initiate_failed", call_attempt_id=attempt_id, error=str(exc))
            return "failed"

        # A webhook may already have filled these in; don't go backwards.
        if attempt.provider_call_id is None:
            attempt.provider_call_id = placed.provider_call_id
        call_state.update_details(attempt, provider_status=placed.raw_status)
        await session.commit()
        logger.info(
            "call_initiated",
            call_attempt_id=attempt_id,
            provider_call_id=placed.provider_call_id,
        )
        return "initiated"


async def reconcile_calls(ctx: dict[str, Any], *, now: datetime | None = None) -> int:
    """Cron: attempts stuck in initiating / ringing / in_progress → ask the provider."""
    settings: Settings = ctx.get("settings") or get_settings()
    if not settings.exotel_configured:
        return 0
    provider = _provider(ctx, settings)
    redis = get_redis()
    now = now or datetime.now(UTC)

    async def lookup(attempt: CallAttempt) -> ProviderCallStatus | None:
        if attempt.provider_call_id:
            return await provider.get_call_status(attempt.provider_call_id)
        candidate = await candidate_repo.get(session, attempt.candidate_id, include_deleted=True)
        if candidate is None:
            return None
        found = await provider.find_calls(to_phone=candidate.phone, since=attempt.created_at)
        return found[0] if found else None

    count = 0
    async with get_sessionmaker()() as session:
        for status, age in call_service.stuck_thresholds(settings).items():
            for attempt in await call_repo.in_statuses_since(session, [status.value], now - age):
                try:
                    await call_service.reconcile_attempt(session, redis, settings, attempt, lookup)
                    count += 1
                except TelephonyError as exc:
                    await session.rollback()
                    logger.warning(
                        "call_reconcile_failed", call_attempt_id=str(attempt.id), error=str(exc)
                    )
    if count:
        await sync_service.request_sync(settings, ctx.get("redis"))
    return count


async def finalize_call(ctx: dict[str, Any], attempt_id: str) -> str:
    """After a conversation (phase-07 §5): final extraction, one transaction (conversation,
    candidate, attempt, Sheets outbox), summary, Sheets sync. Idempotent."""
    from app.providers.llm import create_llm_provider
    from app.services import finalization_service

    settings: Settings = ctx.get("settings") or get_settings()
    llm = (
        create_llm_provider(settings) if settings.openai_api_key and settings.openai_model else None
    )
    try:
        outcome = await finalization_service.finalize_attempt(
            uuid.UUID(attempt_id), settings=settings, llm=llm, pool=ctx.get("redis")
        )
    finally:
        if llm is not None:
            await llm.aclose()
    logger.info("finalize_call_done", call_attempt_id=attempt_id, outcome=outcome)
    return outcome


FINALIZE_STALE = timedelta(minutes=10)


async def reconcile_finalize(ctx: dict[str, Any], *, now: datetime | None = None) -> int:
    """Cron: conversations whose call ended but that weren't finalized (or have no summary)
    after 10 minutes, e.g. the worker was down → queue `finalize_call` again."""
    from sqlalchemy import or_, select

    from app.database.models import Conversation

    now = now or datetime.now(UTC)
    async with get_sessionmaker()() as session:
        rows = await session.execute(
            select(Conversation.call_attempt_id).where(
                Conversation.extracted_data.has_key("result"),
                Conversation.updated_at <= now - FINALIZE_STALE,
                or_(Conversation.finalized_at.is_(None), Conversation.summary.is_(None)),
            )
        )
        attempt_ids = [str(r[0]) for r in rows]
    pool = ctx.get("redis")
    for aid in attempt_ids:
        if pool is not None:
            await pool.enqueue_job("finalize_call", aid, _job_id=f"finalize:{aid}")
    if attempt_ids:
        logger.info("finalize_requeued", count=len(attempt_ids))
    return len(attempt_ids)
