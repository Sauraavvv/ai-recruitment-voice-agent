"""Client companies (the companies the HR firm hires for)."""

import uuid
from datetime import datetime
from typing import Literal, get_args
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database.models.enums import ClientStatus
from app.utils.candidate_fields import normalize_email
from app.utils.phone import PHONE_ERROR_MESSAGES, normalize_phone

Industry = Literal[
    "IT & Software",
    "BPO / KPO",
    "Banking & Finance",
    "Healthcare",
    "Education",
    "Manufacturing",
    "Retail & E-commerce",
    "Hospitality",
    "Other",
]

# The 28 states and 8 union territories of India
State = Literal[
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chhattisgarh",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
    "Andaman and Nicobar Islands",
    "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi",
    "Jammu and Kashmir",
    "Ladakh",
    "Lakshadweep",
    "Puducherry",
]
INDUSTRIES: tuple[str, ...] = get_args(Industry)
STATES: tuple[str, ...] = get_args(State)


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    industry: str
    website: str
    email: str
    address: str
    city: str
    state: str
    contact_name: str
    contact_designation: str
    contact_phone: str
    is_confidential: bool
    notes: str
    status: ClientStatus
    created_at: datetime
    updated_at: datetime


class ClientListItem(ClientOut):
    open_requirements: int = 0


TEXT_FIELDS = (
    "name",
    "website",
    "email",
    "address",
    "city",
    "contact_name",
    "contact_designation",
    "contact_phone",
    "notes",
)


class _ClientFields(BaseModel):
    """Shared validation. Empty optional fields are stored as ""."""

    model_config = ConfigDict(extra="forbid")

    @field_validator(*TEXT_FIELDS, mode="before", check_fields=False)
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("contact_phone", check_fields=False)
    @classmethod
    def _phone(cls, value: str | None) -> str | None:
        if not value:
            return value
        result = normalize_phone(value)
        if result.e164 is None:
            raise ValueError(
                PHONE_ERROR_MESSAGES.get(result.error or "", "Phone number is not valid")
            )
        return result.e164

    @field_validator("email", check_fields=False)
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return normalize_email(value).lower() if value else value

    @field_validator("website", check_fields=False)
    @classmethod
    def _website(cls, value: str | None) -> str | None:
        if not value:
            return value
        url = value if "://" in value else f"https://{value}"
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or "." not in parsed.netloc:
            raise ValueError("Website must look like example.com or https://example.com")
        return url


class ClientCreate(_ClientFields):
    name: str = Field(min_length=1, max_length=200)
    industry: Industry
    website: str = Field(default="", max_length=300)
    email: str = Field(min_length=3, max_length=320)
    address: str = Field(default="", max_length=500)
    city: str = Field(min_length=1, max_length=100)
    state: State
    contact_name: str = Field(min_length=1, max_length=200)
    contact_designation: str = Field(default="", max_length=200)
    contact_phone: str = Field(min_length=1, max_length=32)
    is_confidential: bool = False
    notes: str = Field(default="", max_length=5000)
    status: ClientStatus = ClientStatus.ACTIVE


class ClientUpdate(_ClientFields):
    """Only the fields that are sent change; required fields can't be emptied."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    industry: Industry | None = None
    website: str | None = Field(default=None, max_length=300)
    email: str | None = Field(default=None, min_length=3, max_length=320)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    state: State | None = None
    contact_name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_designation: str | None = Field(default=None, max_length=200)
    contact_phone: str | None = Field(default=None, min_length=1, max_length=32)
    is_confidential: bool | None = None
    notes: str | None = Field(default=None, max_length=5000)
    status: ClientStatus | None = None
