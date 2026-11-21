import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import (
    Base,
    created_at_column,
    enum_check,
    updated_at_column,
    uuid_pk,
)
from app.database.models.enums import ConsentSource, ScreeningStatus


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        # Job candidates: phone numbers are unique across all jobs (Phase 1 decision), including
        # soft-deleted rows, so re-importing a deleted person is reported as a duplicate rather
        # than re-created. Requirement candidates: unique per requirement (migration 0011).
        Index(
            "uq_candidates_phone",
            "phone",
            unique=True,
            postgresql_where=text("requirement_id IS NULL"),
        ),
        Index(
            "uq_candidates_requirement_id_phone",
            "requirement_id",
            "phone",
            unique=True,
            postgresql_where=text("requirement_id IS NOT NULL"),
        ),
        Index("ix_candidates_job_id", "job_id"),
        Index("ix_candidates_requirement_id", "requirement_id"),
        # A candidate belongs to a job (original flow) or to a requirement, never both
        CheckConstraint("(job_id IS NULL) <> (requirement_id IS NULL)", name="one_parent"),
        Index("ix_candidates_screening_status", "screening_status"),
        enum_check("screening_status", ScreeningStatus, "screening_status"),
        enum_check("consent_source", ConsentSource, "consent_source"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(20))  # E.164
    email: Mapped[str | None] = mapped_column(String(320))
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="RESTRICT")
    )
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="RESTRICT")
    )
    applied_role: Mapped[str] = mapped_column(String(200))
    source: Mapped[str | None] = mapped_column(String(200))
    resume_url: Mapped[str | None] = mapped_column(Text)
    recruiter_notes: Mapped[str | None] = mapped_column(Text)

    # Screening fields (plan.md Module C), filled by calls from Phase 2 onwards.
    current_location: Mapped[str | None] = mapped_column(String(200))
    current_company: Mapped[str | None] = mapped_column(String(200))
    total_experience: Mapped[float | None] = mapped_column(Float)
    relevant_experience: Mapped[float | None] = mapped_column(Float)
    current_ctc: Mapped[float | None] = mapped_column(Float)
    expected_ctc: Mapped[float | None] = mapped_column(Float)
    notice_period: Mapped[str | None] = mapped_column(String(200))
    reason_for_change: Mapped[str | None] = mapped_column(Text)
    interested: Mapped[bool | None] = mapped_column(Boolean)
    interview_availability: Mapped[str | None] = mapped_column(Text)
    screening_field_meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )

    screening_status: Mapped[str] = mapped_column(
        String(32), server_default=ScreeningStatus.NOT_STARTED.value
    )
    opted_out: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    consent_source: Mapped[str | None] = mapped_column(String(64))
    consent_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]

    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
