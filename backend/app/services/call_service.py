"""Call orchestration (plan.md Module F, phase-05 P5-T4/T5/T6).

- `start_calls`: eligibility per candidate → create a queued attempt → enqueue `initiate_call`.
- `apply_provider_status`: the one place provider statuses (webhook or reconciler) change an
  attempt.
- `handle_status_callback`: idempotent webhook processing via `webhook_events`.
- `attach_stream` / `stream_ended`: the media stream's view of the call.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import (
    LIVE_CALL_STATUSES,
    CallAttempt,
    CallAttemptType,
    CallEndReason,
    CallStatus,
    Candidate,
    Job,
)
from app.providers.telephony import exotel_models as em
from app.providers.telephony.base import ProviderCallStatus
from app.repositories import call_repo, candidate_repo
from app.services import call_slots, call_state, sync_service
from app.services.errors import conflict, not_found
from app.utils.log import get_logger
from app.utils.phone import normalize_phone

logger = get_logger(__name__)

Enqueue = Callable[[str], Awaitable[None]]

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# --- Eligibility ------------------------------------------------------------------------------


class Ineligible:
    NOT_FOUND = "candidate_not_found"
    DELETED = "candidate_deleted"
    OPTED_OUT = "opted_out"
    NO_CONSENT = "consent_missing"
    BAD_PHONE = "phone_invalid"
    JOB_INACTIVE = "job_inactive"
    LIVE_ATTEMPT = "call_already_active"
    OUTSIDE_WINDOW = "outside_calling_window"
    NOT_CONFIGURED = "telephony_not_configured"
    VOICE_UNAVAILABLE = "voice_unavailable"
    PAUSED = "calling_paused"


INELIGIBLE_MESSAGES = {
    Ineligible.NOT_FOUND: "Candidate not found",
    Ineligible.DELETED: "Candidate was deleted",
    Ineligible.OPTED_OUT: "Candidate opted out of calls",
    Ineligible.NO_CONSENT: "No recorded consent to call this candidate",
    Ineligible.BAD_PHONE: "Phone number is not valid",
    Ineligible.JOB_INACTIVE: "The candidate's job is not active",
    Ineligible.LIVE_ATTEMPT: "A call for this candidate is already queued or in progress",
    Ineligible.OUTSIDE_WINDOW: "Outside calling hours",
    Ineligible.NOT_CONFIGURED: "Telephony is not configured",
    Ineligible.VOICE_UNAVAILABLE: "The AI voice isn't ready yet; try again in a minute",
    Ineligible.PAUSED: "Calling is paused on the Settings page",
}


def in_calling_window(settings: Settings, now: datetime | None = None) -> bool:
    local = (now or datetime.now(UTC)).astimezone(ZoneInfo(settings.app_timezone))
    days = {d.strip().lower()[:3] for d in settings.calling_days.split(",") if d.strip()}
    if DAY_NAMES[local.weekday()] not in days:
        return False
    return settings.calling_hour_start <= local.hour < settings.calling_hour_end


async def check_eligibility(
    session: AsyncSession,
    candidate: Candidate | None,
    settings: Settings,
    *,
    now: datetime | None = None,
    ignore_window: bool = False,
    own_attempt_id: uuid.UUID | None = None,
) -> str | None:
    """None if the candidate may be called now, else an `Ineligible` code."""
    if candidate is None:
        return Ineligible.NOT_FOUND
    if candidate.deleted_at is not None:
        return Ineligible.DELETED
    if candidate.opted_out:
        return Ineligible.OPTED_OUT
    if candidate.consent_at is None:
        return Ineligible.NO_CONSENT
    if not normalize_phone(candidate.phone).ok:
        return Ineligible.BAD_PHONE
    job = await session.get(Job, candidate.job_id)
    if job is None or not job.is_active:
        return Ineligible.JOB_INACTIVE
    live = await call_repo.live_for_candidate(session, candidate.id)
    if live is not None and live.id != own_attempt_id:
        return Ineligible.LIVE_ATTEMPT
    return global_problem(settings, now=now, ignore_window=ignore_window)


def global_problem(
    settings: Settings, *, now: datetime | None = None, ignore_window: bool = False
) -> str | None:
    """The reasons that apply to every candidate alike (pause, window, telephony)."""
    if not settings.calling_enabled:
        return Ineligible.PAUSED
    if not ignore_window and not in_calling_window(settings, now):
        return Ineligible.OUTSIDE_WINDOW
    if not settings.exotel_configured:
        return Ineligible.NOT_CONFIGURED
    return None


async def eligibility_for(
    session: AsyncSession,
    candidates: list[Candidate],
    settings: Settings,
    *,
    now: datetime | None = None,
    voice_ready: bool = True,
) -> dict[uuid.UUID, str | None]:
    """`check_eligibility` for a page of candidates in two queries (the candidate list's
    buttons). Same rules and order."""
    if not candidates:
        return {}
    ids = [c.id for c in candidates]
    live = set(
        (
            await session.execute(
                select(CallAttempt.candidate_id).where(
                    CallAttempt.candidate_id.in_(ids),
                    CallAttempt.call_status.in_([s.value for s in LIVE_CALL_STATUSES]),
                )
            )
        ).scalars()
    )
    active_jobs = set(
        (
            await session.execute(
                select(Job.id).where(
                    Job.id.in_({c.job_id for c in candidates}), Job.is_active.is_(True)
                )
            )
        ).scalars()
    )
    common = global_problem(settings, now=now)
    if common is None and not voice_ready:
        common = Ineligible.VOICE_UNAVAILABLE
    out: dict[uuid.UUID, str | None] = {}
    for c in candidates:
        if c.deleted_at is not None:
            out[c.id] = Ineligible.DELETED
        elif c.opted_out:
            out[c.id] = Ineligible.OPTED_OUT
        elif c.consent_at is None:
            out[c.id] = Ineligible.NO_CONSENT
        elif not normalize_phone(c.phone).ok:
            out[c.id] = Ineligible.BAD_PHONE
        elif c.job_id not in active_jobs:
            out[c.id] = Ineligible.JOB_INACTIVE
        elif c.id in live:
            out[c.id] = Ineligible.LIVE_ATTEMPT
        else:
            out[c.id] = common
    return out


def eligibility_dict(code: str | None) -> dict[str, Any]:
    return {
        "can_call": code is None,
        "reason": code,
        "message": INELIGIBLE_MESSAGES.get(code or "") or None,
    }


# --- Starting calls ---------------------------------------------------------------------------


@dataclass
class StartResult:
    candidate_id: uuid.UUID
    attempt_id: uuid.UUID | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "ok": self.ok,
            "call_attempt_id": self.attempt_id,
            "error": None
            if self.ok
            else {"code": self.error, "message": INELIGIBLE_MESSAGES.get(self.error or "", "")},
        }


async def start_calls(
    session: AsyncSession,
    candidate_ids: list[uuid.UUID],
    settings: Settings,
    enqueue: Enqueue,
    *,
    attempt_type: CallAttemptType = CallAttemptType.MANUAL,
    ignore_window: bool = False,
    voice_ready: bool = True,
    dry_run: bool = False,
) -> list[StartResult]:
    """`dry_run`: eligibility only (the confirmation dialog), nothing is queued."""
    results: list[StartResult] = []
    for candidate_id in dict.fromkeys(candidate_ids):  # de-duplicate, keep order
        result = StartResult(candidate_id)
        results.append(result)
        candidate = await candidate_repo.get(session, candidate_id, include_deleted=True)
        result.error = await check_eligibility(
            session, candidate, settings, ignore_window=ignore_window
        )
        if result.error is None and not voice_ready:
            result.error = Ineligible.VOICE_UNAVAILABLE  # nothing could speak on the call
        if result.error or candidate is None or dry_run:
            continue
        attempt = CallAttempt(
            candidate_id=candidate.id,
            attempt_number=await call_repo.next_attempt_number(session, candidate.id),
            attempt_type=attempt_type.value,
            provider=em.PROVIDER,
            call_status=CallStatus.QUEUED.value,
        )
        try:
            async with session.begin_nested():
                session.add(attempt)
        except IntegrityError:
            # Another request created a live attempt for this candidate at the same moment.
            result.error = Ineligible.LIVE_ATTEMPT
            continue
        sync_service.record_change(session, candidate.id)  # Call Status in the sheet
        await session.commit()
        result.attempt_id = attempt.id
        logger.info(
            "call_queued",
            call_attempt_id=str(attempt.id),
            candidate_id=str(candidate.id),
            attempt_number=attempt.attempt_number,
        )
        try:
            await enqueue(str(attempt.id))
        except Exception:
            logger.exception("call_enqueue_failed", call_attempt_id=str(attempt.id))
            call_state.transition(
                attempt,
                CallStatus.FAILED,
                end_reason=CallEndReason.TECHNICAL_FAILURE.value,
                failure_reason="enqueue_failed",
            )
            await session.commit()
            result.error = "enqueue_failed"
    return results


async def get(session: AsyncSession, attempt_id: uuid.UUID) -> CallAttempt:
    attempt = await call_repo.get(session, attempt_id)
    if attempt is None:
        raise not_found("call_not_found", "Call attempt not found")
    return attempt


# --- Recruiter controls (phase-08 §5.3) ---------------------------------------------------------

# Attempts that haven't dialed yet: the recruiter may cancel them
CANCELLABLE = (
    CallStatus.PENDING,
    CallStatus.QUEUED,
    CallStatus.RETRY_SCHEDULED,
    CallStatus.CALLBACK_REQUESTED,
)


async def retry(
    session: AsyncSession,
    attempt_id: uuid.UUID,
    settings: Settings,
    enqueue: Enqueue,
    *,
    voice_ready: bool = True,
) -> StartResult:
    """A new manual attempt for this attempt's candidate, under the same eligibility rules as
    starting a call (opt-out, consent, window, pause, no live attempt)."""
    attempt = await get(session, attempt_id)  # still live → call_already_active below
    results = await start_calls(
        session,
        [attempt.candidate_id],
        settings,
        enqueue,
        attempt_type=CallAttemptType.MANUAL,
        voice_ready=voice_ready,
    )
    return results[0]


async def cancel(
    session: AsyncSession,
    redis: Redis,
    attempt_id: uuid.UUID,
    settings: Settings,
    *,
    user_id: uuid.UUID,
) -> CallAttempt:
    """Cancel an attempt that hasn't dialed yet. A queued job then finds it not queued and
    skips it."""
    attempt = await call_repo.get(session, attempt_id, lock=True)
    if attempt is None:
        raise not_found("call_not_found", "Call attempt not found")
    current = attempt.call_status
    if current not in {s.value for s in CANCELLABLE}:
        await session.rollback()
        raise conflict(
            "call_not_cancellable",
            "Only a call that hasn't started dialing can be cancelled",
            {"call_status": current},
        )
    changed = call_state.transition(
        attempt,
        CallStatus.CANCELLED,
        end_reason=CallEndReason.CANCELLED.value,
        failure_reason=f"cancelled_by_recruiter:{user_id}",
    )
    record_if_ended(session, attempt, changed)
    await session.commit()
    await session.refresh(attempt)
    await call_slots.release(redis, str(attempt.id), size=settings.max_concurrent_calls)
    logger.info("call_cancelled", call_attempt_id=str(attempt.id), user_id=str(user_id))
    return attempt


# --- Provider status --------------------------------------------------------------------------


def apply_provider_status(
    attempt: CallAttempt, status: ProviderCallStatus, *, now: datetime | None = None
) -> bool:
    """Apply a provider's status to the attempt. Returns True if the call status changed."""
    end_reason = status.end_reason
    if status.status == CallStatus.COMPLETED:
        if attempt.stream_id is None:
            # Answered by the network but our stream never connected: nobody heard the agent.
            end_reason = CallEndReason.TECHNICAL_FAILURE.value
        else:
            end_reason = attempt.end_reason or CallEndReason.CANDIDATE_HANGUP.value
    changed = call_state.transition(
        attempt,
        status.status,
        now=now,
        start_time=status.start_time,
        end_time=status.end_time,
        end_reason=end_reason if call_state.is_terminal(status.status) else None,
        failure_reason="stream_never_connected"
        if end_reason == CallEndReason.TECHNICAL_FAILURE and status.status == CallStatus.COMPLETED
        else None,
    )
    duration = status.duration_seconds
    if (
        duration is None
        and attempt.duration_seconds is None
        and call_state.is_terminal(attempt.call_status)
        and attempt.start_time
        and attempt.end_time
    ):
        # Exotel's default callback has no duration (real call 2026-11-19): use the times we saw
        duration = max(0, round((attempt.end_time - attempt.start_time).total_seconds()))
    call_state.update_details(
        attempt,
        # A late, ignored event must not overwrite the status that ended the call
        provider_status=status.raw_status
        if changed or not call_state.is_terminal(attempt.call_status)
        else None,
        duration_seconds=duration,
        recording_url=status.recording_url,
    )
    return changed


def record_if_ended(session: AsyncSession, attempt: CallAttempt, changed: bool) -> bool:
    """Sheets outbox row when an attempt just reached a final status (Call Status, Attempt
    Count, Last Call Date). Same transaction as the status change."""
    if changed and call_state.is_terminal(attempt.call_status):
        sync_service.record_change(session, attempt.candidate_id)
        return True
    return False


async def release_slot_if_done(redis: Redis, attempt: CallAttempt, settings: Settings) -> None:
    if call_state.is_terminal(attempt.call_status):
        await call_slots.release(redis, str(attempt.id), size=settings.max_concurrent_calls)


async def handle_status_callback(
    session: AsyncSession, redis: Redis, settings: Settings, payload: dict[str, Any]
) -> str:
    """Store, de-duplicate and apply one Exotel StatusCallback. Returns an outcome label."""
    callback = em.parse_status_callback(payload, tz=settings.app_timezone)
    event_id = await call_repo.insert_webhook_event(
        session,
        provider=em.PROVIDER,
        provider_call_id=callback.call_sid,
        event_type=callback.event_type,
        dedupe_key=callback.dedupe_key(),
        payload=payload,
    )
    if event_id is None:
        await session.rollback()
        return "duplicate"
    event = await call_repo.get_webhook_event(session, event_id)
    assert event is not None

    attempt = None
    if callback.call_sid:
        attempt = await call_repo.get_by_provider_call(
            session, em.PROVIDER, callback.call_sid, lock=True
        )
    if attempt is None and callback.custom_field:
        try:
            attempt = await call_repo.get(session, uuid.UUID(callback.custom_field), lock=True)
        except ValueError:
            attempt = None
    now = datetime.now(UTC)
    if attempt is None:
        event.error, event.processed_at = "unknown_call", now
        await session.commit()
        logger.warning("webhook_unknown_call", provider_call_id=callback.call_sid)
        return "unknown_call"

    if attempt.provider_call_id is None and callback.call_sid:
        attempt.provider_call_id = callback.call_sid  # e.g. after an initiate timeout
    mapped = em.map_status(callback.raw_status)
    if mapped is None and callback.event_type == "answered":
        mapped = (CallStatus.IN_PROGRESS, None)
    if mapped is None:
        event.error, event.processed_at = f"unmapped_status:{callback.raw_status}", now
        await session.commit()
        logger.warning("webhook_unmapped_status", raw_status=callback.raw_status)
        return "unmapped_status"

    status, reason = mapped
    changed = apply_provider_status(
        attempt,
        ProviderCallStatus(
            provider_call_id=callback.call_sid or "",
            raw_status=callback.raw_status,
            status=status.value,
            end_reason=reason.value if reason else None,
            start_time=callback.start_time,
            end_time=callback.end_time,
            duration_seconds=callback.duration_seconds,
            recording_url=callback.recording_url,
        ),
        now=now,
    )
    event.processed_at = now
    if not changed:
        event.error = f"ignored:{attempt.call_status}->{status.value}"
    record_if_ended(session, attempt, changed)
    await session.commit()
    await release_slot_if_done(redis, attempt, settings)
    logger.info(
        "webhook_applied",
        call_attempt_id=str(attempt.id),
        event_type=callback.event_type,
        provider_status=callback.raw_status,
        call_status=attempt.call_status,
        changed=changed,
    )
    return "applied" if changed else "ignored"


# --- Media stream -----------------------------------------------------------------------------

STREAMABLE = (CallStatus.INITIATING, CallStatus.RINGING, CallStatus.IN_PROGRESS)


async def attach_stream(session: AsyncSession, start: em.StreamStart) -> CallAttempt | None:
    """Find the live attempt a stream belongs to and mark it in progress. None → reject."""
    attempt = None
    if start.call_sid:
        attempt = await call_repo.get_by_provider_call(
            session, em.PROVIDER, start.call_sid, lock=True
        )
    if attempt is None:
        # CustomField (our attempt id) arrives as a *key* of custom_parameters with an empty
        # value (real call 2026-11-19); also accept explicit attempt_id / CustomField values.
        params = start.custom_parameters
        hints = [params.get("attempt_id"), params.get("CustomField"), *params.keys()]
        for hint in hints:
            try:
                attempt = await call_repo.get(session, uuid.UUID(str(hint)), lock=True)
            except ValueError:
                continue
            if attempt is not None:
                break
    if attempt is None or attempt.call_status not in {s.value for s in STREAMABLE}:
        return None
    if attempt.provider_call_id is None and start.call_sid:
        attempt.provider_call_id = start.call_sid
    elif start.call_sid and attempt.provider_call_id != start.call_sid:
        return None
    attempt.stream_id = start.stream_sid or "unknown"  # non-null = our stream connected
    call_state.transition(attempt, CallStatus.IN_PROGRESS)
    await session.commit()
    return attempt


async def stream_ended(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    attempt_id: uuid.UUID,
    *,
    ended_by: str,
    end_reason: str | None = None,
    failure_reason: str | None = None,
) -> None:
    """The stream is gone; the flow's Hangup step ends the call. `ended_by`: agent | caller |
    error. `end_reason`: how the conversation ended, when the voice pipeline knows (phase-06
    §5.6). The terminal status itself comes from the provider's callback."""
    attempt = await call_repo.get(session, attempt_id, lock=True)
    if attempt is None:
        return
    if attempt.end_reason is None and not call_state.is_terminal(attempt.call_status):
        attempt.end_reason = end_reason or {
            "agent": CallEndReason.AGENT_COMPLETED.value,
            "caller": CallEndReason.CANDIDATE_HANGUP.value,
        }.get(ended_by, CallEndReason.TECHNICAL_FAILURE.value)
        if failure_reason:
            attempt.failure_reason = failure_reason
        elif ended_by == "error":
            attempt.failure_reason = "stream_error"
    await session.commit()
    await call_slots.release(redis, str(attempt.id), size=settings.max_concurrent_calls)


# --- Reconciler -------------------------------------------------------------------------------


def stuck_thresholds(settings: Settings) -> dict[CallStatus, timedelta]:
    return {
        CallStatus.INITIATING: timedelta(minutes=2),
        CallStatus.RINGING: timedelta(seconds=settings.ring_timeout_s + 120),
        CallStatus.IN_PROGRESS: timedelta(seconds=settings.max_call_duration_s + 300),
    }


async def reconcile_attempt(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    attempt: CallAttempt,
    lookup: Callable[[CallAttempt], Awaitable[ProviderCallStatus | None]],
) -> str:
    """Ask the provider about one stuck attempt and apply the answer."""
    status = await lookup(attempt)
    if status is None:
        call_state.transition(
            attempt,
            CallStatus.FAILED,
            end_reason=CallEndReason.TECHNICAL_FAILURE.value,
            failure_reason=(attempt.failure_reason or "") + ";provider_has_no_record",
        )
        outcome = "failed_no_record"
    else:
        if attempt.provider_call_id is None:
            attempt.provider_call_id = status.provider_call_id
        changed = apply_provider_status(attempt, status)
        outcome = f"applied:{status.status}" if changed else f"unchanged:{status.status}"
    record_if_ended(session, attempt, outcome.startswith(("applied", "failed")))
    await session.commit()
    await release_slot_if_done(redis, attempt, settings)
    logger.info("call_reconciled", call_attempt_id=str(attempt.id), outcome=outcome)
    return outcome
