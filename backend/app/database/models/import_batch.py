"""Stored upload previews backing the preview -> confirm import flow."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base, created_at_column, enum_check, uuid_pk
from app.database.models.enums import ImportBatchStatus


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        Index("ix_import_batches_status_created_at", "status", "created_at"),
        enum_check("status", ImportBatchStatus, "status"),
        Index("ix_import_batches_requirement_id", "requirement_id"),
        CheckConstraint("(job_id IS NULL) <> (requirement_id IS NULL)", name="one_parent"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    # The upload is for a job (original flow) or for a requirement
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="RESTRICT")
    )
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="RESTRICT")
    )
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), server_default=ImportBatchStatus.PREVIEW.value)
    headers: Mapped[list[str]] = mapped_column(JSONB)
    column_mapping: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # [{"row": <spreadsheet row number>, "cells": [str, ...]}]; cleared on confirm or expiry.
    rows: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()
    confirmed_at: Mapped[datetime | None]
