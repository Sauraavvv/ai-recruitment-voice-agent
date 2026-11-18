"""Raw provider webhooks: idempotent processing and an audit trail (phase-05 §5)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base, uuid_pk


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        Index("uq_webhook_events_dedupe_key", "dedupe_key", unique=True),
        Index("ix_webhook_events_provider_call_id", "provider_call_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(String(50))
    provider_call_id: Mapped[str | None] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(50))
    dedupe_key: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    processed_at: Mapped[datetime | None]
    error: Mapped[str | None] = mapped_column(Text)
