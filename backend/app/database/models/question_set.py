"""A telephonic round question set for a requirement.

The AI drafts questions from the requirement's JD (or a recruiter writes them); the recruiter
edits and approves. An approved set is frozen: calls record which set (version) they used, so
editing after approval starts a new draft. At most one draft per requirement.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import (
    Base,
    created_at_column,
    enum_check,
    updated_at_column,
    uuid_pk,
)
from app.database.models.enums import QuestionSetStatus


class QuestionSet(Base):
    __tablename__ = "question_sets"
    __table_args__ = (
        enum_check("status", QuestionSetStatus, "status"),
        UniqueConstraint("requirement_id", "version"),
        CheckConstraint("level IS NULL OR level IN ('easy', 'medium', 'hard')", name="level"),
        Index(
            "uq_question_sets_one_draft",
            "requirement_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    requirement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="RESTRICT"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), server_default=QuestionSetStatus.DRAFT.value)
    # "ai" (drafted from the JD) or "manual"; kept when the recruiter edits an AI draft
    source: Mapped[str] = mapped_column(String(16), server_default="manual")
    # [{"id", "text", "type", "rubric", "weight"}], in the order they're asked
    questions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    model: Mapped[str] = mapped_column(String(100), server_default="")  # the AI model, if any
    jd_hash: Mapped[str] = mapped_column(String(64), server_default="")  # JD it was made from
    # easy | medium | hard: how hard the AI was asked to make the questions (None: not known)
    level: Mapped[str | None] = mapped_column(String(8))
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    approved_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
