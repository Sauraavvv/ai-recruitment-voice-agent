"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.database.models.app_setting import AppSetting
from app.database.models.base import Base
from app.database.models.call_attempt import CallAttempt
from app.database.models.candidate import Candidate
from app.database.models.client import Client
from app.database.models.conversation import Conversation
from app.database.models.enums import (
    LIVE_CALL_STATUSES,
    CallAttemptType,
    CallEndReason,
    CallStatus,
    ClientStatus,
    ConsentSource,
    ImportBatchStatus,
    QuestionSetStatus,
    RequirementStatus,
    ScreeningStatus,
    SyncStatus,
    UserRole,
    WorkMode,
)
from app.database.models.import_batch import ImportBatch
from app.database.models.job import Job
from app.database.models.organization import Organization
from app.database.models.question_set import QuestionSet
from app.database.models.requirement import Requirement
from app.database.models.sync_log import SyncLog
from app.database.models.user import User
from app.database.models.webhook_event import WebhookEvent

__all__ = [
    "LIVE_CALL_STATUSES",
    "AppSetting",
    "Base",
    "CallAttempt",
    "CallAttemptType",
    "CallEndReason",
    "CallStatus",
    "Candidate",
    "Client",
    "ClientStatus",
    "ConsentSource",
    "Conversation",
    "ImportBatch",
    "ImportBatchStatus",
    "Job",
    "Organization",
    "QuestionSet",
    "QuestionSetStatus",
    "Requirement",
    "RequirementStatus",
    "ScreeningStatus",
    "SyncLog",
    "SyncStatus",
    "User",
    "UserRole",
    "WebhookEvent",
    "WorkMode",
]
