"""Candidate queries. No business rules here; those live in candidate_service."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Candidate

SORT_COLUMNS = {
    "created_at": Candidate.created_at,
    "name": Candidate.name,
    "updated_at": Candidate.updated_at,
}


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def get(
    session: AsyncSession, candidate_id: uuid.UUID, *, include_deleted: bool = False
) -> Candidate | None:
    stmt = select(Candidate).where(Candidate.id == candidate_id)
    if not include_deleted:
        stmt = stmt.where(Candidate.deleted_at.is_(None))
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_by_phone(session: AsyncSession, phone: str) -> Candidate | None:
    """Includes soft-deleted candidates: phones stay unique after deletion."""
    stmt = select(Candidate).where(Candidate.phone == phone)
    return (await session.execute(stmt)).scalar_one_or_none()


async def ids_by_phone(session: AsyncSession, phones: Sequence[str]) -> dict[str, str]:
    """Phone -> candidate id for phones that already exist (including soft-deleted)."""
    if not phones:
        return {}
    stmt = select(Candidate.phone, Candidate.id).where(Candidate.phone.in_(set(phones)))
    return {phone: str(cid) for phone, cid in (await session.execute(stmt)).all()}


def _filtered(
    q: str | None,
    screening_status: str | None,
    job_id: uuid.UUID | None,
    interested: bool | None,
) -> Select[Candidate]:
    stmt = select(Candidate).where(Candidate.deleted_at.is_(None))
    if q:
        pattern = f"%{_escape_like(q.strip())}%"
        conditions: list[ColumnElement[bool]] = [
            Candidate.name.ilike(pattern, escape="\\"),
            Candidate.email.ilike(pattern, escape="\\"),
            Candidate.phone.ilike(pattern, escape="\\"),
        ]
        digits = "".join(ch for ch in q if ch.isdigit())
        if len(digits) >= 3:
            conditions.append(Candidate.phone.contains(digits))
        stmt = stmt.where(or_(*conditions))
    if screening_status:
        stmt = stmt.where(Candidate.screening_status == screening_status)
    if job_id:
        stmt = stmt.where(Candidate.job_id == job_id)
    if interested is not None:
        stmt = stmt.where(Candidate.interested.is_(interested))
    return stmt


async def search(
    session: AsyncSession,
    *,
    q: str | None,
    screening_status: str | None,
    job_id: uuid.UUID | None,
    interested: bool | None,
    sort: str,
    page: int,
    page_size: int,
) -> tuple[list[Candidate], int]:
    stmt = _filtered(q, screening_status, job_id, interested)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    descending = sort.startswith("-")
    column = SORT_COLUMNS[sort.lstrip("-")]
    order = column.desc() if descending else column.asc()
    stmt = stmt.order_by(order, Candidate.id).offset((page - 1) * page_size).limit(page_size)
    items = list((await session.execute(stmt)).scalars())
    return items, total


async def insert_ignoring_duplicates(
    session: AsyncSession, rows: list[dict[str, Any]]
) -> list[uuid.UUID]:
    """INSERT ... ON CONFLICT (phone) DO NOTHING; returns the ids actually inserted.

    A concurrent import can't create a duplicate: the unique index decides.
    """
    if not rows:
        return []
    stmt = (
        insert(Candidate)
        .values(rows)
        .on_conflict_do_nothing(index_elements=[Candidate.phone])
        .returning(Candidate.id)
    )
    return list((await session.execute(stmt)).scalars())
