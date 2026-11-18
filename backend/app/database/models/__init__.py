"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.database.models.base import Base
from app.database.models.call_attempt import CallAttempt
from app.database.models.candidate import Candidate
from app.database.models.conversation import Conversation
from app.database.models.enums import (
    LIVE_CALL_STATUSES,
    CallAttemptType,
    CallEndReason,
    CallStatus,
    ConsentSource,
    ImportBatchStatus,
    ScreeningStatus,
    SyncStatus,
)
from app.database.models.import_batch import ImportBatch
from app.database.models.job import Job
from app.database.models.sync_log import SyncLog
from app.database.models.user import User
from app.database.models.webhook_event import WebhookEvent

__all__ = [
    "LIVE_CALL_STATUSES",
    "Base",
    "CallAttempt",
    "CallAttemptType",
    "CallEndReason",
    "CallStatus",
    "Candidate",
    "ConsentSource",
    "Conversation",
    "ImportBatch",
    "ImportBatchStatus",
    "Job",
    "ScreeningStatus",
    "SyncLog",
    "SyncStatus",
    "User",
    "WebhookEvent",
]
