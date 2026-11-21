"""Team accounts (super admins only): list, add, rename, change role, deactivate, set password."""

import uuid
from typing import Any

from fastapi import APIRouter, status

from app.api.deps import AdminUser, SessionDep
from app.api.responses import ok
from app.schemas.common import DataResponse
from app.schemas.team import TeamMemberCreate, TeamMemberOut, TeamMemberUpdate
from app.services import team_service

router = APIRouter(prefix="/team", tags=["team"])


@router.get("", response_model=DataResponse[list[TeamMemberOut]])
async def list_members(admin: AdminUser, session: SessionDep) -> dict[str, Any]:
    members = await team_service.list_members(session, admin.organization_id)
    return ok([TeamMemberOut.model_validate(m) for m in members])


@router.post("", response_model=DataResponse[TeamMemberOut], status_code=status.HTTP_201_CREATED)
async def add_member(
    body: TeamMemberCreate, admin: AdminUser, session: SessionDep
) -> dict[str, Any]:
    """Create a login in the super admin's organization (recruiter by default)."""
    member = await team_service.add_member(session, admin, body)
    return ok(TeamMemberOut.model_validate(member))


@router.patch("/{member_id}", response_model=DataResponse[TeamMemberOut])
async def update_member(
    member_id: uuid.UUID, body: TeamMemberUpdate, admin: AdminUser, session: SessionDep
) -> dict[str, Any]:
    member = await team_service.update_member(session, admin, member_id, body)
    return ok(TeamMemberOut.model_validate(member))
