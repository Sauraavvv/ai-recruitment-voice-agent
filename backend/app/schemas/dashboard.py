import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.database.models.enums import CallEndReason, CallStatus
from app.schemas.candidate import Conflict


class DashboardKpis(BaseModel):
    candidates_total: int
    screened: int
    interested: int
    interested_rate: float | None  # interested / screened
    opted_out: int
    calls_total: int
    calls_today: int
    calls_connected: int
    connect_rate: float | None  # connected / placed
    avg_call_seconds: int | None  # over connected calls


class DashboardFunnel(BaseModel):
    candidates: int
    called: int
    connected: int
    screened: int
    interested: int


class CallsOnDay(BaseModel):
    date: str  # YYYY-MM-DD in APP_TIMEZONE
    total: int
    connected: int


class LiveCall(BaseModel):
    call_attempt_id: uuid.UUID
    candidate_id: uuid.UUID
    candidate_name: str
    applied_role: str
    call_status: str
    started_at: datetime


class TranscriptLine(BaseModel):
    speaker: str | None
    text: str | None


class LatestConversation(BaseModel):
    call_attempt_id: uuid.UUID
    candidate_id: uuid.UUID
    candidate_name: str
    ended_at: datetime
    duration_seconds: int | None
    turns: int
    transcript: list[TranscriptLine]


class InterviewAvailability(BaseModel):
    candidate_id: uuid.UUID
    candidate_name: str
    availability: str
    notice_period: str | None
    updated_at: datetime


class DashboardSummary(BaseModel):
    kpis: DashboardKpis
    funnel: DashboardFunnel
    calls_by_day: list[CallsOnDay]
    outcomes: dict[str, int]  # call_status → attempts
    live_calls: list[LiveCall]
    latest_conversation: LatestConversation | None
    interview_availability: list[InterviewAvailability]
    generated_at: datetime


class DashboardStats(BaseModel):
    range: str
    total_candidates: int
    calls_completed: int
    calls_pending: int
    calls_in_progress: int
    unanswered_calls: int
    failed_calls: int
    interested_candidates: int
    screening_completed: int
    scheduled_retries: int
    definitions: dict[str, str]  # tooltip text per metric
    generated_at: datetime


class ActivityItem(BaseModel):
    call_attempt_id: uuid.UUID
    candidate_id: uuid.UUID
    candidate_name: str
    attempt_number: int
    call_status: CallStatus
    end_reason: CallEndReason | None
    at: datetime


AttentionReason = Literal[
    "callback_due",
    "data_conflict",
    "unanswered_question",
    "vague_callback",
    "callback_not_scheduled",  # Phase 9: callback limit reached or too far ahead
    "technical_failure",
    "partially_completed",
    "wrong_person",
    "attempts_exhausted",
]


class AttentionItem(BaseModel):
    candidate_id: uuid.UUID
    candidate_name: str
    reason: AttentionReason
    at: datetime | None
    call_attempt_id: uuid.UUID | None
    detail: str | None
    conflict: Conflict | None  # data_conflict: both values and the quotes


class QuickStartCandidate(BaseModel):
    candidate_id: uuid.UUID
    name: str
    applied_role: str


class QuickStart(BaseModel):
    """Eligible candidates never called (for "Call new candidates")."""

    candidates: list[QuickStartCandidate]
    total: int  # all eligible never-called candidates (the dialog starts at most `limit`)
    limit: int
    calling_now: bool  # inside the calling window and not paused
    blocked_reason: str | None  # why nobody can be called right now
    blocked_message: str | None
    max_concurrent_calls: int
    live_calls: int
