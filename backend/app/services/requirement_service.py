"""Requirements (jobs, openings) at a client. A super admin sees and edits every job of the
company; a recruiter only the jobs they created (any recruiter adds jobs for any client of the
company). Another company never sees them."""

import uuid
from typing import Any

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import AppError
from app.database.models import Candidate, Client, Requirement, ScreeningStatus, User
from app.database.models.enums import RequirementStatus, UserRole
from app.repositories import candidate_repo
from app.schemas.requirement import RequirementCreate, RequirementUpdate, check_ranges
from app.services import client_service

# Fields where null in an update means "clear it"
CLEARABLE = frozenset(
    {"experience_min", "experience_max", "ctc_min", "ctc_max", "notice_max_days", "deadline"}
)
# Open first, then on hold, then filled and closed; newest first inside each
_STATUS_ORDER = {
    RequirementStatus.OPEN.value: 0,
    RequirementStatus.ON_HOLD.value: 1,
    RequirementStatus.FILLED.value: 2,
    RequirementStatus.CLOSED.value: 3,
}


def visible(user: User) -> ColumnElement[bool]:
    """The jobs this account may see: a super admin every job of the company, a recruiter only
    the ones they created. Every list and lookup of jobs goes through this (or `can_see`)."""
    own = Requirement.organization_id == user.organization_id
    if user.role == UserRole.SUPER_ADMIN:
        return own
    return and_(own, Requirement.created_by_id == user.id)


def can_see(user: User, requirement: Requirement) -> bool:
    """`visible` for a job already loaded."""
    if requirement.organization_id != user.organization_id:
        return False
    return user.role == UserRole.SUPER_ADMIN or requirement.created_by_id == user.id


async def list_for_client(
    session: AsyncSession, user: User, client_id: uuid.UUID
) -> list[Requirement]:
    await client_service.get_client(session, user, client_id)  # 404 unless visible
    stmt = select(Requirement).where(Requirement.client_id == client_id, visible(user))
    rows = list((await session.execute(stmt)).scalars())
    rows.sort(key=lambda r: (_STATUS_ORDER.get(r.status, 9), -r.created_at.timestamp()))
    return rows


async def open_counts(
    session: AsyncSession, user: User, client_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    """Per client: its open jobs that `user` sees."""
    if not client_ids:
        return {}
    stmt = (
        select(Requirement.client_id, func.count())
        .where(
            Requirement.client_id.in_(client_ids),
            Requirement.status == RequirementStatus.OPEN.value,
            visible(user),
        )
        .group_by(Requirement.client_id)
    )
    return {client_id: count for client_id, count in (await session.execute(stmt)).all()}


async def get_requirement(
    session: AsyncSession, user: User, requirement_id: uuid.UUID
) -> tuple[Requirement, Client]:
    requirement = await session.get(Requirement, requirement_id)
    if requirement is None or not can_see(user, requirement):
        raise AppError(404, "not_found", "Requirement not found")
    try:
        client = await client_service.get_client(session, user, requirement.client_id)
    except AppError:
        raise AppError(404, "not_found", "Requirement not found") from None
    return requirement, client


async def create_requirement(
    session: AsyncSession, user: User, client_id: uuid.UUID, body: RequirementCreate
) -> Requirement:
    client = await client_service.get_client(session, user, client_id)
    values: dict[str, Any] = body.model_dump()
    values["status"] = body.status.value
    requirement = Requirement(
        organization_id=client.organization_id,
        client_id=client.id,
        created_by_id=user.id,
        **values,
    )
    session.add(requirement)
    await session.commit()
    await session.refresh(requirement)
    return requirement


async def update_requirement(
    session: AsyncSession, user: User, requirement_id: uuid.UUID, body: RequirementUpdate
) -> Requirement:
    requirement, _client = await get_requirement(session, user, requirement_id)
    changes = {
        k: v
        for k, v in body.model_dump(exclude_unset=True).items()
        if v is not None or k in CLEARABLE
    }
    merged = {
        field: changes.get(field, getattr(requirement, field))
        for field in ("experience_min", "experience_max", "ctc_min", "ctc_max")
    }
    try:
        check_ranges({k: float(v) if v is not None else None for k, v in merged.items()})
    except ValueError as exc:
        raise AppError(422, "invalid_range", str(exc)) from None
    for field, value in changes.items():
        setattr(requirement, field, value.value if isinstance(value, RequirementStatus) else value)
    await session.commit()
    await session.refresh(requirement)
    return requirement


async def candidate_counts(
    session: AsyncSession, user: User, requirement_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int, int]]:
    """Per requirement: (candidates, called, interested), not counting deleted candidates,
    over the candidates `user` sees (a recruiter: their own uploads)."""
    if not requirement_ids:
        return {}
    stmt = (
        select(
            Candidate.requirement_id,
            func.count(),
            func.count().filter(Candidate.screening_status != ScreeningStatus.NOT_STARTED.value),
            func.count().filter(Candidate.interested.is_(True)),
        )
        .where(
            Candidate.requirement_id.in_(requirement_ids),
            Candidate.deleted_at.is_(None),
            candidate_repo.visible_to(user),
        )
        .group_by(Candidate.requirement_id)
    )
    return {
        rid: (total, called, interested)
        for rid, total, called, interested in (await session.execute(stmt)).all()
        if rid is not None
    }


async def list_all(session: AsyncSession, user: User) -> list[tuple[Requirement, Client]]:
    """Every job this account sees, with its client (open first, newest first)."""
    stmt = (
        select(Requirement, Client)
        .join(Client, Client.id == Requirement.client_id)
        .where(client_service.visible(user), visible(user))
    )
    rows = [(r, c) for r, c in (await session.execute(stmt)).all()]
    rows.sort(key=lambda rc: (_STATUS_ORDER.get(rc[0].status, 9), -rc[0].created_at.timestamp()))
    return rows
