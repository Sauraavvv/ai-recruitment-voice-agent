"""Recruiter-facing screening summary (plan.md Module G, phase plan 5.10).

Facts (missing information, callback, opt-out) come from state. The LLM only writes a short
neutral paragraph from the collected answers, and anything that sounds like a hiring judgment
is rejected.
"""

import json
import re
from typing import Any, Literal

import structlog
from pydantic import BaseModel

from app.agent.conversation_manager import ScreeningResult
from app.agent.schemas import FieldName
from app.providers.llm.base import LLMError, LLMProvider, Message

log = structlog.get_logger(__name__)

MAX_CHARS = 1000
SUMMARY_TIMEOUT_S = 15.0
SUMMARY_TRIES = 3  # phase-07 P7-T4: up to 2 retries (errors or a rejected judgment/pronoun)

JUDGMENT = re.compile(
    r"\b(suitab\w*|unsuitab\w*|strong (candidate|fit|profile)|weak (candidate|profile)|"
    r"recommend\w*|reject\w*|(good|great|poor|perfect|ideal|excellent|bad) (fit|match|candidate)|"
    r"not a (good )?fit|shortlist\w*|should (be )?hire\w*|qualified|unqualified|impressive)\b",
    re.IGNORECASE,
)

SUMMARY_PROMPT = """\
You write a short, neutral summary of a phone screening for a recruiter.
- 3 to 6 plain sentences, under 700 characters, no lists or markdown.
- Use only the facts in DATA. If a field is missing, don't mention it; don't guess.
- Don't judge the candidate: never say suitable, unsuitable, strong, weak, good fit, recommend, \
reject or similar. Just report what they said.
- CTC values are in lakhs per annum (LPA); experience in years.
- Refer to the candidate by name or as "the candidate". Never use gendered pronouns (he, she, \
his, her): the candidate's gender is unknown.
"""

# The name says nothing reliable about gender; a summary that assumes one is rewritten.
GENDERED = re.compile(r"\b(he|she|him|his|her|hers|himself|herself)\b", re.IGNORECASE)


class ScreeningSummary(BaseModel):
    candidate_profile: str
    experience: str
    compensation: str
    notice_period: str
    reason_for_change: str
    interest: str
    interview_availability: str
    missing_information: list[str]
    callback: str | None
    opted_out: bool
    narrative: str | None
    text: str
    generated_by: Literal["llm", "deterministic"]


def _fmt(value: Any, unit: str = "") -> str:
    if value is None:
        return "not provided"
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{value}{unit}"


def _status(result: ScreeningResult, key: str) -> str:
    return str(result.fields.get(key, {}).get("status", "missing"))


def _section(result: ScreeningResult, key: FieldName, unit: str = "") -> str:
    status = _status(result, key)
    if status == "declined":
        return "declined to share"
    if status == "unknown":
        return "not known"
    return _fmt(result.collected_data.get(key), unit)


def deterministic_sections(result: ScreeningResult, candidate_name: str) -> dict[str, Any]:
    d = result.collected_data
    profile = [candidate_name]
    if d.get(FieldName.CURRENT_LOCATION):
        profile.append(f"based in {d[FieldName.CURRENT_LOCATION]}")
    if d.get(FieldName.CURRENT_COMPANY):
        profile.append(f"currently at {d[FieldName.CURRENT_COMPANY]}")
    interested = d.get(FieldName.INTERESTED)
    interest = (
        "interested"
        if interested is True
        else "not interested"
        if interested is False
        else _section(result, FieldName.INTERESTED)
    )
    callback = None
    if result.callback.get("requested"):
        when = result.callback.get("time_iso") or result.callback.get("time_text")
        callback = f"requested ({when})" if when else "requested, no time given"
    return {
        "candidate_profile": ", ".join(profile),
        "experience": (
            f"total {_section(result, FieldName.TOTAL_EXPERIENCE, ' years')}, "
            f"relevant {_section(result, FieldName.RELEVANT_EXPERIENCE, ' years')}"
        ),
        "compensation": (
            f"current {_section(result, FieldName.CURRENT_CTC, ' LPA')}, "
            f"expected {_section(result, FieldName.EXPECTED_CTC, ' LPA')}"
        ),
        "notice_period": _section(result, FieldName.NOTICE_PERIOD),
        "reason_for_change": _section(result, FieldName.REASON_FOR_CHANGE),
        "interest": interest,
        "interview_availability": _section(result, FieldName.INTERVIEW_AVAILABILITY),
        "missing_information": list(result.missing_fields),
        "callback": callback,
        "opted_out": result.opted_out,
    }


def _facts_text(sections: dict[str, Any]) -> str:
    lines = [
        f"Profile: {sections['candidate_profile']}.",
        f"Experience: {sections['experience']}.",
        f"Compensation: {sections['compensation']}.",
        f"Notice period: {sections['notice_period']}.",
        f"Reason for change: {sections['reason_for_change']}.",
        f"Interest: {sections['interest']}.",
        f"Interview availability: {sections['interview_availability']}.",
    ]
    return " ".join(lines)


def _tail(sections: dict[str, Any]) -> str:
    parts = []
    if sections["missing_information"]:
        parts.append(
            "Missing: " + ", ".join(sections["missing_information"]).replace("_", " ") + "."
        )
    if sections["callback"]:
        parts.append(f"Callback {sections['callback']}.")
    if sections["opted_out"]:
        parts.append("Candidate opted out of further calls.")
    return " ".join(parts)


def _compose(body: str, tail: str) -> str:
    text = f"{body} {tail}".strip()
    if len(text) <= MAX_CHARS:
        return text
    room = MAX_CHARS - len(tail) - 2
    return f"{body[: max(0, room)].rsplit(' ', 1)[0]}… {tail}".strip()[:MAX_CHARS]


async def generate_summary(
    result: ScreeningResult, *, candidate_name: str, job_title: str, llm: LLMProvider | None
) -> ScreeningSummary:
    sections = deterministic_sections(result, candidate_name)
    tail = _tail(sections)
    narrative: str | None = None
    if llm is not None and any(v is not None for v in result.collected_data.values()):
        data = {
            "candidate": candidate_name,
            "role": job_title,
            "answers": {k: v for k, v in result.collected_data.items() if v is not None},
            "declined_to_share": [k for k in result.fields if _status(result, k) == "declined"],
            "candidate_questions": result.candidate_questions,
        }
        messages = [
            Message("system", SUMMARY_PROMPT),
            Message("user", "DATA: " + json.dumps(data, ensure_ascii=False)),
        ]
        for attempt in range(1, SUMMARY_TRIES + 1):  # the first try plus up to 2 retries
            try:
                out = await llm.text(messages, timeout_s=SUMMARY_TIMEOUT_S, max_tokens=400)
            except LLMError as exc:
                log.warning("summary_llm_failed", attempt=attempt, error=type(exc).__name__)
                continue
            candidate_text = " ".join(out.value.split())
            judged, gendered = JUDGMENT.search(candidate_text), GENDERED.search(candidate_text)
            if not judged and not gendered:
                narrative = candidate_text
                break
            log.warning(
                "summary_rejected", attempt=attempt, judged=bool(judged), gendered=bool(gendered)
            )
            fix = (
                "Your summary judged the candidate. Rewrite it with facts only."
                if judged
                else "Your summary used a gendered pronoun. Rewrite it using the candidate's "
                "name or 'the candidate' instead."
            )
            messages.append(Message("developer", fix))
    body = narrative or _facts_text(sections)
    return ScreeningSummary(
        **sections,
        narrative=narrative,
        text=_compose(body, tail),
        generated_by="llm" if narrative else "deterministic",
    )


# --- Which summary a candidate shows (phase-08, decided with the user 2026-11-19) -----------


def collected_data(extracted_data: dict[str, Any] | None) -> bool:
    """Did this call collect any value? (A call that only reached voicemail, or where the
    candidate hung up before answering, didn't.)"""
    final = (extracted_data or {}).get("final") or {}
    fields = final.get("fields") or {}
    if any(isinstance(f, dict) and f.get("value") is not None for f in fields.values()):
        return True
    return any(v is not None for v in (final.get("collected_data") or {}).values())


def pick_summary_conversation[C](conversations: list[C]) -> C | None:
    """The conversation whose summary a candidate shows: the latest finalized one that
    collected data, else the latest finalized one. `conversations`: finalized, oldest first;
    each needs `.extracted_data`. A call with no data keeps its own summary in its history."""
    for conv in reversed(conversations):
        if collected_data(getattr(conv, "extracted_data", None)):
            return conv
    return conversations[-1] if conversations else None
