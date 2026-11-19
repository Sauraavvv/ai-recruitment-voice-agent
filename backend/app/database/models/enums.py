"""Status enumerations stored as VARCHAR + CHECK constraint (easier to extend than PG enums)."""

from enum import StrEnum


class ScreeningStatus(StrEnum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    DECLINED = "declined"
    OPTED_OUT = "opted_out"
    CALLBACK_REQUESTED = "callback_requested"
    WRONG_PERSON = "wrong_person"


class CallStatus(StrEnum):
    """plan.md Module F."""

    PENDING = "pending"
    QUEUED = "queued"
    INITIATING = "initiating"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CALLBACK_REQUESTED = "callback_requested"
    RETRY_SCHEDULED = "retry_scheduled"
    EXHAUSTED = "exhausted"


# Attempts that hold the candidate's single "live or scheduled" slot (partial unique index).
LIVE_CALL_STATUSES = (
    CallStatus.PENDING,
    CallStatus.QUEUED,
    CallStatus.INITIATING,
    CallStatus.RINGING,
    CallStatus.IN_PROGRESS,
    CallStatus.RETRY_SCHEDULED,
    CallStatus.CALLBACK_REQUESTED,
)


class CallAttemptType(StrEnum):
    INITIAL = "initial"
    MANUAL = "manual"
    RETRY = "retry"
    CALLBACK = "callback"


class CallEndReason(StrEnum):
    """Normalized reason a call attempt ended (phase-05 §5, phase-06 §5.6)."""

    NO_ANSWER = "no_answer"
    BUSY = "busy"
    INVALID_NUMBER = "invalid_number"
    CANDIDATE_HANGUP = "candidate_hangup"
    AGENT_COMPLETED = "agent_completed"
    PROVIDER_FAILED = "provider_failed"
    TECHNICAL_FAILURE = "technical_failure"
    CANCELLED = "cancelled"
    # Phase 6: how the conversation itself ended
    DECLINED = "declined"
    OPTED_OUT = "opted_out"
    CALLBACK_SCHEDULED = "callback_scheduled"
    WRONG_PERSON = "wrong_person"
    SILENCE_TIMEOUT = "silence_timeout"
    MAX_DURATION = "max_duration"
    ESCALATED = "escalated"


class SyncStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class ImportBatchStatus(StrEnum):
    PREVIEW = "preview"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"


class ConsentSource(StrEnum):
    RECRUITER_ATTESTED_IMPORT = "recruiter_attested_import"
    MANUAL = "manual"
