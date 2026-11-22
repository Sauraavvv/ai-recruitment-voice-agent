"""Requirements (openings) at a client."""

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.database.models.enums import RequirementStatus

MAX_JD = 20_000
MAX_SKILLS = 30
MAX_MUST_HAVES = 15

WorkModeIn = Literal["", "onsite", "hybrid", "remote"]
Years = Annotated[float, Field(ge=0, le=50)]
Lpa = Annotated[float, Field(ge=0, le=1000)]
NoticeDays = Annotated[int, Field(ge=0, le=365)]


def _clean_list(values: list[str], *, limit: int, item_max: int, what: str) -> list[str]:
    """Strip, drop empties and case-insensitive duplicates, keep the order."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        item = " ".join(str(raw).split())
        if not item or item.lower() in seen:
            continue
        if len(item) > item_max:
            raise ValueError(f"Each {what} can be at most {item_max} characters")
        seen.add(item.lower())
        out.append(item)
    if len(out) > limit:
        raise ValueError(f"At most {limit} {what}s")
    return out


def check_ranges(values: dict[str, object]) -> None:
    for low, high, what in (
        ("experience_min", "experience_max", "experience"),
        ("ctc_min", "ctc_max", "CTC"),
    ):
        lo, hi = values.get(low), values.get(high)
        if isinstance(lo, int | float) and isinstance(hi, int | float) and lo > hi:
            raise ValueError(f"Minimum {what} can't be more than the maximum")


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    client_id: uuid.UUID
    title: str
    location: str
    work_mode: WorkModeIn
    openings: int
    experience_min: float | None
    experience_max: float | None
    ctc_min: float | None
    ctc_max: float | None
    notice_max_days: int | None
    skills: list[str]
    must_haves: list[str]
    job_description: str
    deadline: date | None
    notes: str
    status: RequirementStatus
    created_by_name: str  # who added it: a super admin or a recruiter of the company
    created_at: datetime
    updated_at: datetime


class RequirementListItem(RequirementOut):
    """A row in a client's requirements list, with its screening numbers."""

    candidates: int = 0  # on the list (not deleted)
    called: int = 0  # screening started (any outcome)
    interested: int = 0  # said yes on the screening call


class JobListItem(RequirementListItem):
    """A requirement in the list of all jobs, with its client."""

    client_name: str = ""
    client_status: str = ""


class _RequirementFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator(
        "title", "location", "job_description", "notes", mode="before", check_fields=False
    )
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("skills", check_fields=False)
    @classmethod
    def _skills(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _clean_list(value, limit=MAX_SKILLS, item_max=60, what="skill")

    @field_validator("must_haves", check_fields=False)
    @classmethod
    def _must_haves(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _clean_list(value, limit=MAX_MUST_HAVES, item_max=200, what="must-have")

    @model_validator(mode="after")
    def _ranges(self) -> "_RequirementFields":
        check_ranges(self.model_dump())
        return self


class RequirementCreate(_RequirementFields):
    title: str = Field(min_length=1, max_length=200)
    location: str = Field(default="", max_length=200)
    work_mode: WorkModeIn = ""
    openings: int = Field(default=1, ge=1, le=1000)
    experience_min: Years | None = None
    experience_max: Years | None = None
    ctc_min: Lpa | None = None
    ctc_max: Lpa | None = None
    notice_max_days: NoticeDays | None = None
    skills: list[str] = Field(default_factory=list)
    must_haves: list[str] = Field(default_factory=list)
    job_description: str = Field(default="", max_length=MAX_JD)
    deadline: date | None = None
    notes: str = Field(default="", max_length=5000)
    status: RequirementStatus = RequirementStatus.OPEN


class RequirementUpdate(_RequirementFields):
    """Only the fields that are sent change. null clears the optional numbers and the
    deadline; for the other fields null means "leave as it is"."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    work_mode: WorkModeIn | None = None
    openings: int | None = Field(default=None, ge=1, le=1000)
    experience_min: Years | None = None
    experience_max: Years | None = None
    ctc_min: Lpa | None = None
    ctc_max: Lpa | None = None
    notice_max_days: NoticeDays | None = None
    skills: list[str] | None = None
    must_haves: list[str] | None = None
    job_description: str | None = Field(default=None, max_length=MAX_JD)
    deadline: date | None = None
    notes: str | None = Field(default=None, max_length=5000)
    status: RequirementStatus | None = None


class ScreeningCallQuestion(BaseModel):
    """One question a requirement's screening call asks, in order (phase-11 step 5)."""

    number: int
    key: str
    prompt: str  # what the agent is told to ask
    type: str
    source: Literal["default", "must_have"]
    must_have: str | None = None  # the must-have as the recruiter wrote it
