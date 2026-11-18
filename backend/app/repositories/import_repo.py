import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ImportBatch, ImportBatchStatus


async def get(
    session: AsyncSession, import_id: uuid.UUID, *, for_update: bool = False
) -> ImportBatch | None:
    stmt = select(ImportBatch).where(ImportBatch.id == import_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def expire_previews(session: AsyncSession, created_before: datetime) -> int:
    """Mark old previews expired and drop their stored rows (candidate PII)."""
    stmt = (
        update(ImportBatch)
        .where(
            ImportBatch.status == ImportBatchStatus.PREVIEW,
            ImportBatch.created_at < created_before,
        )
        .values(status=ImportBatchStatus.EXPIRED, rows=None)
        .returning(ImportBatch.id)
    )
    return len((await session.execute(stmt)).all())
