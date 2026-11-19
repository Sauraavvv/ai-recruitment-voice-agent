import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class SheetsStatus(BaseModel):
    configured: bool
    tab: str
    # ok: last sync worked | degraded: temporary failures, retrying | error: needs fixing
    # (permission, wrong sheet, header changed) | unknown: nothing synced yet
    state: Literal["ok", "degraded", "error", "unknown", "not_configured"]
    message: str | None
    reachable: bool | None  # live check (cached for a minute); None when not configured
    header: Literal["ok", "empty", "mismatch", "unknown"] | None
    service_account_email: str | None
    last_success_at: datetime | None
    last_error_at: datetime | None
    pending_candidates: int
    failed_candidates: int
    checked_at: datetime | None


class ManualSyncResult(BaseModel):
    candidate_id: uuid.UUID
    sync_log_id: uuid.UUID
    sync_status: str
    queued: bool
