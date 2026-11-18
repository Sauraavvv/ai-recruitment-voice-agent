"""Call attempts (plan.md Module F). Telephony status lives here; screening status stays on the
candidate. Transitions go through app.services.call_state only."""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import (
    Base,
    created_at_column,
    enum_check,
    updated_at_column,
    uuid_pk,
)
from app.database.models.enums import (
    LIVE_CALL_STATUSES,
    CallAttemptType,
    CallEndReason,
    CallStatus,
)

_LIVE = ", ".join(f"'{s.value}'" for s in LIVE_CALL_STATUSES)


class CallAttempt(Base):
    __tablename__ = "call_attempts"
    __table_args__ = (
        Index("ix_call_attempts_candidate_id", "candidate_id"),
        Index("ix_call_attempts_call_status", "call_status"),
        Index("ix_call_attempts_next_retry_at", "next_retry_at"),
        Index(
            "uq_call_attempts_provider_call",
            "provider",
            "provider_call_id",
            unique=True,
            postgresql_where=text("provider_call_id IS NOT NULL"),
        ),
        # At most one live or scheduled attempt per candidate: no duplicate simultaneous calls.
        Index(
            "uq_call_attempts_one_live",
            "candidate_id",
            unique=True,
            postgresql_where=text(f"call_status IN ({_LIVE})"),
        ),
        UniqueConstraint("candidate_id", "attempt_number", name="uq_call_attempts_number"),
        enum_check("call_status", CallStatus, "call_status"),
        enum_check("attempt_type", CallAttemptType, "attempt_type"),
        enum_check("end_reason", CallEndReason, "end_reason"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("candidates.id", ondelete="RESTRICT")
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    attempt_type: Mapped[str] = mapped_column(
        String(16), server_default=CallAttemptType.INITIAL.value
    )
    provider: Mapped[str] = mapped_column(String(50))
    provider_call_id: Mapped[str | None] = mapped_column(String(200))
    provider_status: Mapped[str | None] = mapped_column(String(50))
    stream_id: Mapped[str | None] = mapped_column(String(200))
    call_status: Mapped[str] = mapped_column(String(32), server_default=CallStatus.PENDING.value)
    end_reason: Mapped[str | None] = mapped_column(String(32))
    start_time: Mapped[datetime | None]
    end_time: Mapped[datetime | None]
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    recording_url: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    next_retry_at: Mapped[datetime | None]
    retry_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
