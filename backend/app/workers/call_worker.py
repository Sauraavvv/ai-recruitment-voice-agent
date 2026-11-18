"""Call jobs (phase-05 P5-T4): `initiate_call` and the stuck-attempt reconciler.

initiate_call(attempt_id):
  queued only → concurrency slot (none free → retry in 15 s) → re-check eligibility →
  initiating → provider → store provider_call_id.
  A provider timeout leaves the attempt `initiating` with failure_reason=initiate_timeout; the
  reconciler then asks the provider whether the call exists. Never retried blindly.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from arq import Retry

from app.config import Settings, get_settings
from app.database.connection import get_sessionmaker
from app.database.models import CallAttempt, CallEndReason, CallStatus
from app.providers.telephony import create_telephony_provider, status_callback_url
from app.providers.telephony.base import (
    ProviderCallStatus,
    TelephonyError,
    TelephonyProvider,
    TelephonyTimeoutError,
)
from app.repositories import call_repo, candidate_repo
from app.services import call_service, call_slots, call_state
from app.utils.log import get_logger
from app.utils.redis import get_redis

logger = get_logger(__name__)

NO_SLOT_RETRY_S = 15
MAX_SLOT_WAITS = 240  # 1 hour of waiting for a free line, then give up


def _provider(ctx: dict[str, Any], settings: Settings) -> TelephonyProvider:
    provider: TelephonyProvider | None = ctx.get("telephony")
    if provider is None:
        provider = create_telephony_provider(settings)
        ctx["telephony"] = provider
    return provider


async def _fail(session: Any, attempt: CallAttempt, reason: str, end_reason: str) -> None:
    call_state.transition(attempt, CallStatus.FAILED, end_reason=end_reason, failure_reason=reason)
    await session.commit()


async def initiate_call(ctx: dict[str, Any], attempt_id: str, ignore_window: bool = False) -> str:
    settings: Settings = ctx.get("settings") or get_settings()
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
        if problem or candidate is None:
            call_state.transition(
                attempt,
                CallStatus.CANCELLED,
                end_reason=CallEndReason.CANCELLED,
                failure_reason=f"ineligible:{problem}",
            )
            await session.commit()
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
    return count
