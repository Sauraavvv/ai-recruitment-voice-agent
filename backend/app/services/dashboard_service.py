"""Recruiter dashboard numbers, computed from real data only (no estimates).

Days and "today" are in APP_TIMEZONE. A call counts as *connected* when our stream started
(`stream_id` set) or it reached in_progress/completed with talk time; that's the candidate
actually answering, not just the network picking up.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, and_, cast, func, or_, select, true
from sqlalchemy.dialects.postgresql import JSONPATH, distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.database.models import (
    CallAttempt,
    CallStatus,
    Candidate,
    Conversation,
    ScreeningStatus,
    SyncLog,
    SyncStatus,
)

LIVE = (CallStatus.QUEUED, CallStatus.INITIATING, CallStatus.RINGING, CallStatus.IN_PROGRESS)
DAYS = 14
TRANSCRIPT_TAIL = 8


def _connected() -> Any:
    return or_(
        CallAttempt.stream_id.is_not(None),
        and_(
            CallAttempt.call_status == CallStatus.COMPLETED,
            func.coalesce(CallAttempt.duration_seconds, 0) > 0,
        ),
    )


async def summary(session: AsyncSession, *, tz: str, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    zone = ZoneInfo(tz)
    today = now.astimezone(zone).date()
    first_day = today - timedelta(days=DAYS - 1)
    local_day = cast(func.timezone(tz, CallAttempt.created_at), Date)
    active = Candidate.deleted_at.is_(None)

    # --- candidates -------------------------------------------------------------------------
    cand = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Candidate.screening_status == ScreeningStatus.COMPLETED),
                func.count().filter(Candidate.interested.is_(True)),
                func.count().filter(Candidate.opted_out.is_(True)),
            ).where(active)
        )
    ).one()
    candidates_total, screened, interested, opted_out = (int(v) for v in cand)

    # --- calls ------------------------------------------------------------------------------
    calls = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(_connected()),
                func.avg(CallAttempt.duration_seconds).filter(_connected()),
                func.count().filter(local_day == today),
                func.count(func.distinct(CallAttempt.candidate_id)),
                func.count(func.distinct(CallAttempt.candidate_id)).filter(_connected()),
            )
        )
    ).one()
    calls_total, connected, avg_duration, calls_today, called_people, connected_people = calls

    by_day_rows = (
        await session.execute(
            select(
                local_day.label("day"),
                func.count(),
                func.count().filter(_connected()),
            )
            .where(local_day >= first_day)
            .group_by("day")
        )
    ).all()
    by_day = {row[0]: (int(row[1]), int(row[2])) for row in by_day_rows}
    calls_by_day = []
    for i in range(DAYS):
        day: date = first_day + timedelta(days=i)
        total, conn = by_day.get(day, (0, 0))
        calls_by_day.append({"date": day.isoformat(), "total": total, "connected": conn})

    outcome_rows = (
        await session.execute(
            select(CallAttempt.call_status, func.count()).group_by(CallAttempt.call_status)
        )
    ).all()
    outcomes = {str(status): int(n) for status, n in outcome_rows}

    # --- live calls -------------------------------------------------------------------------
    live_rows = (
        await session.execute(
            select(CallAttempt, Candidate.name, Candidate.applied_role)
            .join(Candidate, Candidate.id == CallAttempt.candidate_id)
            .where(CallAttempt.call_status.in_([s.value for s in LIVE]))
            .order_by(CallAttempt.created_at)
            .limit(10)
        )
    ).all()
    live_calls = [
        {
            "call_attempt_id": a.id,
            "candidate_id": a.candidate_id,
            "candidate_name": name,
            "applied_role": role,
            "call_status": a.call_status,
            "started_at": a.start_time or a.created_at,
        }
        for a, name, role in live_rows
    ]

    # --- latest finished conversation -------------------------------------------------------
    latest_row = (
        await session.execute(
            select(Conversation, CallAttempt, Candidate.name)
            .join(CallAttempt, CallAttempt.id == Conversation.call_attempt_id)
            .join(Candidate, Candidate.id == CallAttempt.candidate_id)
            .where(func.jsonb_array_length(Conversation.transcript) > 0)
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
    ).first()
    latest = None
    if latest_row is not None:
        conv, attempt, name = latest_row
        entries = [
            {"speaker": e.get("speaker"), "text": e.get("text")}
            for e in conv.transcript
            if isinstance(e, dict) and e.get("text")
        ]
        latest = {
            "call_attempt_id": attempt.id,
            "candidate_id": attempt.candidate_id,
            "candidate_name": name,
            "ended_at": attempt.end_time or conv.created_at,
            "duration_seconds": attempt.duration_seconds,
            "turns": len(entries),
            "transcript": entries[-TRANSCRIPT_TAIL:],
        }

    # --- interview availability -------------------------------------------------------------
    avail_rows = (
        await session.execute(
            select(
                Candidate.id,
                Candidate.name,
                Candidate.interview_availability,
                Candidate.notice_period,
                Candidate.updated_at,
            )
            .where(
                active,
                Candidate.interested.is_(True),
                Candidate.interview_availability.is_not(None),
            )
            .order_by(Candidate.updated_at.desc())
            .limit(6)
        )
    ).all()
    interviews = [
        {
            "candidate_id": cid,
            "candidate_name": name,
            "availability": availability,
            "notice_period": notice,
            "updated_at": updated,
        }
        for cid, name, availability, notice, updated in avail_rows
    ]

    def rate(part: int, whole: int) -> float | None:
        return round(part / whole, 4) if whole else None

    return {
        "kpis": {
            "candidates_total": candidates_total,
            "screened": screened,
            "interested": interested,
            "interested_rate": rate(interested, screened),
            "opted_out": opted_out,
            "calls_total": int(calls_total),
            "calls_today": int(calls_today),
            "calls_connected": int(connected),
            "connect_rate": rate(int(connected), int(calls_total)),
            "avg_call_seconds": round(float(avg_duration)) if avg_duration is not None else None,
        },
        "funnel": {
            "candidates": candidates_total,
            "called": int(called_people),
            "connected": int(connected_people),
            "screened": screened,
            "interested": interested,
        },
        "calls_by_day": calls_by_day,
        "outcomes": outcomes,
        "live_calls": live_calls,
        "latest_conversation": latest,
        "interview_availability": interviews,
        "generated_at": now,
    }


# --- Phase 8: stat tiles, activity, needs attention (phase-08 §5.1, §5.2) -------------------

PENDING = (CallStatus.PENDING, CallStatus.QUEUED, CallStatus.INITIATING)
IN_PROGRESS = (CallStatus.RINGING, CallStatus.IN_PROGRESS)
UNANSWERED = (CallStatus.NO_ANSWER, CallStatus.BUSY)
SCHEDULED = (CallStatus.RETRY_SCHEDULED, CallStatus.CALLBACK_REQUESTED)
RANGES = ("today", "7d", "all")

# Shown as the tiles' tooltips (agreed definitions, phase-08 §5.1)
DEFINITIONS = {
    "total_candidates": "Candidates not deleted",
    "calls_completed": "Call attempts that ended as completed (answered and hung up)",
    "calls_pending": "Call attempts pending, queued or dialing right now",
    "calls_in_progress": "Call attempts ringing or on the call right now",
    "unanswered_calls": "Candidates whose latest call was not answered or busy",
    "failed_calls": "Candidates whose latest call failed",
    "interested_candidates": "Candidates who said they are interested",
    "screening_completed": "Candidates whose screening is completed",
    "scheduled_retries": "Call attempts with a retry or a callback scheduled",
}


def _vals(statuses: tuple[CallStatus, ...]) -> list[str]:
    return [s.value for s in statuses]


def range_start(range_: str, *, tz: str, now: datetime) -> datetime | None:
    if range_ == "today":
        local = now.astimezone(ZoneInfo(tz))
        return local.replace(hour=0, minute=0, second=0, microsecond=0)
    if range_ == "7d":
        return now - timedelta(days=7)
    return None


def _latest_attempts() -> Any:
    """Each active candidate's newest attempt (subquery: candidate_id, call_status, created_at)."""
    return (
        select(
            CallAttempt.candidate_id,
            CallAttempt.call_status,
            CallAttempt.created_at,
        )
        .join(Candidate, Candidate.id == CallAttempt.candidate_id)
        .where(Candidate.deleted_at.is_(None))
        .ext(distinct_on(CallAttempt.candidate_id))
        .order_by(CallAttempt.candidate_id, CallAttempt.attempt_number.desc())
        .subquery()
    )


async def stats(
    session: AsyncSession, *, tz: str, range_: str = "all", now: datetime | None = None
) -> dict[str, Any]:
    """The stat tiles. Each is one query over real rows; an empty database gives zeros.
    `range_` limits the call outcome metrics (completed, unanswered, failed) by when the call
    was placed; current states (pending, in progress, scheduled) are always "now"."""
    now = now or datetime.now(UTC)
    since = range_start(range_, tz=tz, now=now)
    active = Candidate.deleted_at.is_(None)

    total, interested, screened = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Candidate.interested.is_(True)),
                func.count().filter(Candidate.screening_status == ScreeningStatus.COMPLETED),
            ).where(active)
        )
    ).one()

    in_range = CallAttempt.created_at >= since if since else true()
    completed, pending, in_progress, scheduled = (
        await session.execute(
            select(
                func.count().filter(CallAttempt.call_status == CallStatus.COMPLETED, in_range),
                func.count().filter(CallAttempt.call_status.in_(_vals(PENDING))),
                func.count().filter(CallAttempt.call_status.in_(_vals(IN_PROGRESS))),
                func.count().filter(CallAttempt.call_status.in_(_vals(SCHEDULED))),
            )
        )
    ).one()

    latest = _latest_attempts()
    latest_in_range = latest.c.created_at >= since if since else true()
    unanswered, failed = (
        await session.execute(
            select(
                func.count().filter(latest.c.call_status.in_(_vals(UNANSWERED)), latest_in_range),
                func.count().filter(latest.c.call_status == CallStatus.FAILED, latest_in_range),
            ).select_from(latest)
        )
    ).one()

    return {
        "range": range_,
        "total_candidates": int(total),
        "calls_completed": int(completed),
        "calls_pending": int(pending),
        "calls_in_progress": int(in_progress),
        "unanswered_calls": int(unanswered),
        "failed_calls": int(failed),
        "interested_candidates": int(interested),
        "screening_completed": int(screened),
        "scheduled_retries": int(scheduled),
        "definitions": DEFINITIONS,
        "generated_at": now,
    }


async def activity(session: AsyncSession, *, limit: int = 20) -> list[dict[str, Any]]:
    """The latest call status changes: each attempt at its current status, newest change
    first. (Attempts keep no status history; the provider events are in webhook_events.)"""
    rows = (
        await session.execute(
            select(CallAttempt, Candidate.name)
            .join(Candidate, Candidate.id == CallAttempt.candidate_id)
            .order_by(CallAttempt.updated_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "call_attempt_id": a.id,
            "candidate_id": a.candidate_id,
            "candidate_name": name,
            "attempt_number": a.attempt_number,
            "call_status": a.call_status,
            "end_reason": a.end_reason,
            "at": a.updated_at,
        }
        for a, name in rows
    ]


ATTENTION_ORDER = (
    "callback_due",
    "data_conflict",
    "unanswered_question",
    "vague_callback",
    "technical_failure",
    "partially_completed",
    "wrong_person",
    "attempts_exhausted",
    "sheets_sync_failed",
)
ATTENTION_LIMIT = 100


def _result_of(conv: Conversation) -> dict[str, Any]:
    data = conv.extracted_data or {}
    result = data.get("result")
    return result if isinstance(result, dict) else data  # Phase 5 rows kept the result flat


async def attention(
    session: AsyncSession, *, now: datetime | None = None, limit: int = ATTENTION_LIMIT
) -> list[dict[str, Any]]:
    """Candidates a recruiter should look at, each with a reason code and the details."""
    from app.services.candidate_view_service import open_conflicts

    now = now or datetime.now(UTC)
    items: list[dict[str, Any]] = []

    def add(cand: Candidate | Any, reason: str, at: datetime | None, **detail: Any) -> None:
        items.append(
            {
                "candidate_id": cand.id,
                "candidate_name": cand.name,
                "reason": reason,
                "at": at,
                "call_attempt_id": detail.pop("call_attempt_id", None),
                "detail": detail.pop("detail", None),
                "conflict": detail.pop("conflict", None),
            }
        )

    callable_ = and_(Candidate.deleted_at.is_(None), Candidate.opted_out.is_(False))

    # Latest attempt per candidate: technical failures, exhausted, callbacks scheduled (P9)
    latest = (
        select(CallAttempt)
        .join(Candidate, Candidate.id == CallAttempt.candidate_id)
        .where(Candidate.deleted_at.is_(None))
        .ext(distinct_on(CallAttempt.candidate_id))
        .order_by(CallAttempt.candidate_id, CallAttempt.attempt_number.desc())
        .subquery()
    )
    last = aliased(CallAttempt, latest)
    rows = (
        await session.execute(
            select(last, Candidate)
            .join(Candidate, Candidate.id == last.candidate_id)
            .where(
                callable_,
                last.call_status.in_(
                    [
                        CallStatus.FAILED.value,
                        CallStatus.EXHAUSTED.value,
                        CallStatus.CALLBACK_REQUESTED.value,
                        CallStatus.RETRY_SCHEDULED.value,
                    ]
                ),
            )
        )
    ).all()
    for attempt, cand in rows:
        if attempt.call_status == CallStatus.FAILED:
            add(
                cand,
                "technical_failure",
                attempt.updated_at,
                call_attempt_id=attempt.id,
                detail=attempt.end_reason,
            )
        elif attempt.call_status == CallStatus.EXHAUSTED:
            add(cand, "attempts_exhausted", attempt.updated_at, call_attempt_id=attempt.id)
        elif (
            attempt.call_status == CallStatus.CALLBACK_REQUESTED
            and attempt.next_retry_at is not None
            and attempt.next_retry_at <= now + timedelta(hours=24)
        ):
            add(
                cand,
                "callback_due",
                attempt.next_retry_at,
                call_attempt_id=attempt.id,
                detail=attempt.next_retry_at.isoformat(),
            )

    # Latest conversation per candidate: callback requests, questions for a recruiter
    conv_rows = (
        await session.execute(
            select(Conversation, CallAttempt, Candidate)
            .join(CallAttempt, CallAttempt.id == Conversation.call_attempt_id)
            .join(Candidate, Candidate.id == CallAttempt.candidate_id)
            .where(callable_)
            .ext(distinct_on(CallAttempt.candidate_id))
            .order_by(CallAttempt.candidate_id, CallAttempt.attempt_number.desc())
        )
    ).all()
    scheduled = {i["candidate_id"] for i in items if i["reason"] == "callback_due"}
    for conv, attempt, cand in conv_rows:
        result = _result_of(conv)
        callback = result.get("callback") or {}
        at = attempt.end_time or conv.created_at
        if callback.get("requested") and cand.id not in scheduled:
            when = _parse_time(callback.get("time_iso"))
            if when is None or callback.get("needs_recruiter"):
                add(
                    cand,
                    "vague_callback",
                    at,
                    call_attempt_id=attempt.id,
                    detail=callback.get("time_text") or "no time given",
                )
            elif when <= now + timedelta(hours=24):
                add(
                    cand,
                    "callback_due",
                    when,
                    call_attempt_id=attempt.id,
                    detail=callback.get("time_text") or when.isoformat(),
                )
        if result.get("escalation_reason") or attempt.end_reason == "escalated":
            add(
                cand,
                "unanswered_question",
                at,
                call_attempt_id=attempt.id,
                detail=result.get("escalation_reason")
                or "; ".join((result.get("candidate_questions") or [])[-2:])
                or None,
            )

    # Screening status
    status_rows = (
        (
            await session.execute(
                select(Candidate).where(
                    callable_,
                    Candidate.screening_status.in_(
                        [
                            ScreeningStatus.PARTIALLY_COMPLETED.value,
                            ScreeningStatus.WRONG_PERSON.value,
                        ]
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    for cand in status_rows:
        add(cand, str(cand.screening_status), cand.updated_at)

    # Data conflicts from the final pass (one item per field, Keep / Use in the UI)
    conflict_rows = (
        (
            await session.execute(
                select(Candidate).where(
                    Candidate.deleted_at.is_(None),
                    func.jsonb_path_exists(
                        Candidate.screening_field_meta,
                        cast('$.* ? (@.conflict.type() == "object")', JSONPATH),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    for cand in conflict_rows:
        for c in open_conflicts(cand):
            add(
                cand,
                "data_conflict",
                cand.updated_at,
                call_attempt_id=c["call_attempt_id"],
                detail=c["field"],
                conflict=c,
            )

    # Sheets: the candidate's latest outbox row failed
    latest_sync = (
        select(SyncLog)
        .ext(distinct_on(SyncLog.candidate_id))
        .order_by(SyncLog.candidate_id, SyncLog.created_at.desc())
        .subquery()
    )
    sync = aliased(SyncLog, latest_sync)
    sync_rows = (
        await session.execute(
            select(sync, Candidate)
            .join(Candidate, Candidate.id == sync.candidate_id)
            .where(Candidate.deleted_at.is_(None), sync.sync_status == SyncStatus.FAILED.value)
        )
    ).all()
    for row, cand in sync_rows:
        add(cand, "sheets_sync_failed", row.updated_at, detail=(row.error_message or "")[:200])

    order = {r: i for i, r in enumerate(ATTENTION_ORDER)}
    items.sort(key=lambda i: (order.get(i["reason"], 99), -(i["at"].timestamp() if i["at"] else 0)))
    return items[:limit]


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
