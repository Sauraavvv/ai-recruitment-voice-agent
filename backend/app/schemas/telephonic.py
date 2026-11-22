"""Telephonic round: the questions asked on the second call, made from the requirement's JD."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database.models.enums import CallEndReason, CallStatus, QuestionSetStatus
from app.schemas.candidate import Eligibility

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


# --- The interested candidates and their telephonic round calls (step 6b, build step 4) ---

# Where a candidate stands in the round (from their latest telephonic call):
#   not_called · queued · on_call · retry_scheduled · callback · done (the round finished) ·
#   incomplete (answered, but the round didn't finish) · no_answer · declined · opted_out ·
#   failed
RoundStatus = Literal[
    "not_called",
    "queued",
    "on_call",
    "retry_scheduled",
    "callback",
    "done",
    "incomplete",
    "no_answer",
    "declined",
    "opted_out",
    "failed",
]
AnswerStatus = Literal["answered", "partial", "dont_know", "declined", "not_asked"]


class RoundCall(BaseModel):
    """A candidate's latest telephonic round call."""

    id: uuid.UUID
    attempt_number: int
    call_status: CallStatus
    end_reason: CallEndReason | None
    at: datetime
    terminal: bool
    next_retry_at: datetime | None
    question_set_id: uuid.UUID | None
    version: int | None  # the question set's version this call asked
    finalized: bool
    has_transcript: bool
    answered: int  # questions with an answer (answered or partly)
    questions: int


class RoundRow(BaseModel):
    candidate_id: uuid.UUID
    name: str
    phone: str
    status: RoundStatus
    last_call: RoundCall | None
    done_before: bool  # finished the round on some call (another one needs a confirmation)
    eligibility: Eligibility


class RoundRoster(BaseModel):
    """The requirement's interested candidates, for the telephonic round."""

    approved_version: int | None  # the version a new call would ask
    rows: list[RoundRow]


class RoundAnswer(BaseModel):
    question_id: str
    question: str
    status: AnswerStatus
    answer: str
    follow_up_asked: bool = False
    follow_up: str | None = None
    checked: bool = True  # False: kept as said, the AI was busy on that turn
    from_earlier_call: bool = False


class CallAnswers(BaseModel):
    """What a telephonic round call recorded, question by question."""

    call_attempt_id: uuid.UUID
    candidate_id: uuid.UUID
    question_set_id: uuid.UUID | None
    version: int | None
    answers: list[RoundAnswer]
    candidate_questions: list[str]
    summary: str | None
    finalized: bool
    call_status: CallStatus
    end_reason: CallEndReason | None
    start_time: datetime | None
    duration_seconds: int | None
