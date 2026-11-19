"""Google Sheets outbox (phase-07 P7-T9).

A row is written in the same transaction as every candidate change. It goes from `pending` to
`success` (with `synced_at`) or `failed` (with `error_message`, `attempts` and, while another try
is due, `next_attempt_at`). Several rows for one candidate are satisfied by one sync of the
latest state.
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import (
    Base,
    created_at_column,
    enum_check,
    updated_at_column,
    uuid_pk,
)
from app.database.models.enums import SyncStatus


class SyncLog(Base):
    __tablename__ = "sync_logs"
    __table_args__ = (
        Index("ix_sync_logs_candidate_id_created_at", "candidate_id", "created_at"),
        Index("ix_sync_logs_sync_status_next_attempt_at", "sync_status", "next_attempt_at"),
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
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    next_attempt_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
