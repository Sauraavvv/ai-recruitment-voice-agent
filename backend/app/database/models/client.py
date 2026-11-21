"""A client company the HR firm hires for (e.g. "Easy Recruitz 365").

Added and edited by the organization's super admins, who all see the organization's clients.
Recruiters don't see clients yet (assigning clients to recruiters comes later). Requirements,
screening lists and the telephonic round hang off a client.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.models.base import (
    Base,
    created_at_column,
    enum_check,
    updated_at_column,
    uuid_pk,
)
from app.database.models.enums import ClientStatus


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (
        enum_check("status", ClientStatus, "status"),
        # One client name per organization, ignoring case
        Index(
            "uq_clients_organization_id_name", "organization_id", text("lower(name)"), unique=True
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str] = mapped_column(String(100), server_default="")
    website: Mapped[str] = mapped_column(String(300), server_default="")
    email: Mapped[str] = mapped_column(String(320), server_default="")  # the company's email
    address: Mapped[str] = mapped_column(String(500), server_default="")
    city: Mapped[str] = mapped_column(String(100), server_default="")
    state: Mapped[str] = mapped_column(String(100), server_default="")
    contact_name: Mapped[str] = mapped_column(String(200), server_default="")
    contact_designation: Mapped[str] = mapped_column(String(200), server_default="")
    contact_phone: Mapped[str] = mapped_column(String(32), server_default="")  # E.164 or ""
    # Confidential: the agent never says the client's name on a call
    is_confidential: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    notes: Mapped[str] = mapped_column(Text, server_default="")
    status: Mapped[str] = mapped_column(String(16), server_default=ClientStatus.ACTIVE.value)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
