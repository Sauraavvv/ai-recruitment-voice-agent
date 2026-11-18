import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.database.models.enums import CallAttemptType, CallEndReason, CallStatus


class StartCallsRequest(BaseModel):
    candidate_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


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
    recording_url: str | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
