import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

MAX_LONG_TEXT = 4000

QuestionType = Literal["string", "number", "boolean"]


class ScreeningQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,49}$")]
    prompt: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    required: bool = True
    type: QuestionType = "string"
    unit: Annotated[str, StringConstraints(max_length=20)] | None = None


# The ten standard fields (plan.md Module C). Keys and types are fixed; prompts are editable.
# Interest comes first so nobody is asked about salary after saying they aren't interested
# (Phase 2 plan 5.4). The order is the order the agent asks in.
STANDARD_QUESTIONS: list[ScreeningQuestion] = [
    ScreeningQuestion(
        key="interested",
        prompt="Are you interested in this opportunity?",
        type="boolean",
    ),
    ScreeningQuestion(key="current_location", prompt="Where are you currently located?"),
    ScreeningQuestion(key="current_company", prompt="Which company are you working with now?"),
    ScreeningQuestion(
        key="total_experience",
        prompt="How many years of total work experience do you have?",
        type="number",
        unit="years",
    ),
    ScreeningQuestion(
        key="relevant_experience",
        prompt="How many years of experience do you have that is relevant to this role?",
        type="number",
        unit="years",
    ),
    ScreeningQuestion(key="notice_period", prompt="What is your notice period?"),
    ScreeningQuestion(
        key="current_ctc", prompt="What is your current CTC?", type="number", unit="LPA"
    ),
    ScreeningQuestion(
        key="expected_ctc", prompt="What CTC are you expecting?", type="number", unit="LPA"
    ),
    ScreeningQuestion(
        key="reason_for_change", prompt="Why are you looking for a change right now?"
    ),
    ScreeningQuestion(
        key="interview_availability", prompt="When would you be available for an interview?"
    ),
]
STANDARD_TYPES: dict[str, str] = {q.key: q.type for q in STANDARD_QUESTIONS}


def default_screening_questions() -> list[ScreeningQuestion]:
    return [q.model_copy() for q in STANDARD_QUESTIONS]


Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=MAX_LONG_TEXT)]
Skill = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Questions = Annotated[list[ScreeningQuestion], Field(min_length=1, max_length=30)]


def _check_questions(questions: list[ScreeningQuestion] | None) -> None:
    if questions is None:
        return
    keys = [q.key for q in questions]
    duplicates = {k for k in keys if keys.count(k) > 1}
    if duplicates:
        raise ValueError(f"Duplicate screening question keys: {', '.join(sorted(duplicates))}")
    for q in questions:
        expected = STANDARD_TYPES.get(q.key)
        if expected is not None and q.type != expected:
            raise ValueError(f"Question '{q.key}' is a standard field and must be '{expected}'")


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_title: Title
    company_name: Title
    job_description: LongText = ""
    location: ShortText = ""
    required_experience: Annotated[str, StringConstraints(max_length=100)] = ""
    skills: Annotated[list[Skill], Field(max_length=50)] = []
    screening_questions: Questions | None = Field(
        default=None, description="Defaults to the ten standard questions"
    )
    agent_instructions: LongText = ""

    @model_validator(mode="after")
    def _questions(self) -> "JobCreate":
        _check_questions(self.screening_questions)
        return self


class JobUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_title: Title | None = None
    company_name: Title | None = None
    job_description: LongText | None = None
    location: ShortText | None = None
    required_experience: Annotated[str, StringConstraints(max_length=100)] | None = None
    skills: Annotated[list[Skill], Field(max_length=50)] | None = None
    screening_questions: Questions | None = None
    agent_instructions: LongText | None = None

    @model_validator(mode="after")
    def _questions(self) -> "JobUpdate":
        _check_questions(self.screening_questions)
        return self


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job_title: str
    company_name: str
    job_description: str
    location: str
    required_experience: str
    skills: list[str]
    screening_questions: list[ScreeningQuestion]
    agent_instructions: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DefaultQuestionsUpdate(BaseModel):
    """The full list of default questions, in order. Standard keys keep their types."""

    model_config = ConfigDict(extra="forbid")

    questions: Questions

    @model_validator(mode="after")
    def _questions(self) -> "DefaultQuestionsUpdate":
        _check_questions(self.questions)
        return self


class DefaultQuestionsOut(BaseModel):
    questions: list[ScreeningQuestion]
    jobs_updated: int = Field(description="Jobs that used the defaults and now ask the new list")
