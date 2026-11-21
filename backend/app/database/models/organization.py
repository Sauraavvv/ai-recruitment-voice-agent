"""A company (HR firm) using HireCall. Created by sign-up together with its super admin.

Only users belong to an organization so far; candidates, jobs, calls and settings are still
shared until the data-isolation work lands (see `Settings.signup_enabled`).
"""

import uuid
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import Base, created_at_column, uuid_pk


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at_column()
