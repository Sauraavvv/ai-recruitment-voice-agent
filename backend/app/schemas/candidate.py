import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from app.database.models.enums import ScreeningStatus
from app.utils import candidate_fields as rules
from app.utils.phone import PHONE_ERROR_MESSAGES, normalize_phone


def _phone(value: str) -> str:
    result = normalize_phone(value)
    if result.e164 is None:
        raise ValueError(PHONE_ERROR_MESSAGES[result.error or "phone_invalid"])
    return result.e164


def _optional(validator: Any) -> Any:
    def run(value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        result: str = validator(value)
        return result

    return run


Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=rules.MAX_NAME_LENGTH)
]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=rules.MAX_TEXT_LENGTH)]
Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=rules.MAX_NOTES_LENGTH)]
Phone = Annotated[str, StringConstraints(max_length=40), AfterValidator(_phone)]
Email = Annotated[str | None, AfterValidator(_optional(rules.normalize_email))]
Url = Annotated[
    str | None, StringConstraints(max_length=2000), AfterValidator(_optional(rules.check_http_url))
]
Experience = Annotated[float, Field(ge=0, le=rules.MAX_EXPERIENCE_YEARS)]
Money = Annotated[float, Field(ge=0, le=10_000)]  # LPA


class CandidateCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    phone: Phone
    applied_role: Name
    job_id: uuid.UUID | None = Field(
        default=None, description="Defaults to the active job when omitted"
    )
    email: Email = None
    source: Text | None = None
    resume_url: Url = None
    recruiter_notes: Notes | None = None
    total_experience: Experience | None = None
    current_company: Text | None = None
    current_location: Text | None = None
    consent_attested: bool = Field(
        description="The candidate agreed to be contacted by phone about this role"
    )


class CandidateUpdate(BaseModel):
    """Partial update. Fields left out are unchanged; send null to clear an optional field."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    phone: Phone | None = None
    applied_role: Name | None = None
    job_id: uuid.UUID | None = None
    email: Email = None
    source: Text | None = None
    resume_url: Url = None
    recruiter_notes: Notes | None = None
    current_location: Text | None = None
    current_company: Text | None = None
    total_experience: Experience | None = None
    relevant_experience: Experience | None = None
    current_ctc: Money | None = None
    expected_ctc: Money | None = None
    notice_period: Text | None = None
    reason_for_change: Notes | None = None
    interested: bool | None = None
    interview_availability: Notes | None = None
    opted_out: bool | None = None

    @field_validator("name", "phone", "applied_role", "job_id", "opted_out")
    @classmethod
    def _not_null(cls, value: Any) -> Any:
        # Required columns can be changed but not cleared. (Runs only when the field is sent.)
        if value is None:
            raise ValueError("cannot be null")
        return value


class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    phone: str
    email: str | None
    job_id: uuid.UUID
    applied_role: str
    source: str | None
    resume_url: str | None
    recruiter_notes: str | None

    current_location: str | None
    current_company: str | None
    total_experience: float | None
    relevant_experience: float | None
    current_ctc: float | None
    expected_ctc: float | None
    notice_period: str | None
    reason_for_change: str | None
    interested: bool | None
    interview_availability: str | None
    screening_field_meta: dict[str, Any]

    screening_status: ScreeningStatus
    opted_out: bool
    consent_source: str | None
    consent_at: datetime | None
    created_at: datetime
    updated_at: datetime


CandidateSort = Literal["created_at", "-created_at", "name", "-name", "updated_at", "-updated_at"]
