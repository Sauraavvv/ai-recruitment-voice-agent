import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SheetsStatus(BaseModel):
    configured: bool
    tab: str
    sheet_id: str | None
    sheet_url: str | None
    sheet_source: Literal["settings", "env"] | None  # Settings page, or GOOGLE_SHEET_ID
    sheet_changed_at: str | None
    can_edit: bool  # the current user is an admin
    key_configured: bool  # GOOGLE_SERVICE_ACCOUNT_JSON is set (the key itself is never sent)
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


class BackfillResult(BaseModel):
    queued_candidates: int
    queued: bool


class SheetChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link: str = Field(min_length=1, max_length=2000, description="Sheet link or id")
    tab: str | None = Field(default=None, max_length=100)


class SheetAccessCheck(BaseModel):
    sheet_id: str
    sheet_url: str
    tab: str
    reachable: bool
    header: Literal["ok", "empty", "mismatch", "unknown"]
    message: str | None
    service_account_email: str | None
    can_save: bool  # reachable and the header is ours or empty
