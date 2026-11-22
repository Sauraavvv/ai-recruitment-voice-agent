"""Call attempt and webhook event queries. No business rules here (see call_service)."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, true
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import (
    LIVE_CALL_STATUSES,
    CallAttempt,
    CallAttemptType,
    CallEndReason,
    CallPurpose,
    CallStatus,
    Candidate,
    WebhookEvent,
)
from app.repositories.candidate_repo import escape_like

SCHEDULED_STATUSES = (CallStatus.RETRY_SCHEDULED.value, CallStatus.CALLBACK_REQUESTED.value)
# Attempts that ended after dialing (or trying to): these count toward max_attempts
DIALED_STATUSES = (
    CallStatus.COMPLETED.value,
    CallStatus.FAILED.value,
    CallStatus.NO_ANSWER.value,
    CallStatus.BUSY.value,
    CallStatus.EXHAUSTED.value,
)
COUNTED_TYPES = (
    CallAttemptType.INITIAL.value,
    CallAttemptType.RETRY.value,
    CallAttemptType.MANUAL.value,
)


async def get(
    session: AsyncSession, attempt_id: uuid.UUID, *, lock: bool = False
) -> CallAttempt | None:
    stmt = select(CallAttempt).where(CallAttempt.id == attempt_id)
    if lock:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_by_provider_call(
    session: AsyncSession, provider: str, provider_call_id: str, *, lock: bool = False
) -> CallAttempt | None:
    stmt = select(CallAttempt).where(
        CallAttempt.provider == provider, CallAttempt.provider_call_id == provider_call_id
    )
    if lock:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def live_for_candidate(
    session: AsyncSession, candidate_id: uuid.UUID, *, include_scheduled: bool = True
) -> CallAttempt | None:
    statuses = [s.value for s in LIVE_CALL_STATUSES]
    if not include_scheduled:
        statuses = [s for s in statuses if s not in SCHEDULED_STATUSES]
    stmt = select(CallAttempt).where(
        CallAttempt.candidate_id == candidate_id, CallAttempt.call_status.in_(statuses)
    )
    return (await session.execute(stmt)).scalars().first()


def _of_purpose(purpose: CallPurpose | str | None) -> Any:
    return true() if purpose is None else CallAttempt.purpose == str(purpose)


async def attempt_counts(
    session: AsyncSession,
    candidate_ids: Sequence[uuid.UUID],
    *,
    purpose: CallPurpose | str | None,
) -> dict[uuid.UUID, tuple[int, int]]:
    """Per candidate: (dialed attempts that count toward max_attempts, callbacks scheduled or
    made), for one purpose (screening calls don't use up telephonic tries, or the reverse;
    None: all). Cancelled attempts never count."""
    if not candidate_ids:
        return {}
    counted = and_(
        CallAttempt.attempt_type.in_(COUNTED_TYPES), CallAttempt.call_status.in_(DIALED_STATUSES)
    )
    callbacks = and_(
        CallAttempt.attempt_type == CallAttemptType.CALLBACK.value,
        CallAttempt.call_status != CallStatus.CANCELLED.value,
    )
    rows = await session.execute(
        select(
            CallAttempt.candidate_id,
            func.count().filter(counted),
            func.count().filter(callbacks),
        )
        .where(CallAttempt.candidate_id.in_(list(candidate_ids)), _of_purpose(purpose))
        .group_by(CallAttempt.candidate_id)
    )
    out = {cid: (0, 0) for cid in candidate_ids}
    out.update({cid: (int(d), int(c)) for cid, d, c in rows.all()})
    return out


async def completed_rounds(
    session: AsyncSession, candidate_ids: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    """Candidates with a telephonic round call the agent finished (answered, and ended by the
    agent after the questions, not a callback, decline or hang-up)."""
    if not candidate_ids:
        return set()
    stmt = select(CallAttempt.candidate_id).where(
        CallAttempt.candidate_id.in_(list(candidate_ids)),
        CallAttempt.purpose == CallPurpose.TELEPHONIC.value,
        CallAttempt.call_status == CallStatus.COMPLETED.value,
        CallAttempt.end_reason == CallEndReason.AGENT_COMPLETED.value,
    )
    return set((await session.execute(stmt)).scalars())


async def scheduled_for_candidates(
    session: AsyncSession,
    candidate_ids: Sequence[uuid.UUID],
    *,
    purpose: CallPurpose | str | None = None,
) -> dict[uuid.UUID, CallAttempt]:
    """Each candidate's scheduled retry or callback (at most one: the one-live index)."""
    if not candidate_ids:
        return {}
    stmt = select(CallAttempt).where(
        CallAttempt.candidate_id.in_(list(candidate_ids)),
        CallAttempt.call_status.in_(SCHEDULED_STATUSES),
        _of_purpose(purpose),
    )
    return {a.candidate_id: a for a in (await session.execute(stmt)).scalars()}


async def next_attempt_number(session: AsyncSession, candidate_id: uuid.UUID) -> int:
    stmt = select(func.coalesce(func.max(CallAttempt.attempt_number), 0)).where(
        CallAttempt.candidate_id == candidate_id
    )
    return int((await session.execute(stmt)).scalar_one()) + 1


async def in_statuses_since(
    session: AsyncSession, statuses: Sequence[str], updated_before: datetime
) -> list[CallAttempt]:
    stmt = select(CallAttempt).where(
        CallAttempt.call_status.in_(list(statuses)), CallAttempt.updated_at < updated_before
    )
    return list((await session.execute(stmt)).scalars())


async def search(
    session: AsyncSession,
    *,
    candidate_id: uuid.UUID | None,
    status: str | Sequence[str] | None,
    page: int,
    page_size: int,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    q: str | None = None,
    purpose: CallPurpose | str | None = None,
) -> tuple[list[tuple[CallAttempt, str, str]], int]:
    """Attempts newest first, with the candidate's name and applied role."""
    stmt = (
        select(CallAttempt, Candidate.name, Candidate.applied_role)
        .join(Candidate, Candidate.id == CallAttempt.candidate_id)
        .where(_of_purpose(purpose))
    )
    if candidate_id:
        stmt = stmt.where(CallAttempt.candidate_id == candidate_id)
    if isinstance(status, str):
        stmt = stmt.where(CallAttempt.call_status == status)
    elif status:
        stmt = stmt.where(CallAttempt.call_status.in_(list(status)))
    if created_from:
        stmt = stmt.where(CallAttempt.created_at >= created_from)
    if created_to:
        stmt = stmt.where(CallAttempt.created_at < created_to)
    if q:
        like = f"%{escape_like(q.strip())}%"
        stmt = stmt.where(
            or_(Candidate.name.ilike(like, escape="\\"), Candidate.phone.ilike(like, escape="\\"))
        )
    total = int(
        (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    )
    rows = await session.execute(
        stmt.order_by(CallAttempt.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return [(a, name, role) for a, name, role in rows.all()], total


async def latest_for_candidates(
    session: AsyncSession,
    candidate_ids: Sequence[uuid.UUID],
    *,
    include_scheduled: bool = True,
    purpose: CallPurpose | str | None = None,
) -> dict[uuid.UUID, CallAttempt]:
    """Each candidate's newest attempt (highest attempt number), of one purpose or (None) any.
    `include_scheduled=False`: the newest one that isn't only a scheduled retry or callback."""
    if not candidate_ids:
        return {}
    stmt = (
        select(CallAttempt)
        .where(CallAttempt.candidate_id.in_(list(candidate_ids)), _of_purpose(purpose))
        .where(true() if include_scheduled else CallAttempt.call_status.not_in(SCHEDULED_STATUSES))
        .ext(distinct_on(CallAttempt.candidate_id))
        .order_by(CallAttempt.candidate_id, CallAttempt.attempt_number.desc())
    )
    return {a.candidate_id: a for a in (await session.execute(stmt)).scalars()}


async def insert_webhook_event(
    session: AsyncSession,
    *,
    provider: str,
    provider_call_id: str | None,
    event_type: str,
    dedupe_key: str,
    payload: dict[str, Any],
) -> uuid.UUID | None:
    """Insert unless the dedupe key exists. Returns the new id, or None for a duplicate."""
    stmt = (
        insert(WebhookEvent)
        .values(
            provider=provider,
            provider_call_id=provider_call_id,
            event_type=event_type,
            dedupe_key=dedupe_key,
            payload=payload,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
        .returning(WebhookEvent.id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_webhook_event(session: AsyncSession, event_id: uuid.UUID) -> WebhookEvent | None:
    return await session.get(WebhookEvent, event_id)
