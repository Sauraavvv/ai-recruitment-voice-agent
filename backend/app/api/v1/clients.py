"""Client companies: list, add, view, edit. Everyone in an organization sees its clients
(recruiters pick one when adding a job); only super admins add and edit them."""

import uuid
from typing import Any

from fastapi import APIRouter, status

from app.api.deps import AdminUser, CurrentUser, SessionDep
from app.api.responses import ok
from app.database.models.enums import ClientStatus
from app.schemas.client import ClientCreate, ClientListItem, ClientOut, ClientUpdate
from app.schemas.common import DataResponse
from app.services import client_service, requirement_service

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=DataResponse[list[ClientListItem]])
async def list_clients(
    user: CurrentUser, session: SessionDep, q: str = "", status: ClientStatus | None = None
) -> dict[str, Any]:
    """Search matches the name, city or contact person. Closed clients come last."""
    clients = await client_service.list_clients(session, user, q=q, status=status)
    counts = await requirement_service.open_counts(session, user, [c.id for c in clients])
    return ok(
        [
            ClientListItem.model_validate(c).model_copy(
                update={"open_requirements": counts.get(c.id, 0)}
            )
            for c in clients
        ]
    )


@router.post("", response_model=DataResponse[ClientOut], status_code=status.HTTP_201_CREATED)
async def create_client(body: ClientCreate, user: AdminUser, session: SessionDep) -> dict[str, Any]:
    return ok(ClientOut.model_validate(await client_service.create_client(session, user, body)))


@router.get("/{client_id}", response_model=DataResponse[ClientOut])
async def get_client(
    client_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    return ok(ClientOut.model_validate(await client_service.get_client(session, user, client_id)))


@router.patch("/{client_id}", response_model=DataResponse[ClientOut])
async def update_client(
    client_id: uuid.UUID, body: ClientUpdate, user: AdminUser, session: SessionDep
) -> dict[str, Any]:
    client = await client_service.update_client(session, user, client_id, body)
    return ok(ClientOut.model_validate(client))
