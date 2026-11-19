"""One candidate → one Google Sheets row (plan.md Module H, phase-07 P7-T8). Pure functions.

- Dates in APP_TIMEZONE (Asia/Kolkata) as `YYYY-MM-DD HH:MM`.
- Booleans `Yes` / `No` / blank. Missing values blank.
- Numbers stay numbers (12.5, not "12.5"): written with valueInputOption=RAW a string would be
  stored as text, and the team couldn't sort or filter by CTC. Units are in the headers.
- Text is written RAW too, so a value like `=HYPERLINK(...)` stays text (no formula injection)
  and phone numbers keep their `+`.
- The transcript stays in the app behind login; the sheet links to the candidate page.
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.database.models import CallAttempt, CallStatus, Candidate, Conversation

HEADERS: list[str] = [
    "Candidate ID",
    "Candidate Name",
    "Phone Number",
    "Email",
    "Job Role",
    "Current Location",
    "Current Company",
    "Total Experience (Years)",
    "Relevant Experience (Years)",
    "Current CTC (LPA)",
    "Expected CTC (LPA)",
    "Notice Period",
    "Reason for Change",
    "Interested",
    "Interview Availability",
    "Call Status",
    "Screening Status",
    "Attempt Count",
    "Last Call Date",
    "Next Retry Date",
    "Call Summary",
    "Transcript Reference",
    "Last Updated",
]
assert len(HEADERS) == 23
LAST_COLUMN = "W"

Cell = str | int | float

# Attempts that never rang the candidate's phone don't count as attempts in the sheet.
_NOT_DIALED = frozenset(
    {
        CallStatus.PENDING,
        CallStatus.QUEUED,
        CallStatus.CANCELLED,
        CallStatus.RETRY_SCHEDULED,
        CallStatus.CALLBACK_REQUESTED,
    }
)
_SCHEDULED = frozenset({CallStatus.RETRY_SCHEDULED, CallStatus.CALLBACK_REQUESTED})


def counts_as_attempt(status: str) -> bool:
    return status not in _NOT_DIALED


def label(value: str | None) -> str:
    """`no_answer` → `No answer`."""
    if not value:
        return ""
    text = value.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def fmt_date(value: datetime | None, tz: ZoneInfo) -> str:
    if value is None:
        return ""
    return value.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def fmt_bool(value: bool | None) -> str:
    return "" if value is None else ("Yes" if value else "No")


def fmt_number(value: float | None) -> Cell:
    if value is None:
        return ""
    return int(value) if float(value).is_integer() else round(float(value), 2)


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def to_sheet_row(
    candidate: Candidate,
    latest_attempt: CallAttempt | None,
    latest_conversation: Conversation | None,
    attempt_count: int,
    *,
    frontend_url: str,
    tz: ZoneInfo,
) -> list[Cell]:
    attempt = latest_attempt
    last_call = None
    if attempt is not None and counts_as_attempt(attempt.call_status):
        last_call = attempt.start_time or attempt.end_time or attempt.created_at
    next_retry = (
        attempt.next_retry_at if attempt is not None and attempt.call_status in _SCHEDULED else None
    )
    updated = max(
        (
            t
            for t in (
                candidate.updated_at,
                attempt.updated_at if attempt else None,
                latest_conversation.updated_at if latest_conversation else None,
            )
            if t is not None
        ),
        default=None,
    )
    row: list[Cell] = [
        str(candidate.id),
        candidate.name,
        candidate.phone,
        _text(candidate.email),
        candidate.applied_role,
        _text(candidate.current_location),
        _text(candidate.current_company),
        fmt_number(candidate.total_experience),
        fmt_number(candidate.relevant_experience),
        fmt_number(candidate.current_ctc),
        fmt_number(candidate.expected_ctc),
        _text(candidate.notice_period),
        _text(candidate.reason_for_change),
        fmt_bool(candidate.interested),
        _text(candidate.interview_availability),
        label(attempt.call_status) if attempt else "",
        label(candidate.screening_status),
        attempt_count,
        fmt_date(last_call, tz),
        fmt_date(next_retry, tz),
        _text(latest_conversation.summary if latest_conversation else None),
        f"{frontend_url.rstrip('/')}/candidates/{candidate.id}",
        fmt_date(updated, tz),
    ]
    assert len(row) == len(HEADERS)
    return row
