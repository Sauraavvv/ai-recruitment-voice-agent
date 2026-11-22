"""Accounts. A super admin signs up with their organization (POST /auth/signup); other accounts
are created with `python -m app.scripts.create_user` (user management in the UI comes later)."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.models.base import Base, created_at_column, enum_check, uuid_pk
from app.database.models.enums import UserRole
from app.database.models.organization import Organization


class User(Base):
    __tablename__ = "users"
    __table_args__ = (enum_check("role", UserRole, "role"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    # Loaded with the user (every request reads it through /auth/me and the session check)
    organization: Mapped[Organization] = relationship(lazy="joined")
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lowercase
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    # super_admin: owns the organization (its clients and team). Default recruiter.
    role: Mapped[str] = mapped_column(String(16), server_default=UserRole.RECRUITER.value)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = created_at_column()
    last_login_at: Mapped[datetime | None]
