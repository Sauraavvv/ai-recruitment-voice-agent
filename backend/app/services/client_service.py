"""Client companies. Everyone in an organization sees all of its clients (a recruiter picks one
when adding a job); only super admins add and edit them."""

import uuid

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import AppError
from app.database.models import Client, User
from app.database.models.enums import ClientStatus
from app.schemas.client import ClientCreate, ClientUpdate

NAME_TAKEN = "Your company already has a client with this name"


def visible(user: User) -> ColumnElement[bool]:
    """The clients this account may see: its organization's."""
    return Client.organization_id == user.organization_id


async def list_clients(
    session: AsyncSession, user: User, *, q: str = "", status: ClientStatus | None = None
) -> list[Client]:
    stmt = select(Client).where(visible(user))
    if q.strip():
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            func.lower(Client.name).like(like)
            | func.lower(Client.city).like(like)
            | func.lower(Client.contact_name).like(like)
        )
    if status is not None:
        stmt = stmt.where(Client.status == status.value)
    stmt = stmt.order_by(Client.status == ClientStatus.CLOSED.value, func.lower(Client.name))
    return list((await session.execute(stmt)).scalars())


async def get_client(session: AsyncSession, user: User, client_id: uuid.UUID) -> Client:
    stmt = select(Client).where(Client.id == client_id, visible(user))
    client = (await session.execute(stmt)).scalar_one_or_none()
    if client is None:
        raise AppError(404, "not_found", "Client not found")
    return client


async def _name_taken(
    session: AsyncSession, user: User, name: str, exclude: uuid.UUID | None = None
) -> bool:
    stmt = select(Client.id).where(
        Client.organization_id == user.organization_id, func.lower(Client.name) == name.lower()
    )
    if exclude is not None:
        stmt = stmt.where(Client.id != exclude)
    return (await session.execute(stmt)).first() is not None


async def _commit(session: AsyncSession) -> None:
    try:
        await session.commit()
    except IntegrityError:  # the same name saved at the same moment
        await session.rollback()
        raise AppError(409, "client_name_taken", NAME_TAKEN) from None


async def create_client(session: AsyncSession, user: User, body: ClientCreate) -> Client:
    if await _name_taken(session, user, body.name):
        raise AppError(409, "client_name_taken", NAME_TAKEN)
    client = Client(
        organization_id=user.organization_id,
        created_by_id=user.id,
        **body.model_dump(exclude={"status"}),
        status=body.status.value,
    )
    session.add(client)
    await _commit(session)
    await session.refresh(client)
    return client


async def update_client(
    session: AsyncSession, user: User, client_id: uuid.UUID, body: ClientUpdate
) -> Client:
    client = await get_client(session, user, client_id)
    # Fields left out, or sent as null, stay as they are
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if "name" in changes and await _name_taken(session, user, changes["name"], exclude=client.id):
        raise AppError(409, "client_name_taken", NAME_TAKEN)
    for field, value in changes.items():
        setattr(client, field, value.value if isinstance(value, ClientStatus) else value)
    await _commit(session)
    await session.refresh(client)
    return client
