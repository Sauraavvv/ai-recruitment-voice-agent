"""Deterministic screening state (phase plan 5.2, 5.3).

Python, not the LLM, decides which fields are missing, which question comes next and when the
screening is complete. That makes "don't repeat answered questions" and "don't invent answers"
enforceable and testable.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.agent.schemas import FieldName

FieldValue = str | float | bool | None

# A field is asked at most this many times (the question plus clarifications) before it's UNKNOWN.
MAX_CLARIFICATIONS = 2
MAX_ASKS = 1 + MAX_CLARIFICATIONS


class FieldStatus(StrEnum):
    MISSING = "missing"
    ANSWERED = "answered"
    CONFIRMED = "confirmed"
    DECLINED = "declined"  # candidate refused to share
    UNKNOWN = "unknown"  # candidate doesn't know, or gave up after clarifications


class Phase(StrEnum):
    GREETING = "greeting"
    IDENTITY_CHECK = "identity_check"
    PERMISSION = "permission"
    SCREENING = "screening"
    CONFIRMATION = "confirmation"
    CLOSING = "closing"
    ENDED = "ended"
    # Side exits; each ends the call.
    CALLBACK = "callback"
    DECLINED = "declined"
    OPTED_OUT = "opted_out"
    WRONG_PERSON = "wrong_person"
    ESCALATED = "escalated"


TERMINAL_PHASES = frozenset(
    {
        Phase.ENDED,
        Phase.CALLBACK,
        Phase.DECLINED,
        Phase.OPTED_OUT,
        Phase.WRONG_PERSON,
        Phase.ESCALATED,
    }
)


class EndReason(StrEnum):
    COMPLETED = "completed"
    CALLBACK = "callback"
    DECLINED = "declined"
    OPTED_OUT = "opted_out"
    WRONG_PERSON = "wrong_person"
    ESCALATED = "escalated"
    NO_RESPONSE = "no_response"
    HANGUP = "hangup"
    MAX_TURNS = "max_turns"
    ERROR = "error"


class AskKind(StrEnum):
    QUESTION = "question"
    CLARIFY = "clarify"
    CONFIRM = "confirm"


class MergeOutcome(StrEnum):
    SET = "set"
    UNCHANGED = "unchanged"
    CORRECTED = "corrected"
    IGNORED = "ignored"


class PriorValue(BaseModel):
    value: FieldValue
    raw_text: str | None = None
    turn: int | None = None


class FieldRecord(BaseModel):
    value: FieldValue = None
    status: FieldStatus = FieldStatus.MISSING
    raw_text: str | None = None  # the candidate's words that produced the value
    turn: int | None = None
    previous: list[PriorValue] = Field(default_factory=list)  # earlier values when corrected
    needs_confirmation: bool = False
    asked_count: int = 0
    clarify_count: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)  # e.g. {"days": 30}, {"range": [15, 18]}

    @property
    def has_value(self) -> bool:
        return self.status in (FieldStatus.ANSWERED, FieldStatus.CONFIRMED)

    @property
    def settled(self) -> bool:
        """Not to be asked again (outside confirmation)."""
        return self.status is not FieldStatus.MISSING


class QuestionSpec(BaseModel):
    key: str
    prompt: str
    required: bool = True
    type: str = "string"
    unit: str | None = None

    @property
    def standard(self) -> FieldName | None:
        try:
            return FieldName(self.key)
        except ValueError:
            return None


class CallbackInfo(BaseModel):
    requested: bool = False
    time_text: str | None = None
    time_iso: str | None = None  # Asia/Kolkata offset, validated: future and within 14 days
    needs_recruiter: bool = False  # vague time ("later"): no automatic callback
    time_asked: bool = False


def same_value(a: FieldValue, b: FieldValue) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return abs(float(a) - float(b)) < 0.01
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().casefold() == b.strip().casefold()
    return a == b


class ScreeningState(BaseModel):
    candidate_name: str
    job_title: str
    candidate_id: str | None = None
    call_id: str | None = None

    phase: Phase = Phase.GREETING
    turn_count: int = 0  # candidate utterances handled
    questions: list[QuestionSpec]
    fields: dict[str, FieldRecord]
    current_question: str | None = None
    current_ask_kind: AskKind | None = None

    callback: CallbackInfo = Field(default_factory=CallbackInfo)
    opted_out: bool = False
    declined_opportunity: bool = False
    identity_confirmed: bool | None = None
    escalation_reason: str | None = None
    candidate_questions: list[str] = Field(default_factory=list)
    readback_fields: list[str] = Field(default_factory=list)  # read back in CONFIRMATION
    end_reason: EndReason | None = None

    # Attempt counters for the fixed phases and recovery paths.
    identity_attempts: int = 0
    permission_attempts: int = 0
    low_confidence_streak: int = 0

    @classmethod
    def new(
        cls,
        *,
        candidate_name: str,
        job_title: str,
        questions: list[QuestionSpec],
        candidate_id: str | None = None,
        call_id: str | None = None,
    ) -> "ScreeningState":
        return cls(
            candidate_name=candidate_name,
            job_title=job_title,
            candidate_id=candidate_id,
            call_id=call_id,
            questions=questions,
            fields={q.key: FieldRecord() for q in questions},
        )

    # --- lookups -------------------------------------------------------------------------------

    @property
    def ended(self) -> bool:
        return self.phase in TERMINAL_PHASES

    def spec(self, key: str) -> QuestionSpec | None:
        return next((q for q in self.questions if q.key == key), None)

    def record(self, key: str) -> FieldRecord | None:
        return self.fields.get(key)

    def missing_fields(self, *, required_only: bool = False) -> list[str]:
        return [
            q.key
            for q in self.questions
            if self.fields[q.key].status is FieldStatus.MISSING
            and (q.required or not required_only)
        ]

    def pending_confirmation(self) -> list[str]:
        return [q.key for q in self.questions if self.fields[q.key].needs_confirmation]

    def next_field(self) -> str | None:
        """Corrections awaiting confirmation first, then the first MISSING field in job order."""
        pending = self.pending_confirmation()
        if pending:
            return pending[0]
        for q in self.questions:
            rec = self.fields[q.key]
            if rec.status is FieldStatus.MISSING and rec.asked_count < MAX_ASKS:
                return q.key
        return None

    def screening_complete(self) -> bool:
        """Every field asked or settled, nothing awaiting confirmation."""
        return self.next_field() is None

    def required_complete(self) -> bool:
        return not self.missing_fields(required_only=True) and not self.pending_confirmation()

    # --- merge rules (phase plan 5.3) -----------------------------------------------------------

    def merge(
        self,
        key: str,
        value: FieldValue,
        *,
        raw_text: str | None,
        turn: int,
        meta: dict[str, Any] | None = None,
        affirmed: bool = False,
    ) -> MergeOutcome:
        rec = self.fields.get(key)
        if rec is None or value is None:
            return MergeOutcome.IGNORED  # null never overwrites a value
        if rec.status in (FieldStatus.MISSING, FieldStatus.UNKNOWN, FieldStatus.DECLINED):
            rec.value, rec.raw_text, rec.turn = value, raw_text, turn
            rec.status = FieldStatus.CONFIRMED if affirmed else FieldStatus.ANSWERED
            rec.meta.update(meta or {})
            return MergeOutcome.SET
        if same_value(rec.value, value):
            if affirmed:
                rec.status = FieldStatus.CONFIRMED
                rec.needs_confirmation = False
            return MergeOutcome.UNCHANGED
        rec.previous.append(PriorValue(value=rec.value, raw_text=rec.raw_text, turn=rec.turn))
        rec.value, rec.raw_text, rec.turn = value, raw_text, turn
        rec.meta = dict(meta or {})
        if affirmed:
            rec.status, rec.needs_confirmation = FieldStatus.CONFIRMED, False
        else:
            rec.status, rec.needs_confirmation = FieldStatus.ANSWERED, True
        return MergeOutcome.CORRECTED

    def decline(self, key: str) -> bool:
        rec = self.fields.get(key)
        if rec is None or rec.status is not FieldStatus.MISSING:
            return False  # a refusal never discards an answer already given
        rec.status = FieldStatus.DECLINED
        return True

    def mark_unknown(self, key: str) -> bool:
        rec = self.fields.get(key)
        if rec is None or rec.status is not FieldStatus.MISSING:
            return False
        rec.status = FieldStatus.UNKNOWN
        return True

    def confirm(self, key: str) -> bool:
        rec = self.fields.get(key)
        if rec is None or not rec.has_value:
            return False
        rec.status, rec.needs_confirmation = FieldStatus.CONFIRMED, False
        return True

    def note_asked(self, key: str | None, kind: AskKind) -> None:
        self.current_question, self.current_ask_kind = key, (kind if key else None)
        rec = self.fields.get(key) if key else None
        if rec is None:
            return
        rec.asked_count += 1
        if kind is AskKind.CLARIFY:
            rec.clarify_count += 1

    # --- views ----------------------------------------------------------------------------------

    def collected_data(self) -> dict[str, FieldValue]:
        return {k: (r.value if r.has_value else None) for k, r in self.fields.items()}

    def plan_json(self) -> dict[str, Any]:
        """The conversation-state shape from plan.md Module C."""
        return {
            "candidate_id": self.candidate_id,
            "call_id": self.call_id,
            "conversation_status": "ended" if self.ended else "in_progress",
            "current_question": self.current_question,
            "collected_data": self.collected_data(),
            "missing_fields": self.missing_fields(),
            "callback_requested": self.callback.requested,
            "opted_out": self.opted_out,
        }
