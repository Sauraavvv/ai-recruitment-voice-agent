import uuid
from datetime import datetime

from pydantic import BaseModel


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
