"""Automatic retries and callbacks (phase-09, docs/retries.md).

    attempt ended ──► evaluate ──► classify (what happened) ──► decide (the rules)
                                                                   │
        retry      new attempt  retry_scheduled     type=retry     at = retry_time()
        callback   new attempt  callback_requested  type=callback  at = the requested time,
                                                                   moved into the window
        exhausted  this attempt → exhausted (last allowed attempt, retryable outcome)
        none       nothing; the reason is stored (no_retry:<reason>)

    cron, every 5 min ──► dispatch_due ──► re-check ──► queued ──► initiate_call job

`evaluate` is idempotent: the attempt row is locked and `retry_evaluated_at` is set once.
Duplicate dials are prevented by four layers: the one-live-attempt index, the unique
(candidate, attempt_number), FOR UPDATE SKIP LOCKED in the dispatcher and the job id
`call:<attempt id>`.

Counts are per purpose (phase-11 step 6b): screening calls don't use up telephonic round tries,
or the reverse. A retry or callback keeps its attempt's purpose; a telephonic callback keeps the
question set (it resumes where the call stopped), a telephonic retry asks the latest approved one.

All time comes from a `Clock`; times are stored in UTC and the window is evaluated in
APP_TIMEZONE.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import (
    CallAttempt,
    CallAttemptType,
    CallEndReason,
    CallPurpose,
    CallStatus,
    Candidate,
    Conversation,
    Job,
    ScreeningStatus,
)
from app.providers.telephony import exotel_models as em
from app.repositories import call_repo
from app.services import (
    call_service,
    call_state,
    screening_job,
    settings_service,
    sync_service,
    telephonic_service,
)
from app.utils.calling_window import CallingWindow, Half
from app.utils.clock import SYSTEM_CLOCK, Clock
from app.utils.log import get_logger

logger = get_logger(__name__)

Enqueue = Callable[[str], Awaitable[None]]

EARLY_DROP_S = 15  # a call that ends this soon with nothing said counts as dropped
CALLBACK_MAX_AHEAD = timedelta(days=14)
# A call with a conversation is evaluated after finalization; if that never comes, the
# reconciler evaluates it with what's stored after this long
AWAIT_FINALIZATION = timedelta(minutes=15)
EVALUATE_GRACE = timedelta(minutes=2)  # other ended attempts: missed by the webhook path
STALE_QUEUED = timedelta(minutes=10)
DISPATCH_LIMIT = 20
ENQUEUE_RETRY = timedelta(minutes=5)

RETRYABLE = frozenset({"no_answer", "busy", "temporary_failure", "no_response"})
SCHEDULED_STATUS = {
    CallAttemptType.RETRY: CallStatus.RETRY_SCHEDULED,
    CallAttemptType.CALLBACK: CallStatus.CALLBACK_REQUESTED,
}

# --- Rules (pure) -----------------------------------------------------------------------------


@dataclass(frozen=True)
class RetryRules:
    enabled: bool
    max_attempts: int
    interval: timedelta
    unit: str  # days | minutes
    max_callbacks: int
    alternate: bool
    window: CallingWindow

    @classmethod
    def from_settings(cls, settings: Settings) -> "RetryRules":
        unit = settings.retry_interval_unit
        n = settings.retry_interval_days
        return cls(
            enabled=settings.retry_enabled,
            max_attempts=settings.max_call_attempts,
            interval=timedelta(minutes=n) if unit == "minutes" else timedelta(days=n),
            unit=unit,
            max_callbacks=settings.max_callbacks,
            alternate=settings.retry_alternate_slots,
            window=CallingWindow.from_settings(settings),
        )


@dataclass(frozen=True)
class Outcome:
    """What happened on an attempt, in the terms of the phase-09 §6 table."""

    kind: str
    callback_at: datetime | None = None
    callback_text: str | None = None


@dataclass(frozen=True)
class Decision:
    action: str  # retry | callback | exhausted | none
    reason: str
    at: datetime | None = None
    note: str | None = None

    @property
    def code(self) -> str:
        return {
            "retry": "retry_scheduled",
            "callback": "callback_scheduled",
            "exhausted": "exhausted",
        }.get(self.action, f"no_retry:{self.reason}")[:48]


def _duration(attempt: CallAttempt) -> int | None:
    if attempt.duration_seconds is not None:
        return attempt.duration_seconds
    if attempt.start_time and attempt.end_time:
        return max(0, round((attempt.end_time - attempt.start_time).total_seconds()))
    return None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None  # the agent always gives an offset


def classify(
    attempt: CallAttempt, result: dict[str, Any] | None, final: dict[str, Any] | None
) -> Outcome:
    """`result`: the conversation's live result (None: no conversation was stored); `final`:
    the finalized data (phase-07), when there is one."""
    status = attempt.call_status
    if status == CallStatus.CANCELLED:
        return Outcome("cancelled")
    if status == CallStatus.NO_ANSWER:
        return Outcome("no_answer")
    if status == CallStatus.BUSY:
        return Outcome("busy")
    if status == CallStatus.FAILED:
        if attempt.end_reason == CallEndReason.INVALID_NUMBER:
            return Outcome("invalid_number")
        return Outcome("temporary_failure")  # provider 5xx, network, our side, no free line
    # completed: the call was answered
    if not result:
        # Our stream never connected or the conversation wasn't stored: nobody heard the agent
        return Outcome("temporary_failure")
    if result.get("purpose") == "telephonic":
        return classify_round(attempt, result)
    end = str(result.get("end_reason") or "")
    if result.get("opted_out") or end == "opted_out":
        return Outcome("opted_out")
    if end == "declined" or result.get("declined_opportunity"):
        return Outcome("declined")
    if end == "wrong_person":
        return Outcome("wrong_person")
    callback = result.get("callback") or {}
    screening = str((final or {}).get("screening_status") or result.get("screening_status") or "")
    if callback.get("requested") and screening != ScreeningStatus.COMPLETED:
        return _callback_outcome(callback)
    if screening == ScreeningStatus.COMPLETED:
        return Outcome("completed")
    values = (final or {}).get("fields") or {}
    has_data = any((f or {}).get("value") is not None for f in values.values()) or any(
        v is not None for v in (result.get("collected_data") or {}).values()
    )
    if has_data or screening == ScreeningStatus.PARTIALLY_COMPLETED:
        return Outcome("partial")  # manual retry from the attention list (decision 2026-11-19)
    if end == "escalated":
        return Outcome("escalated")
    if end == "error":
        return Outcome("temporary_failure")  # our STT/LLM/TTS failed before screening started
    if end == "no_response":
        return Outcome("no_response")  # nobody spoke (e.g. voicemail picked up)
    duration = _duration(attempt)
    if end == "hangup" and duration is not None and duration < EARLY_DROP_S:
        return Outcome("temporary_failure")  # dropped in the first seconds
    return Outcome("not_started")  # answered, said nothing useful, hung up: no retry


def _callback_outcome(callback: dict[str, Any]) -> Outcome:
    when = None if callback.get("needs_recruiter") else _parse_time(callback.get("time_iso"))
    if when is None:
        return Outcome("vague_callback", callback_text=callback.get("time_text"))
    return Outcome("callback", callback_at=when, callback_text=callback.get("time_text"))


def classify_round(attempt: CallAttempt, result: dict[str, Any]) -> Outcome:
    """An answered telephonic round call (phase-11 step 6b), in the same outcome terms: a
    finished round is completed; a round cut short after some answers is partial (a manual
    retry, as for screening); the side exits and failures are as for screening."""
    end = str(result.get("end_reason") or "")
    if result.get("opted_out") or end == "opted_out":
        return Outcome("opted_out")
    if end == "declined" or result.get("declined_round"):
        return Outcome("declined")
    if end == "wrong_person":
        return Outcome("wrong_person")
    callback = result.get("callback") or {}
    if end == "callback" or (callback.get("requested") and end != "completed"):
        return _callback_outcome(callback)
    if end == "completed":
        return Outcome("completed")
    answers = [a for a in result.get("answers") or [] if isinstance(a, dict)]
    if any(a.get("status") != "not_asked" and not a.get("from_earlier_call") for a in answers):
        return Outcome("partial")
    if end == "escalated":
        return Outcome("escalated")
    if end == "error":
        return Outcome("temporary_failure")
    if end == "no_response":
        return Outcome("no_response")
    duration = _duration(attempt)
    if end == "hangup" and duration is not None and duration < EARLY_DROP_S:
        return Outcome("temporary_failure")
    return Outcome("not_started")


def retry_time(ended_at: datetime, rules: RetryRules, previous: Half | None) -> datetime:
    """When the next attempt is due. Days: the same time of day `interval` calendar days later,
    or, alternating, the window's other half (morning 10:00 / afternoon 14:30); moved to the
    next calling day and into the window. Minutes (staging): `interval` later, inside the
    window."""
    window = rules.window
    if rules.unit == "minutes":
        return window.next_open(ended_at + rules.interval)
    local = window.local(ended_at)
    day = local.date() + timedelta(days=rules.interval.days)
    at = local.time()
    if rules.alternate and previous is not None:
        at = window.start if previous == "afternoon" else window.midpoint
    return window.slot_from(day, at)


def callback_time(
    requested: datetime, now: datetime, window: CallingWindow
) -> tuple[datetime | None, str | None]:
    """The requested time if it's in the future, within 14 days and inside the window; else
    the nearest later slot, with a note. None: can't be scheduled (too far ahead)."""
    if requested > now + CALLBACK_MAX_AHEAD:
        return None, None
    if requested <= now:
        at = window.next_open(now)
        note = f"Callback time {_fmt(requested, window)} had passed; moved to {_fmt(at, window)}"
        return at, note
    at = window.schedulable(requested)
    if at != requested:
        return at, (
            f"Callback asked for {_fmt(requested, window)}, outside calling hours "
            f"({window.describe()}); moved to {_fmt(at, window)}"
        )
    return at, None


def _fmt(when: datetime, window: CallingWindow) -> str:
    return window.local(when).strftime("%a %d %b %H:%M")


@dataclass(frozen=True)
class Counts:
    dialed: int  # initial + retry + manual attempts that ended (incl. this one)
    callbacks: int  # callback attempts (not cancelled), before this decision


def decide(
    outcome: Outcome,
    counts: Counts,
    rules: RetryRules,
    *,
    ended_at: datetime,
    now: datetime,
    previous: Half | None,
) -> Decision:
    if outcome.kind in RETRYABLE:
        if counts.dialed >= rules.max_attempts:
            return Decision("exhausted", outcome.kind)
        if not rules.enabled:
            return Decision("none", "retry_disabled")
        at = max(retry_time(ended_at, rules, previous), rules.window.next_open(now))
        return Decision("retry", outcome.kind, at=at)
    if outcome.kind == "callback":
        assert outcome.callback_at is not None
        if counts.callbacks >= rules.max_callbacks:
            return Decision("none", "callback_limit")
        when, note = callback_time(outcome.callback_at, now, rules.window)
        if when is None:
            return Decision("none", "callback_too_far")
        return Decision("callback", "callback", at=when, note=note)
    return Decision("none", outcome.kind)


# --- Evaluation (database) ----------------------------------------------------------------------


@dataclass
class Evaluation:
    decision: str  # Decision.code, or a waiting state (not_ended, awaiting_finalization)
    new_attempt_id: uuid.UUID | None = None
    note: str | None = None


def stop_reason(candidate: Candidate | None, job: Job | None) -> str | None:
    """Candidates who must not get an automatic call (checked when scheduling and
    dispatching; initiation re-checks opt-out, consent and the job via eligibility)."""
    if candidate is None or candidate.deleted_at is not None:
        return "candidate_deleted"
    if candidate.opted_out:
        return "opted_out"
    if candidate.screening_status in (
        ScreeningStatus.DECLINED,
        ScreeningStatus.OPTED_OUT,
        ScreeningStatus.WRONG_PERSON,
    ):
        return str(candidate.screening_status)
    if job is None or not job.is_active:
        return "job_inactive"
    return None


async def _conversation(session: AsyncSession, attempt_id: uuid.UUID) -> Conversation | None:
    return (
        await session.execute(
            select(Conversation).where(Conversation.call_attempt_id == attempt_id)
        )
    ).scalar_one_or_none()


async def _next_question_set(
    session: AsyncSession,
    attempt: CallAttempt,
    candidate: Candidate | None,
    kind: CallAttemptType,
) -> uuid.UUID | None:
    """The question set a telephonic retry or callback asks: a callback resumes the same set;
    a retry (nothing was asked) takes the latest approved one."""
    if attempt.purpose != CallPurpose.TELEPHONIC:
        return None
    if kind == CallAttemptType.RETRY and candidate is not None:
        latest = await telephonic_service.latest_approved_id(session, candidate.requirement_id)
        if latest is not None:
            return latest
    return attempt.question_set_id


def _previous_half(attempt: CallAttempt, window: CallingWindow) -> Half | None:
    when = attempt.start_time or attempt.end_time or attempt.updated_at or attempt.created_at
    return window.half(when) if when else None


async def evaluate(
    session: AsyncSession,
    attempt_id: uuid.UUID,
    settings: Settings,
    *,
    clock: Clock = SYSTEM_CLOCK,
    force: bool = False,
) -> Evaluation:
    """Decide and apply the retry rules for one ended attempt. Idempotent. `settings` must be
    the effective settings. `force`: don't wait for finalization (the reconciler)."""
    now = clock.now()
    attempt = await call_repo.get(session, attempt_id, lock=True)
    if attempt is None:
        await session.commit()
        return Evaluation("not_found")
    if attempt.retry_evaluated_at is not None:
        await session.commit()  # nothing changed; ends the transaction, keeps loaded objects
        return Evaluation(attempt.retry_decision or "done", note=attempt.retry_note)
    if attempt.call_status not in call_state.OUTCOMES | {CallStatus.CANCELLED}:
        await session.commit()
        return Evaluation("not_ended")

    conv = await _conversation(session, attempt.id)
    data = (conv.extracted_data or {}) if conv else {}
    result = data.get("result") if isinstance(data.get("result"), dict) else None
    final = data.get("final") if isinstance(data.get("final"), dict) else None
    if (
        attempt.call_status == CallStatus.COMPLETED
        and attempt.stream_id is not None
        and conv is not None
        and conv.finalized_at is None
        and not force
    ):
        # The decision needs the conversation's outcome: finalization calls evaluate again
        await session.commit()
        return Evaluation("awaiting_finalization")

    candidate = await session.get(Candidate, attempt.candidate_id, with_for_update=True)
    job = await screening_job.for_candidate(session, candidate)
    rules = RetryRules.from_settings(settings)
    outcome = classify(attempt, result, final)

    newer = await session.scalar(
        select(
            exists().where(
                CallAttempt.candidate_id == attempt.candidate_id,
                CallAttempt.purpose == attempt.purpose,
                CallAttempt.attempt_number > attempt.attempt_number,
            )
        )
    )
    stop = stop_reason(candidate, job)
    if outcome.kind == "cancelled":
        decision = Decision("none", "cancelled")
    elif newer:
        decision = Decision("none", "superseded")  # e.g. a recruiter already called again
    elif stop and (outcome.kind in RETRYABLE or outcome.kind == "callback"):
        decision = Decision("none", stop)
    else:
        dialed, callbacks = (
            await call_repo.attempt_counts(session, [attempt.candidate_id], purpose=attempt.purpose)
        )[attempt.candidate_id]
        ended_at = attempt.end_time or attempt.updated_at or now
        decision = decide(
            outcome,
            Counts(dialed=dialed, callbacks=callbacks),
            rules,
            ended_at=ended_at,
            now=now,
            previous=_previous_half(attempt, rules.window),
        )

    new_attempt: CallAttempt | None = None
    if decision.action in ("retry", "callback"):
        kind = CallAttemptType.RETRY if decision.action == "retry" else CallAttemptType.CALLBACK
        new_attempt = CallAttempt(
            candidate_id=attempt.candidate_id,
            attempt_number=await call_repo.next_attempt_number(session, attempt.candidate_id),
            attempt_type=kind.value,
            purpose=attempt.purpose,
            question_set_id=await _next_question_set(session, attempt, candidate, kind),
            provider=em.PROVIDER,
            call_status=SCHEDULED_STATUS[kind].value,
            next_retry_at=decision.at,
            retry_count=attempt.retry_count + (1 if kind == CallAttemptType.RETRY else 0),
        )
        try:
            async with session.begin_nested():
                session.add(new_attempt)
        except IntegrityError:
            # Another live or scheduled attempt exists for this candidate
            new_attempt = None
            decision = Decision("none", "already_scheduled")
    elif decision.action == "exhausted":
        call_state.mark_exhausted(attempt)

    attempt.retry_decision = decision.code
    attempt.retry_note = decision.note
    attempt.retry_evaluated_at = now
    if new_attempt is not None or decision.action == "exhausted":
        sync_service.record_change(session, attempt.candidate_id)  # Call Status, Next Retry
    await session.commit()
    logger.info(
        "retry_evaluated",
        call_attempt_id=str(attempt.id),
        candidate_id=str(attempt.candidate_id),
        outcome=outcome.kind,
        decision=decision.code,
        next_attempt_id=str(new_attempt.id) if new_attempt else None,
        next_retry_at=decision.at.isoformat() if decision.at and new_attempt else None,
        note=decision.note,
    )
    return Evaluation(
        decision.code, new_attempt_id=new_attempt.id if new_attempt else None, note=decision.note
    )


async def evaluate_safely(
    session: AsyncSession,
    attempt_id: uuid.UUID,
    settings: Settings,
    *,
    clock: Clock = SYSTEM_CLOCK,
) -> Evaluation | None:
    """`evaluate` with the effective settings, for the webhook and worker paths: an error is
    logged, never raised (the reconciler evaluates the attempt later)."""
    try:
        effective = await settings_service.effective(session, settings)
        return await evaluate(session, attempt_id, effective, clock=clock)
    except Exception:
        await session.rollback()
        logger.exception("retry_evaluate_failed", call_attempt_id=str(attempt_id))
        return None


async def evaluate_pending(
    session: AsyncSession, settings: Settings, *, clock: Clock = SYSTEM_CLOCK, limit: int = 50
) -> int:
    """Reconciler: ended attempts nobody evaluated (webhook lost, worker down, finalization
    never ran)."""
    now = clock.now()
    ended = [s.value for s in call_state.OUTCOMES | {CallStatus.CANCELLED}]
    with_conversation = and_(
        CallAttempt.call_status == CallStatus.COMPLETED.value,
        CallAttempt.stream_id.is_not(None),
    )
    rows = await session.execute(
        select(CallAttempt.id)
        .where(
            CallAttempt.retry_evaluated_at.is_(None),
            CallAttempt.call_status.in_(ended),
            or_(
                and_(with_conversation, CallAttempt.updated_at <= now - AWAIT_FINALIZATION),
                and_(~with_conversation, CallAttempt.updated_at <= now - EVALUATE_GRACE),
            ),
        )
        .order_by(CallAttempt.updated_at)
        .limit(limit)
    )
    ids = list(rows.scalars())
    await session.commit()
    for aid in ids:
        try:
            await evaluate(session, aid, settings, clock=clock, force=True)
        except Exception:
            await session.rollback()
            logger.exception("retry_evaluate_failed", call_attempt_id=str(aid))
    return len(ids)


# --- Dispatch ---------------------------------------------------------------------------------


@dataclass
class DispatchResult:
    queued: list[str] = field(default_factory=list)
    moved: int = 0  # outside the window: moved to the next opening
    held: int = 0  # paused or telephony not configured: left scheduled
    cancelled: int = 0
    enqueue_failed: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.queued or self.cancelled)


async def dispatch_due(
    session: AsyncSession,
    settings: Settings,
    enqueue: Enqueue,
    *,
    clock: Clock = SYSTEM_CLOCK,
    limit: int = DISPATCH_LIMIT,
) -> DispatchResult:
    """Due retries and callbacks → re-check → queued → `initiate_call`. `settings` must be the
    effective settings."""
    now = clock.now()
    window = CallingWindow.from_settings(settings)
    out = DispatchResult()
    rows = (
        (
            await session.execute(
                select(CallAttempt)
                .where(
                    CallAttempt.call_status.in_(call_repo.SCHEDULED_STATUSES),
                    CallAttempt.next_retry_at <= now,
                )
                .order_by(CallAttempt.next_retry_at)
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    for attempt in rows:
        candidate = await session.get(Candidate, attempt.candidate_id)
        job = await screening_job.for_candidate(session, candidate)
        problem = stop_reason(candidate, job)
        if problem is None:
            problem = await call_service.check_eligibility(
                session,
                candidate,
                settings,
                now=now,
                own_attempt_id=attempt.id,
                purpose=attempt.purpose,
            )
            if problem is None:
                dialed, _ = (
                    await call_repo.attempt_counts(
                        session, [attempt.candidate_id], purpose=attempt.purpose
                    )
                )[attempt.candidate_id]
                retry = attempt.attempt_type == CallAttemptType.RETRY
                if retry and dialed >= settings.max_call_attempts:
                    problem = call_service.Ineligible.MAX_ATTEMPTS  # max lowered meanwhile
        if problem == call_service.Ineligible.OUTSIDE_WINDOW:
            attempt.next_retry_at = window.next_open(now)
            out.moved += 1
            continue
        if problem in (call_service.Ineligible.PAUSED, call_service.Ineligible.NOT_CONFIGURED):
            out.held += 1  # stays due; dispatched once calling is resumed or set up
            continue
        if problem is not None:  # opted out, deleted, declined, no consent, job closed, …
            reason = problem
            call_state.transition(
                attempt,
                CallStatus.CANCELLED,
                now=now,
                end_reason=CallEndReason.CANCELLED.value,
                failure_reason=f"ineligible:{reason}",
            )
            attempt.retry_decision = f"no_retry:{reason}"[:48]
            attempt.retry_evaluated_at = now
            sync_service.record_change(session, attempt.candidate_id)
            out.cancelled += 1
            continue
        call_state.transition(attempt, CallStatus.QUEUED, now=now)
        sync_service.record_change(session, attempt.candidate_id)  # Call Status in the sheet
        out.queued.append(str(attempt.id))
    await session.commit()

    for aid in out.queued:
        try:
            await enqueue(aid)
        except Exception:
            logger.exception("retry_enqueue_failed", call_attempt_id=aid)
            out.enqueue_failed += 1
            await _unqueue(session, uuid.UUID(aid), now + ENQUEUE_RETRY)
    if rows:
        logger.info(
            "retries_dispatched",
            queued=len(out.queued),
            moved=out.moved,
            held=out.held,
            cancelled=out.cancelled,
            enqueue_failed=out.enqueue_failed or None,
        )
    return out


async def _unqueue(session: AsyncSession, attempt_id: uuid.UUID, at: datetime) -> None:
    """Put a queued retry or callback back on the schedule (its job couldn't be queued, or the
    window closed or calling was paused before it dialed)."""
    attempt = await call_repo.get(session, attempt_id, lock=True)
    if attempt is not None:
        reschedule(attempt, at)
    await session.commit()


def reschedule(attempt: CallAttempt, at: datetime) -> bool:
    """queued → retry_scheduled | callback_requested at `at`. Only for automatic attempts."""
    kind = CallAttemptType(attempt.attempt_type)
    target = SCHEDULED_STATUS.get(kind)
    if target is None or not call_state.transition(attempt, target):
        return False
    attempt.next_retry_at = at
    return True


async def requeue_stale(
    session: AsyncSession, enqueue: Enqueue, *, clock: Clock = SYSTEM_CLOCK
) -> int:
    """Queued attempts whose job may have been lost (e.g. the worker stopped between the
    dispatcher's commit and the enqueue). Enqueueing again is safe: the job id is the attempt
    id, so a job that still exists isn't duplicated, and `initiate_call` dials only a queued
    attempt."""
    now = clock.now()
    ids = list(
        (
            await session.execute(
                select(CallAttempt.id).where(
                    CallAttempt.call_status == CallStatus.QUEUED.value,
                    CallAttempt.updated_at <= now - STALE_QUEUED,
                )
            )
        ).scalars()
    )
    await session.commit()
    for aid in ids:
        try:
            await enqueue(str(aid))
        except Exception:
            logger.exception("retry_requeue_failed", call_attempt_id=str(aid))
    if ids:
        logger.info("queued_calls_requeued", count=len(ids))
    return len(ids)


# --- Resuming a call (P9-T6) -------------------------------------------------------------------

_RESUMABLE = frozenset({"answered", "confirmed", "declined"})


def known_answers(candidate: Candidate) -> dict[str, dict[str, Any]]:
    """Answers the candidate gave on earlier calls, for the agent's state (phase-06 §5.9):
    values with their status, and fields they declined (declined stays declined). Values the
    recruiter typed or imported aren't included: those are still asked."""
    out: dict[str, dict[str, Any]] = {}
    for key, entry in (candidate.screening_field_meta or {}).items():
        if not isinstance(entry, dict) or not entry.get("call_attempt_id"):
            continue
        status = str(entry.get("status") or "")
        value = entry.get("value")
        if status not in _RESUMABLE or (value is None and status != "declined"):
            continue
        out[key] = {
            "value": value,
            "status": status,
            "raw_text": entry.get("raw_text"),
            "meta": {"source": "prior_call"},
        }
    return out


def call_kind(attempt_type: str, prior: dict[str, Any]) -> str:
    if attempt_type == CallAttemptType.CALLBACK:
        return "callback"
    return "resume" if any(v.get("value") is not None for v in prior.values()) else "first"
