import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database.models.enums import UserRole
from app.utils.candidate_fields import normalize_email


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=320)
    password: str = Field(max_length=200)


MIN_PASSWORD_LENGTH = 10


class SignupRequest(BaseModel):
    """A new organization and its super admin."""

    model_config = ConfigDict(extra="forbid")

    organization_name: str = Field(min_length=2, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(max_length=320)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)

    @field_validator("organization_name", "name", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        # The password is never stripped: spaces in it are the user's choice
        return value.strip() if isinstance(value, str) else value

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return normalize_email(value).lower()


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str
    role: UserRole
    organization: OrganizationOut
