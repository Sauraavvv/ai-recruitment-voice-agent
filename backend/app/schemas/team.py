"""Team accounts: the super admin adds and manages the logins of their organization."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database.models.enums import UserRole
from app.schemas.auth import MIN_PASSWORD_LENGTH
from app.utils.candidate_fields import normalize_email


def _strip(value: object) -> object:
    return value.strip() if isinstance(value, str) else value


class TeamMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class TeamMemberCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    email: str = Field(max_length=320)
    # Set by the super admin and shared with the person; never stripped
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)
    role: UserRole = UserRole.RECRUITER

    _name = field_validator("name", mode="before")(_strip)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return normalize_email(value).lower()


class TeamMemberUpdate(BaseModel):
    """Only the fields that are sent change."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=MIN_PASSWORD_LENGTH, max_length=200)

    _name = field_validator("name", mode="before")(_strip)
