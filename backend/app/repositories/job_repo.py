import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Job


async def get(session: AsyncSession, job_id: uuid.UUID) -> Job | None:
    return await session.get(Job, job_id)


async def get_active(session: AsyncSession) -> Job | None:
    stmt = select(Job).where(Job.is_active.is_(True))
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_all(session: AsyncSession) -> list[Job]:
    stmt = select(Job).order_by(Job.is_active.desc(), Job.created_at.desc())
    return list((await session.execute(stmt)).scalars())


async def deactivate_all(session: AsyncSession) -> None:
    await session.execute(update(Job).where(Job.is_active.is_(True)).values(is_active=False))
