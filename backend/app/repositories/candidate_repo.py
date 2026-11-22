"""Candidate queries. No business rules here; those live in candidate_service."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CallAttempt, CallPurpose, Candidate, Requirement, User
from app.database.models.enums import UserRole

SORT_COLUMNS = {
    "created_at": Candidate.created_at,
    "name": Candidate.name,
    "updated_at": Candidate.updated_at,
}


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def get(
    session: AsyncSession, candidate_id: uuid.UUID, *, include_deleted: bool = False
) -> Candidate | None:
    stmt = select(Candidate).where(Candidate.id == candidate_id)
    if not include_deleted:
        stmt = stmt.where(Candidate.deleted_at.is_(None))
    return (await session.execute(stmt)).scalar_one_or_none()


def visible_to(user: User) -> ColumnElement[bool]:
    """The candidates this account may see. A super admin: every candidate of the company,
    whoever uploaded them. A recruiter: only the ones they uploaded. Never another company's.
    Every list, count and lookup of candidates (and of their calls) goes through this."""
    own = Candidate.organization_id == user.organization_id
    if user.role == UserRole.SUPER_ADMIN:
        return own
    return and_(own, Candidate.uploaded_by_id == user.id)


def can_see(user: User, candidate: Candidate) -> bool:
    """`visible_to` for a candidate already loaded."""
    if candidate.organization_id != user.organization_id:
        return False
    return user.role == UserRole.SUPER_ADMIN or candidate.uploaded_by_id == user.id


def _phone_scope(
    requirement_id: uuid.UUID | None, organization_id: uuid.UUID
) -> ColumnElement[bool]:
    """Job candidates share one phone space per organization; each requirement has its own."""
    if requirement_id is None:
        return and_(
            Candidate.requirement_id.is_(None), Candidate.organization_id == organization_id
        )
    return Candidate.requirement_id == requirement_id


async def get_by_phone(
    session: AsyncSession,
    phone: str,
    *,
    organization_id: uuid.UUID,
    requirement_id: uuid.UUID | None = None,
) -> Candidate | None:
    """Includes soft-deleted candidates: phones stay unique after deletion."""
    stmt = select(Candidate).where(
        Candidate.phone == phone, _phone_scope(requirement_id, organization_id)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def ids_by_phone(
    session: AsyncSession,
    phones: Sequence[str],
    *,
    organization_id: uuid.UUID,
    requirement_id: uuid.UUID | None = None,
) -> dict[str, str]:
    """Phone -> candidate id for phones that already exist (including soft-deleted)."""
    if not phones:
        return {}
    stmt = select(Candidate.phone, Candidate.id).where(
        Candidate.phone.in_(set(phones)), _phone_scope(requirement_id, organization_id)
    )
    return {phone: str(cid) for phone, cid in (await session.execute(stmt)).all()}


NOT_CALLED = "not_called"  # call_status filter: no attempt yet


def _screening_call() -> Any:
    return CallAttempt.purpose == CallPurpose.SCREENING.value


def latest_call_status() -> Any:
    """The candidate's newest screening call's status (correlated scalar subquery). The
    candidate list is about screening calls; telephonic round calls don't count here."""
    return (
        select(CallAttempt.call_status)
        .where(CallAttempt.candidate_id == Candidate.id, _screening_call())
        .order_by(CallAttempt.attempt_number.desc())
        .limit(1)
        .scalar_subquery()
    )


def _filtered(
    q: str | None,
    screening_status: str | None,
    job_id: uuid.UUID | None,
    interested: bool | None,
    call_status: str | None = None,
    requirement_id: uuid.UUID | None = None,
    viewer: User | None = None,
    client_id: uuid.UUID | None = None,
) -> Select[Candidate]:
    stmt = select(Candidate).where(Candidate.deleted_at.is_(None))
    if viewer is not None:
        stmt = stmt.where(visible_to(viewer))
    if requirement_id:
        stmt = stmt.where(Candidate.requirement_id == requirement_id)
    if client_id:
        of_client = select(Requirement.id).where(Requirement.client_id == client_id)
        stmt = stmt.where(Candidate.requirement_id.in_(of_client))
    if q:
        pattern = f"%{escape_like(q.strip())}%"
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
    if call_status == NOT_CALLED:
        stmt = stmt.where(
            ~select(CallAttempt.id)
            .where(CallAttempt.candidate_id == Candidate.id, _screening_call())
            .exists()
        )
    elif call_status:
        stmt = stmt.where(latest_call_status() == call_status)
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
    call_status: str | None = None,
    requirement_id: uuid.UUID | None = None,
    viewer: User | None = None,
    client_id: uuid.UUID | None = None,
) -> tuple[list[Candidate], int]:
    stmt = _filtered(
        q, screening_status, job_id, interested, call_status, requirement_id, viewer, client_id
    )
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()

    descending = sort.startswith("-")
    column = SORT_COLUMNS[sort.lstrip("-")]
    order = column.desc() if descending else column.asc()
    stmt = stmt.order_by(order, Candidate.id).offset((page - 1) * page_size).limit(page_size)
    items = list((await session.execute(stmt)).scalars())
    return items, total


async def insert_ignoring_duplicates(
    session: AsyncSession, rows: list[dict[str, Any]], requirement_id: uuid.UUID | None = None
) -> list[uuid.UUID]:
    """INSERT ... ON CONFLICT DO NOTHING on the phone index of the scope (job candidates, or
    this requirement); returns the ids actually inserted.

    A concurrent import can't create a duplicate: the unique index decides.
    """
    if not rows:
        return []
    if requirement_id is None:
        conflict = insert(Candidate).on_conflict_do_nothing(
            index_elements=[Candidate.organization_id, Candidate.phone],
            index_where=Candidate.requirement_id.is_(None),
        )
    else:
        conflict = insert(Candidate).on_conflict_do_nothing(
            index_elements=[Candidate.requirement_id, Candidate.phone],
            index_where=Candidate.requirement_id.is_not(None),
        )
    stmt = conflict.values(rows).returning(Candidate.id)
    return list((await session.execute(stmt)).scalars())
