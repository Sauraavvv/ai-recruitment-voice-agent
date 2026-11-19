"""Recruiter dashboard numbers, computed from real data only (no estimates).

Days and "today" are in APP_TIMEZONE. A call counts as *connected* when our stream started
(`stream_id` set) or it reached in_progress/completed with talk time; that's the candidate
actually answering, not just the network picking up.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Date, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    CallAttempt,
    CallStatus,
    Candidate,
    Conversation,
    ScreeningStatus,
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
