"""Recruiter and admin accounts. Created with `python -m app.scripts.create_user`; no sign-up."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base, created_at_column, enum_check, uuid_pk
from app.database.models.enums import UserRole


class User(Base):
    __tablename__ = "users"
    __table_args__ = (enum_check("role", UserRole, "role"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lowercase
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    # admin: may also change integration settings (the Google Sheet). Default recruiter.
    role: Mapped[str] = mapped_column(String(16), server_default=UserRole.RECRUITER.value)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = created_at_column()
    last_login_at: Mapped[datetime | None]
