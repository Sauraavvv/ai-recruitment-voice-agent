import uuid
from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.database.models.enums import CallAttemptType, CallEndReason, CallStatus


class StartCallsRequest(BaseModel):
    candidate_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    # True: only check who could be called (the confirmation dialog), queue nothing
    dry_run: bool = False


class StartCallError(BaseModel):
    code: str
    message: str


class StartCallResult(BaseModel):
    candidate_id: uuid.UUID
    ok: bool
    call_attempt_id: uuid.UUID | None
    error: StartCallError | None


class CallAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    candidate_id: uuid.UUID
    attempt_number: int
    attempt_type: CallAttemptType
    provider: str
    provider_call_id: str | None
    provider_status: str | None
    call_status: CallStatus
    end_reason: CallEndReason | None
    start_time: datetime | None
    end_time: datetime | None
    duration_seconds: int | None
    # The provider's recording link never reaches the browser (phase-08 §9): only whether
    # there is one. Playback would go through an authenticated backend proxy.
    has_recording: bool = Field(
        default=False, validation_alias=AliasChoices("has_recording", "recording_url")
    )
    failure_reason: str | None
    next_retry_at: datetime | None  # retry or callback time (Phase 9)
    created_at: datetime
    updated_at: datetime

    @field_validator("has_recording", mode="before")
    @classmethod
    def _present(cls, value: object) -> bool:
        return bool(value)


class CallListItem(CallAttemptOut):
    candidate_name: str
    applied_role: str
    has_transcript: bool


class TranscriptEntry(BaseModel):
    seq: int | None
    speaker: str  # assistant | candidate
    text: str
    timestamp: datetime | None
    interrupted: bool = False
    heard_text: str | None = None  # what the candidate heard before interrupting


class CallTranscript(BaseModel):
    call_attempt_id: uuid.UUID
    candidate_id: uuid.UUID
    attempt_number: int
    call_status: CallStatus
    end_reason: CallEndReason | None
    start_time: datetime | None
    duration_seconds: int | None
    entries: list[TranscriptEntry]
    summary: str | None
    finalized: bool
    voice_engine: str  # pipeline | realtime (the engine that ran this call)
    estimated_cost_usd: float | None  # realtime calls: from the model's token usage


class HangupResult(BaseModel):
    call_attempt_id: uuid.UUID
    ending: bool  # the agent is saying its closing line and will hang up
