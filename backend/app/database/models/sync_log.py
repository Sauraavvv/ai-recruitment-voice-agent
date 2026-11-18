"""Google Sheets sync log / outbox. Only the table exists in Phase 1; used from Phase 7."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base, created_at_column, enum_check, uuid_pk
from app.database.models.enums import SyncStatus


class SyncLog(Base):
    __tablename__ = "sync_logs"
    __table_args__ = (
        Index("ix_sync_logs_candidate_id_created_at", "candidate_id", "created_at"),
        enum_check("sync_status", SyncStatus, "sync_status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="RESTRICT")
    )
    provider: Mapped[str] = mapped_column(String(50))
    sync_status: Mapped[str] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text)
    synced_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at_column()
