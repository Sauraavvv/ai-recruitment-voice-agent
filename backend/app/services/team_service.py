"""Accounts in an organization, managed by its super admins.

Every lookup is limited to the acting super admin's organization: another organization's user
is "not found". A super admin can't deactivate themselves or change their own role, so an
organization always keeps at least one active super admin.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import AppError
from app.database.models import User
from app.repositories import user_repo
from app.schemas.team import TeamMemberCreate, TeamMemberUpdate
from app.services.auth_service import hash_password

EMAIL_TAKEN = "An account with this email already exists"


async def list_members(session: AsyncSession, organization_id: uuid.UUID) -> list[User]:
    stmt = (
        select(User)
        .where(User.organization_id == organization_id)
        .order_by(User.is_active.desc(), User.created_at)
    )
    return list((await session.execute(stmt)).scalars().all())


async def add_member(session: AsyncSession, admin: User, body: TeamMemberCreate) -> User:
    if await user_repo.get_by_email(session, body.email) is not None:
        raise AppError(409, "email_taken", EMAIL_TAKEN)
    member = User(
        organization_id=admin.organization_id,
        email=body.email,
        name=body.name,
        password_hash=hash_password(body.password),
        role=body.role.value,
    )
    session.add(member)
    try:
        await session.commit()
    except IntegrityError:  # added at the same moment elsewhere
        await session.rollback()
        raise AppError(409, "email_taken", EMAIL_TAKEN) from None
    await session.refresh(member)
    return member


async def update_member(
    session: AsyncSession, admin: User, member_id: uuid.UUID, body: TeamMemberUpdate
) -> User:
    member = await user_repo.get(session, member_id)
    if member is None or member.organization_id != admin.organization_id:
        raise AppError(404, "not_found", "Account not found")
    if member.id == admin.id and (
        (body.role is not None and body.role.value != member.role) or body.is_active is False
    ):
        raise AppError(
            409, "cannot_change_self", "You can't change your own role or deactivate yourself"
        )
    if body.name is not None:
        member.name = body.name
    if body.role is not None:
        member.role = body.role.value
    if body.is_active is not None:
        # A deactivated account is refused on its next request (require_user checks is_active)
        member.is_active = body.is_active
    if body.password is not None:
        member.password_hash = hash_password(body.password)
    await session.commit()
    await session.refresh(member)
    return member
