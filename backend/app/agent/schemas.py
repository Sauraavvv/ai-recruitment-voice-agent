"""Structured output the LLM returns for each candidate turn (plan.md "Agent output contract").

Strict structured outputs need every property required and no free-form dicts, so every field is
listed without a default and "not mentioned" is `null`. Key names carry units (`_years`, `_lpa`)
so the model normalizes; `extraction.py` still validates every value.
"""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class FieldName(StrEnum):
    """Standard screening fields; values match the candidate table columns (plan.md Module C)."""

    CURRENT_LOCATION = "current_location"
    CURRENT_COMPANY = "current_company"
    TOTAL_EXPERIENCE = "total_experience"
    RELEVANT_EXPERIENCE = "relevant_experience"
    CURRENT_CTC = "current_ctc"
    EXPECTED_CTC = "expected_ctc"
    NOTICE_PERIOD = "notice_period"
    REASON_FOR_CHANGE = "reason_for_change"
    INTERESTED = "interested"
    INTERVIEW_AVAILABILITY = "interview_availability"


# The names the model sees (unit-suffixed) ↔ the internal field names.
FIELD_TO_KEY: dict[FieldName, str] = {
    FieldName.CURRENT_LOCATION: "current_location",
    FieldName.CURRENT_COMPANY: "current_company",
    FieldName.TOTAL_EXPERIENCE: "total_experience_years",
    FieldName.RELEVANT_EXPERIENCE: "relevant_experience_years",
    FieldName.CURRENT_CTC: "current_ctc_lpa",
    FieldName.EXPECTED_CTC: "expected_ctc_lpa",
    FieldName.NOTICE_PERIOD: "notice_period",
    FieldName.REASON_FOR_CHANGE: "reason_for_change",
    FieldName.INTERESTED: "interested",
    FieldName.INTERVIEW_AVAILABILITY: "interview_availability",
}
KEY_TO_FIELD: dict[str, FieldName] = {v: k for k, v in FIELD_TO_KEY.items()}
NUMERIC_FIELDS = frozenset(
    {
        FieldName.TOTAL_EXPERIENCE,
        FieldName.RELEVANT_EXPERIENCE,
        FieldName.CURRENT_CTC,
        FieldName.EXPECTED_CTC,
    }
)


class NextAction(StrEnum):
    ASK_QUESTION = "ask_question"
    CLARIFY = "clarify"
    ANSWER_CANDIDATE = "answer_candidate"
    SCHEDULE_CALLBACK = "schedule_callback"
    END_CALL = "end_call"
    ESCALATE = "escalate"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedFields(_Strict):
    """Values stated in the candidate's latest message only. null = not stated in this message."""

    current_location: str | None = Field(description="City or town where the candidate lives now")
    current_company: str | None = Field(description="Employer's name as stated")
    total_experience_years: float | None = Field(
        description="Total work experience in years. '5 years 6 months' -> 5.5; fresher -> 0"
    )
    relevant_experience_years: float | None = Field(
        description="Experience relevant to this role, in years"
    )
    current_ctc_lpa: float | None = Field(
        description=(
            "Current annual CTC in lakhs per annum. '12 lakhs' -> 12; '1.2 crore' -> 120; "
            "'80k per month' -> 9.6; '12,00,000' -> 12"
        )
    )
    expected_ctc_lpa: float | None = Field(description="Expected annual CTC in lakhs per annum")
    notice_period: str | None = Field(
        description="Notice period in the candidate's words, e.g. '30 days', 'serving notice'"
    )
    notice_period_days: int | None = Field(
        description="Notice period in days when derivable; immediate joiner -> 0"
    )
    reason_for_change: str | None = Field(description="Why they want to change jobs, briefly")
    interested: bool | None = Field(
        description="true/false only when clearly stated; 'maybe, depends' -> null"
    )
    interview_availability: str | None = Field(
        description="When they can interview, in their words"
    )


class FieldEvidence(_Strict):
    field: str = Field(description="Key of an extracted field or custom question")
    quote: str = Field(description="The candidate's exact words from the latest message")


class RangeAnswer(_Strict):
    field: str = Field(description="Numeric field key answered with a range")
    low: float
    high: float
    quote: str


class CustomAnswer(_Strict):
    key: str = Field(description="Key of a custom question listed in the job context")
    answer: str
    quote: str


class AgentTurn(_Strict):
    extracted_fields: ExtractedFields
    evidence: list[FieldEvidence] = Field(description="One quote per non-null extracted value")
    ranges: list[RangeAnswer] = Field(
        description="Numeric answers given as a range ('15 to 18 lakhs'); leave the value null"
    )
    custom_answers: list[CustomAnswer]
    declined_fields: list[str] = Field(description="Fields the candidate refused to share")
    unknown_fields: list[str] = Field(description="Fields the candidate says they don't know")
    confirmed_fields: list[str] = Field(
        description="Fields whose value the candidate just affirmed when asked to confirm"
    )
    identity_confirmed: bool | None = Field(
        description="Only for the identity question: true = it's them, false = wrong person"
    )
    permission_granted: bool | None = Field(
        description="Only for 'is this a good time': true = go ahead, false = not now"
    )
    callback_requested: bool
    callback_time_text: str | None = Field(description="Callback time in the candidate's words")
    callback_time_iso: str | None = Field(
        description="Callback time as ISO 8601 with +05:30 offset, resolved against NOW; "
        "null if vague"
    )
    opt_out: bool = Field(description="Candidate asked never to be called or to remove the number")
    declined_opportunity: bool = Field(description="Candidate is clearly not interested")
    candidate_question: str | None = Field(description="Question the candidate asked, if any")
    next_action: NextAction
    next_question: str | None = Field(description="Key of the field your reply asks about")
    conversation_complete: bool
    response_text: str = Field(description="What you say next: spoken, at most two sentences")
