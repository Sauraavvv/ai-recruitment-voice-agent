"""A requirement (opening) at a client, e.g. "Sales Executive, Pune, 10 openings".

Belongs to a client; visible to whoever can see the client. Screening lists and the telephonic
round (JD-based questions) attach to a requirement in later steps.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import (
    Base,
    created_at_column,
    enum_check,
    updated_at_column,
    uuid_pk,
)
from app.database.models.enums import RequirementStatus

if TYPE_CHECKING:
    from app.database.models.user import User


class Requirement(Base):
    __tablename__ = "requirements"
    __table_args__ = (
        enum_check("status", RequirementStatus, "status"),
        CheckConstraint("work_mode IN ('', 'onsite', 'hybrid', 'remote')", name="work_mode"),
        CheckConstraint("openings >= 1", name="openings_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="RESTRICT"), index=True
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    # Who added it (a super admin or a recruiter), shown on the job; loaded with it
    created_by: Mapped["User"] = relationship(lazy="joined")
    title: Mapped[str] = mapped_column(String(200))  # the role
    location: Mapped[str] = mapped_column(String(200), server_default="")
    work_mode: Mapped[str] = mapped_column(String(16), server_default="")  # "" = not said
    openings: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    experience_min: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))  # years
    experience_max: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    ctc_min: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))  # LPA
    ctc_max: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    notice_max_days: Mapped[int | None] = mapped_column(Integer)
    skills: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    # Things a candidate must have; the screening call checks each one (later step)
    must_haves: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    job_description: Mapped[str] = mapped_column(Text, server_default="")  # needed for telephonic
    deadline: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str] = mapped_column(Text, server_default="")
    status: Mapped[str] = mapped_column(String(16), server_default=RequirementStatus.OPEN.value)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    @property
    def created_by_name(self) -> str:
        return self.created_by.name
