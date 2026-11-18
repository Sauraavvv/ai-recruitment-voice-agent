"""Call attempt and webhook event queries. No business rules here (see call_service)."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import LIVE_CALL_STATUSES, CallAttempt, WebhookEvent


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


async def live_for_candidate(session: AsyncSession, candidate_id: uuid.UUID) -> CallAttempt | None:
    stmt = select(CallAttempt).where(
        CallAttempt.candidate_id == candidate_id,
        CallAttempt.call_status.in_([s.value for s in LIVE_CALL_STATUSES]),
    )
    return (await session.execute(stmt)).scalars().first()


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
    status: str | None,
    page: int,
    page_size: int,
) -> tuple[list[CallAttempt], int]:
    stmt = select(CallAttempt)
    if candidate_id:
        stmt = stmt.where(CallAttempt.candidate_id == candidate_id)
    if status:
        stmt = stmt.where(CallAttempt.call_status == status)
    total = int(
        (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    )
    rows = await session.execute(
        stmt.order_by(CallAttempt.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    return list(rows.scalars()), total


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
