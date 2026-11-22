"""Telephonic round: the questions asked on the second call, made from the requirement's JD."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database.models.enums import QuestionSetStatus

QuestionType = Literal["experience", "skill", "situational", "logistics"]
QUESTION_TYPES: tuple[str, ...] = ("experience", "skill", "situational", "logistics")
MAX_QUESTIONS = 15


def _clean(value: object) -> object:
    return " ".join(value.split()) if isinstance(value, str) else value


class Question(BaseModel):
    """One question as stored and shown: what's asked, what a good answer covers, how much it
    counts (1 nice to have … 3 critical)."""

    id: str
    text: str
    type: QuestionType
    rubric: str
    weight: int = Field(ge=1, le=3)


class QuestionIn(BaseModel):
    """A question as the recruiter saves it. A new question has no id yet."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, max_length=40)
    text: str = Field(min_length=5, max_length=400)
    type: QuestionType = "skill"
    rubric: str = Field(default="", max_length=800)
    weight: int = Field(default=2, ge=1, le=3)

    _strip = field_validator("text", "rubric", mode="before")(_clean)


class DraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[QuestionIn] = Field(min_length=1, max_length=MAX_QUESTIONS)


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int = Field(default=8, ge=4, le=12)
    # Extra guidance from the recruiter, e.g. "focus on B2B sales"
    focus: str = Field(default="", max_length=300)


class QuestionSetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    status: QuestionSetStatus
    source: str
    questions: list[Question]
    model: str
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TelephonicOut(BaseModel):
    """Where a requirement's telephonic round questions stand."""

    draft: QuestionSetOut | None
    approved: QuestionSetOut | None
    has_jd: bool
    ai_ready: bool  # the question-writing AI is configured
    # The JD changed after the approved set was made (worth regenerating)
    jd_changed: bool


# --- What the AI returns (lenient: cleaned up before it's stored) ---


class GeneratedQuestion(BaseModel):
    text: str = Field(min_length=5)
    type: str = "skill"
    rubric: str = ""
    weight: int = 2

    @field_validator("type", mode="before")
    @classmethod
    def _type(cls, value: object) -> str:
        text = str(value or "").strip().lower()
        return text if text in QUESTION_TYPES else "skill"

    @field_validator("weight", mode="before")
    @classmethod
    def _weight(cls, value: object) -> int:
        try:
            return min(3, max(1, round(float(str(value)))))
        except ValueError:
            return 2


class GeneratedQuestions(BaseModel):
    questions: list[GeneratedQuestion] = Field(min_length=1)


# --- Telephonic round calls (step 6b) ---

MAX_TELEPHONIC_BATCH = 20


class TelephonicCallsRequest(BaseModel):
    """Start telephonic round calls for a requirement's candidates: the ones listed, or (none
    listed) up to 20 interested candidates who haven't had the round yet."""

    model_config = ConfigDict(extra="forbid")

    candidate_ids: list[uuid.UUID] = Field(default_factory=list, max_length=MAX_TELEPHONIC_BATCH)
    # True: only check who could be called (the confirmation dialog), queue nothing
    dry_run: bool = False
    # The recruiter confirmed calling beyond max_attempts (counted for telephonic calls only)
    override_limit: bool = False
    # The recruiter confirmed a second round for candidates who have done it
    call_again: bool = False
