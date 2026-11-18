"""Recruiter accounts. Created with `python -m app.scripts.create_user`; no public sign-up."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base, created_at_column, uuid_pk


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True)  # stored lowercase
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = created_at_column()
    last_login_at: Mapped[datetime | None]
