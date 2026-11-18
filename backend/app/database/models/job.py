import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base, created_at_column, updated_at_column, uuid_pk


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # plan.md Module B: one active job for the MVP.
        Index(
            "uq_jobs_single_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_title: Mapped[str] = mapped_column(String(200))
    company_name: Mapped[str] = mapped_column(String(200))
    job_description: Mapped[str] = mapped_column(Text, server_default="")
    location: Mapped[str] = mapped_column(String(200), server_default="")
    required_experience: Mapped[str] = mapped_column(String(100), server_default="")
    skills: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    screening_questions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    agent_instructions: Mapped[str] = mapped_column(Text, server_default="")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
