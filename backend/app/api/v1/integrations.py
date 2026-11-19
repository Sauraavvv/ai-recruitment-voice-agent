"""Google Sheets integration endpoints (plan.md §6, phase-07 P7-T10). Recruiter-only."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, status

from app.api.deps import RedisDep, SessionDep, SettingsDep
from app.api.responses import ok
from app.schemas.common import DataResponse
from app.schemas.integrations import ManualSyncResult, SheetsStatus
from app.services import candidate_service, sync_service
from app.services.errors import conflict
from app.services.sheets_service import SheetsService

router = APIRouter(prefix="/integrations/google-sheets", tags=["integrations"])
CHECK_TTL_S = 60


def _sheets(request: Request, settings: Any) -> SheetsService:
    service: SheetsService | None = getattr(request.app.state, "sheets", None)
    if service is None:
        service = SheetsService(settings)
        request.app.state.sheets = service
    return service


@router.get("/status", response_model=DataResponse[SheetsStatus])
async def sheets_status(
    request: Request,
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
    refresh: bool = False,
) -> dict[str, Any]:
    """Configured, reachable, header ok, last success, pending and failed counts."""
    counts = await sync_service.counts(session)
    stored = await sync_service.get_status(redis)
    body: dict[str, Any] = {
        "configured": settings.sheets_configured,
        "tab": settings.google_sheet_tab,
        "state": stored.get("state") or "unknown",
        "message": stored.get("message"),
        "reachable": None,
        "header": None,
        "service_account_email": None,
        "last_success_at": counts["last_success_at"] or stored.get("last_success_at"),
        "last_error_at": stored.get("error_at"),
        "pending_candidates": counts["pending_candidates"],
        "failed_candidates": counts["failed_candidates"],
        "checked_at": None,
    }
    if not settings.sheets_configured:
        body.update(
            state="not_configured",
            message="GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_SHEET_ID are not set",
        )
        return ok(body)

    cached = None if refresh else await redis.get(sync_service.CHECK_CACHE_KEY)
    if cached:
        check = json.loads(cached)
    else:
        result = await _sheets(request, settings).check()
        check = {
            "reachable": result.reachable,
            "header": result.header,
            "message": result.message,
            "service_account_email": result.service_email,
            "checked_at": datetime.now(UTC).isoformat(),
        }
        await redis.set(sync_service.CHECK_CACHE_KEY, json.dumps(check), ex=CHECK_TTL_S)
    body.update(
        reachable=check["reachable"],
        header=check["header"],
        service_account_email=check["service_account_email"],
        checked_at=check["checked_at"],
    )
    if not check["reachable"] or check["header"] == "mismatch":
        body.update(state="error", message=check["message"])
    return ok(body)


@router.post(
    "/sync/{candidate_id}",
    response_model=DataResponse[ManualSyncResult],
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_candidate(
    candidate_id: uuid.UUID, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    """Queue a sync of this candidate's row (also retries one that failed for good)."""
    if not settings.sheets_configured:
        raise conflict("sheets_not_configured", "Google Sheets is not configured")
    candidate = await candidate_service.get(session, candidate_id)
    row = sync_service.record_change(session, candidate.id)
    await session.commit()
    await session.refresh(row)
    # Not queued (Redis down): the reconciler picks the pending row up within 15 minutes
    queued = await sync_service.request_sync(settings)
    return ok(
        {
            "candidate_id": candidate.id,
            "sync_log_id": row.id,
            "sync_status": row.sync_status,
            "queued": queued,
        }
    )
