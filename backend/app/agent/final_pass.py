"""Post-call final extraction, reconciliation and validation (phase-07 P7-T1, P7-T2).

1. One LLM pass over the whole transcript: the candidate's final answer for every field, each
   with an evidence quote and the transcript line (`seq`) it came from.
2. Every value is validated with the P2 rules and its quote must be found in a candidate line;
   anything else is rejected (prevents invented data).
3. The result is reconciled with the live state from the call:

   | Live state      | Final pass                          | Result                              |
   |-----------------|-------------------------------------|-------------------------------------|
   | value           | same value                          | keep                                |
   | CONFIRMED value | different                           | keep live, flag `conflict`          |
   | ANSWERED value  | different, evidence later           | take final, live kept in `previous` |
   | ANSWERED value  | different, evidence not later       | keep live, flag `conflict`          |
   | MISSING/UNKNOWN | value with evidence                 | accept, `source=final_pass`         |
   | DECLINED        | anything                            | stays DECLINED                      |

4. `FinalScreeningData` applies the range rules once more: a bad field becomes null plus a
   note; the rest of the record still saves. `screening_status` applies the phase-07 table.

Pure functions apart from `run_final_pass`; the database work is in finalization_service.
"""

import json
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.conversation_manager import ScreeningResult
from app.agent.extraction import (
    CTC_RANGE,
    EXPERIENCE_RANGE,
    MAX_TEXT_LEN,
    contains_words,
    has_name,
    quote_matches,
    same_words,
    validate_field,
)
from app.agent.schemas import FIELD_TO_KEY, ExtractedFields, FieldName
from app.agent.state import FieldStatus, FieldValue, QuestionSpec, same_value
from app.database.models.enums import ScreeningStatus
from app.providers.llm.base import LLMError, LLMProvider, Message

log = structlog.get_logger(__name__)

FINAL_PASS_TIMEOUT_S = 25.0
FINAL_PASS_MAX_TOKENS = 1500
FINAL_EXTRACTION_VERSION = "p7-2026-11-19.1"


# --- LLM output ----------------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FinalFields(ExtractedFields):
    """The candidate's FINAL answer for each field across the whole call. If they corrected
    themselves, the corrected value. null = never stated by the candidate."""


class FinalEvidence(_Strict):
    field: str = Field(description="Key of a non-null field in `fields`")
    quote: str = Field(description="The candidate's exact words that give the final value")
    seq: int = Field(description="Number of the CANDIDATE line the quote comes from")


class FinalCustomAnswer(_Strict):
    key: str = Field(description="Key of a custom question listed under QUESTIONS")
    answer: str
    quote: str
    seq: int


class FinalPassOutput(_Strict):
    fields: FinalFields
    evidence: list[FinalEvidence] = Field(description="One entry per non-null value in `fields`")
    custom_answers: list[FinalCustomAnswer]


FINAL_EXTRACTION_PROMPT = """\
You read the transcript of a phone screening between a recruiter's AI assistant and a candidate \
and extract the candidate's final answers.
- Use only what the CANDIDATE said (lines marked "Candidate"). Never take a value from the \
assistant's lines, even if the assistant read it back, unless the candidate stated it.
- If the candidate corrected an answer, return the corrected (latest) value.
- For every non-null value give one evidence entry: the candidate's exact words and the number \
of that candidate line.
- null when the candidate never stated it, refused, or said they don't know. Don't guess.
- Units: experience in years ("5 years 6 months" -> 5.5); CTC in lakhs per annum ("12 lakhs" \
-> 12, "1.2 crore" -> 120, "80k per month" -> 9.6). A range ("15 to 18 lakhs") -> null.
- Custom questions: answer in the candidate's words, briefly, with evidence.
"""


@dataclass
class TranscriptLine:
    seq: int
    speaker: str
    text: str


def transcript_lines(transcript: list[dict[str, Any]]) -> list[TranscriptLine]:
    lines = []
    for i, entry in enumerate(transcript, start=1):
        speaker = str(entry.get("speaker") or "")
        # An interrupted reply: only what the candidate heard counts
        text = entry.get("heard_text") if entry.get("interrupted") else entry.get("text")
        if text:
            lines.append(TranscriptLine(int(entry.get("seq") or i), speaker, str(text)))
    return lines


def _render(lines: list[TranscriptLine]) -> str:
    who = {"candidate": "Candidate", "assistant": "Assistant"}
    return "\n".join(f"[{ln.seq}] {who.get(ln.speaker, ln.speaker)}: {ln.text}" for ln in lines)


async def run_final_pass(
    llm: LLMProvider,
    transcript: list[dict[str, Any]],
    questions: list[QuestionSpec],
    *,
    timeout_s: float = FINAL_PASS_TIMEOUT_S,
) -> FinalPassOutput | None:
    """The LLM pass, or None when it fails (the live state is then used as it is)."""
    lines = transcript_lines(transcript)
    if not any(ln.speaker == "candidate" for ln in lines):
        return None
    custom = [
        {"key": q.key, "question": q.prompt} for q in questions if q.standard is None and q.key
    ]
    messages = [
        Message("system", FINAL_EXTRACTION_PROMPT),
        Message(
            "user",
            "QUESTIONS (custom): "
            + json.dumps(custom, ensure_ascii=False)
            + "\n\nTRANSCRIPT:\n"
            + _render(lines),
        ),
    ]
    try:
        out = await llm.structured(
            messages, FinalPassOutput, timeout_s=timeout_s, max_tokens=FINAL_PASS_MAX_TOKENS
        )
    except LLMError as exc:
        log.warning("final_pass_failed", error=type(exc).__name__)
        return None
    return out.value


# --- Evidence and reconciliation ----------------------------------------------------------------


@dataclass
class Proposal:
    """A value proposed by the final pass, after validation and the evidence check."""

    value: FieldValue
    quote: str
    seq: int
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class FinalField:
    value: FieldValue
    status: str  # FieldStatus value
    source: str  # live | final_pass | none
    raw_text: str | None = None
    seq: int | None = None  # transcript line of the evidence, when known
    meta: dict[str, Any] = field(default_factory=dict)
    previous: list[dict[str, Any]] = field(default_factory=list)
    conflict: dict[str, Any] | None = None
    note: str | None = None  # validation note when a value was dropped

    @property
    def has_value(self) -> bool:
        return self.value is not None


def find_evidence(quote: str, cited_seq: int, lines: list[TranscriptLine]) -> int | None:
    """The candidate line holding `quote`: the cited one first, then the latest that matches."""
    candidate_lines = [ln for ln in lines if ln.speaker == "candidate"]
    for ln in candidate_lines:
        if ln.seq == cited_seq and quote_matches(quote, ln.text):
            return ln.seq
    for match in (contains_words, quote_matches):  # exact words first, then fuzzy
        for ln in reversed(candidate_lines):
            if match(quote, ln.text):
                return ln.seq
    return None


def proposals(
    output: FinalPassOutput | None, keys: list[str], lines: list[TranscriptLine]
) -> tuple[dict[str, Proposal], dict[str, str]]:
    """Validated, evidence-backed final-pass values per field, and the rejected ones (reason)."""
    if output is None:
        return {}, {}
    accepted: dict[str, Proposal] = {}
    rejected: dict[str, str] = {}
    evidence: dict[str, FinalEvidence] = {}
    for ev in output.evidence:
        name = ev.field.strip().lower().removesuffix("_years").removesuffix("_lpa")
        evidence.setdefault(name, ev)

    raw = output.fields.model_dump()
    for name, model_key in FIELD_TO_KEY.items():
        value = raw.get(model_key)
        if value is None or name.value not in keys:
            continue
        found = evidence.get(name.value)
        seq = find_evidence(found.quote, found.seq, lines) if found else None
        if found is None or seq is None:
            rejected[name.value] = "evidence not found in the candidate's words"
            continue
        clean, meta = validate_field(name, value, raw.get("notice_period_days"))
        if clean is None:
            rejected[name.value] = f"invalid value: {value!r}"
            continue
        accepted[name.value] = Proposal(clean, found.quote, seq, meta)

    for custom in output.custom_answers:
        key = custom.key.strip()
        if key not in keys or key in accepted:
            continue
        seq = find_evidence(custom.quote, custom.seq, lines)
        answer = " ".join(custom.answer.split())[:MAX_TEXT_LEN]
        if seq is None:
            rejected[key] = "evidence not found in the candidate's words"
        elif answer:
            accepted[key] = Proposal(answer, custom.quote, seq)
    return accepted, rejected


def live_seq(record: dict[str, Any], lines: list[TranscriptLine]) -> int | None:
    """Transcript line of the live value: where its raw words appear exactly (latest), else the
    n-th candidate line for the live turn number, else a fuzzy match of the raw words."""
    candidate_lines = [ln for ln in lines if ln.speaker == "candidate"]
    raw = str(record.get("raw_text") or "")
    if raw:
        for ln in reversed(candidate_lines):
            if contains_words(raw, ln.text):
                return ln.seq
    turn = record.get("turn")
    if isinstance(turn, int) and 1 <= turn <= len(candidate_lines):
        return candidate_lines[turn - 1].seq
    if raw:
        for ln in reversed(candidate_lines):
            if quote_matches(raw, ln.text):
                return ln.seq
    return None


def same_answer(live: "FinalField", new: Proposal) -> bool:
    """The final pass restating the live answer, not contradicting it: equal values, the same
    words, the same candidate line, or the same notice days. (Real calls 2026-11-19: most
    "conflicts" were "Thirty days" vs "30 days" or one quote with and without its full stop.)"""
    if same_value(live.value, new.value):
        return True
    if isinstance(live.value, str) and isinstance(new.value, str):
        if same_words(live.value, new.value):
            return True
    if live.seq is not None and live.seq == new.seq:
        return True
    days = live.meta.get("days")
    return days is not None and days == new.meta.get("days")


def reconcile(
    live_fields: dict[str, dict[str, Any]],
    keys: list[str],
    proposed: dict[str, Proposal],
    lines: list[TranscriptLine],
) -> dict[str, FinalField]:
    out: dict[str, FinalField] = {}
    for key in keys:
        live = live_fields.get(key) or {}
        status = str(live.get("status") or FieldStatus.MISSING.value)
        live_value = live.get("value") if status in ("answered", "confirmed") else None
        kept = FinalField(
            value=live_value,
            status=status,
            source="live" if live_value is not None else "none",
            raw_text=live.get("raw_text"),
            seq=live_seq(live, lines) if live_value is not None else None,
            meta=dict(live.get("meta") or {}),
            previous=list(live.get("previous") or []),
        )
        new = proposed.get(key)
        if status == FieldStatus.DECLINED or new is None:
            out[key] = kept
        elif live_value is None:  # MISSING or UNKNOWN
            out[key] = FinalField(
                value=new.value,
                status=FieldStatus.ANSWERED.value,
                source="final_pass",
                raw_text=new.quote,
                seq=new.seq,
                meta={**new.meta, "source": "final_pass"},
            )
        elif same_answer(kept, new):
            out[key] = kept
        elif status == FieldStatus.ANSWERED and (kept.seq is None or new.seq > kept.seq):
            out[key] = FinalField(
                value=new.value,
                status=FieldStatus.ANSWERED.value,
                source="final_pass",
                raw_text=new.quote,
                seq=new.seq,
                meta={**new.meta, "source": "final_pass"},
                previous=[
                    *kept.previous,
                    {"value": live_value, "raw_text": kept.raw_text, "seq": kept.seq},
                ],
            )
        else:
            kept.conflict = {
                "final_value": new.value,
                "quote": new.quote,
                "seq": new.seq,
                "reason": "confirmed during the call"
                if status == FieldStatus.CONFIRMED
                else "final pass evidence is not later than the live answer",
            }
            out[key] = kept
    return out


# --- Validation (P7-T2) ------------------------------------------------------------------------


def _in(value: Any, bounds: tuple[float, float]) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and (bounds[0] <= float(value) <= bounds[1])
    )


class FinalScreeningData(BaseModel):
    """The standard fields after the range rules. A value that fails becomes null and gets a
    note in `notes`; the other fields are unaffected."""

    current_location: str | None = None
    current_company: str | None = None
    total_experience: float | None = None
    relevant_experience: float | None = None
    current_ctc: float | None = None
    expected_ctc: float | None = None
    notice_period: str | None = None
    reason_for_change: str | None = None
    interested: bool | None = None
    interview_availability: str | None = None
    notes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _null_bad_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        values = dict(data)
        notes = dict(values.get("notes") or {})

        def bad(key: str, why: str) -> None:
            notes[key] = f"{why}: {values[key]!r}"
            values[key] = None

        for key in (FieldName.TOTAL_EXPERIENCE, FieldName.RELEVANT_EXPERIENCE):
            if values.get(key) is not None and not _in(values[key], EXPERIENCE_RANGE):
                bad(key, "experience out of range")
        for key in (FieldName.CURRENT_CTC, FieldName.EXPECTED_CTC):
            if values.get(key) is not None and not _in(values[key], CTC_RANGE):
                bad(key, "CTC out of range (LPA)")
        if values.get(FieldName.INTERESTED) is not None and not isinstance(
            values[FieldName.INTERESTED], bool
        ):
            bad(FieldName.INTERESTED, "not a yes/no answer")
        for key in (
            FieldName.CURRENT_LOCATION,
            FieldName.CURRENT_COMPANY,
            FieldName.NOTICE_PERIOD,
            FieldName.REASON_FOR_CHANGE,
            FieldName.INTERVIEW_AVAILABILITY,
        ):
            value = values.get(key)
            if value is None:
                continue
            if not isinstance(value, str) or not value.strip():
                bad(key, "empty or not text")
            elif len(value) > MAX_TEXT_LEN:
                values[key] = value[:MAX_TEXT_LEN]
        for key in (FieldName.CURRENT_LOCATION, FieldName.CURRENT_COMPANY):
            if isinstance(values.get(key), str) and not has_name(values[key]):
                bad(key, "no name in the answer")
        values["notes"] = notes
        return values

    def standard_values(self) -> dict[str, FieldValue]:
        return self.model_dump(exclude={"notes"})


def validate(final: dict[str, FinalField]) -> FinalScreeningData:
    """Apply FinalScreeningData to the reconciled fields; a dropped value is reflected back."""
    standard = {f.value for f in FieldName}
    data = FinalScreeningData.model_validate(
        {k: f.value for k, f in final.items() if k in standard}
    )
    for key, note in data.notes.items():
        rec = final.get(key)
        if rec is not None:
            rec.previous.append({"value": rec.value, "raw_text": rec.raw_text, "seq": rec.seq})
            rec.value, rec.status, rec.source, rec.note = None, "missing", "none", note
    return data


# --- Screening status (P7-T2) --------------------------------------------------------------------


def required_settled(final: dict[str, FinalField], questions: list[QuestionSpec]) -> bool:
    """Every required field answered, confirmed, declined or unknown (nothing MISSING)."""
    return all(
        final.get(q.key) is not None and final[q.key].status != FieldStatus.MISSING
        for q in questions
        if q.required
    )


def screening_status(
    result: ScreeningResult, final: dict[str, FinalField], questions: list[QuestionSpec]
) -> ScreeningStatus | None:
    """phase-07 P7-T2. None = leave the candidate's status unchanged (no data, no decision)."""
    reason = result.end_reason.value
    if result.opted_out or reason == "opted_out":
        return ScreeningStatus.OPTED_OUT
    if reason == "declined" or result.declined_opportunity:
        return ScreeningStatus.DECLINED
    if reason == "wrong_person":
        return ScreeningStatus.WRONG_PERSON
    completed = reason == "completed" and required_settled(final, questions)
    if reason == "callback" or (result.callback.get("requested") and not completed):
        return ScreeningStatus.CALLBACK_REQUESTED
    if completed:
        return ScreeningStatus.COMPLETED
    if any(f.has_value for f in final.values()):
        return ScreeningStatus.PARTIALLY_COMPLETED
    return None


# --- Everything together -----------------------------------------------------------------------


@dataclass
class FinalOutcome:
    fields: dict[str, FinalField]
    data: FinalScreeningData
    status: ScreeningStatus | None
    rejected: dict[str, str]
    final_pass_ran: bool

    @property
    def conflicts(self) -> dict[str, dict[str, Any]]:
        return {k: f.conflict for k, f in self.fields.items() if f.conflict}

    @property
    def missing(self) -> list[str]:
        return [k for k, f in self.fields.items() if f.status == FieldStatus.MISSING]

    def to_json(self) -> dict[str, Any]:
        return {
            "version": FINAL_EXTRACTION_VERSION,
            "final_pass_ran": self.final_pass_ran,
            "screening_status": self.status.value if self.status else None,
            "fields": {k: asdict(f) for k, f in self.fields.items()},
            "collected_data": {k: f.value for k, f in self.fields.items()},
            "missing_fields": self.missing,
            "conflicts": self.conflicts,
            "rejected": self.rejected,
            "validation_notes": self.data.notes,
        }


def finalize(
    result: ScreeningResult,
    questions: list[QuestionSpec],
    output: FinalPassOutput | None,
) -> FinalOutcome:
    keys = [q.key for q in questions] or list(result.fields)
    lines = transcript_lines(result.transcript)
    proposed, rejected = proposals(output, keys, lines)
    fields = reconcile(result.fields, keys, proposed, lines)
    data = validate(fields)
    return FinalOutcome(
        fields=fields,
        data=data,
        status=screening_status(result, fields, questions),
        rejected=rejected,
        final_pass_ran=output is not None,
    )
