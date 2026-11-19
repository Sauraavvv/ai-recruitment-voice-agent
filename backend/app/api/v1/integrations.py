"""Google Sheets integration endpoints (plan.md §6, phase-07 P7-T10, phase-08 Settings page).

Every recruiter can see the status, sync a candidate and re-sync everyone. Only an admin can
point the sync at another sheet (candidates' personal data goes there).
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, status

from app.api.deps import (
    AdminUser,
    CurrentUser,
    EffectiveSettingsDep,
    RedisDep,
    SessionDep,
    SettingsDep,
)
from app.api.responses import ok
from app.config import Settings
from app.database.models import UserRole
from app.schemas.common import DataResponse
from app.schemas.integrations import (
    BackfillResult,
    ManualSyncResult,
    SheetAccessCheck,
    SheetChange,
    SheetsStatus,
)
from app.services import candidate_service, settings_service, sync_service
from app.services.errors import conflict, unprocessable
from app.services.sheets_service import SheetsService
from app.utils.log import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/integrations/google-sheets", tags=["integrations"])
CHECK_TTL_S = 60


def sheet_url(sheet_id: str | None) -> str | None:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit" if sheet_id else None


def _sheets(request: Request, settings: Settings) -> SheetsService:
    service: SheetsService | None = getattr(request.app.state, "sheets", None)
    if service is None:
        service = SheetsService(settings)
        request.app.state.sheets = service
    return service.configure(settings)


async def sheets_status_body(
    request: Request,
    session: Any,
    redis: Any,
    settings: Settings,
    *,
    env: Settings,
    refresh: bool = False,
    can_edit: bool = False,
) -> dict[str, Any]:
    """The status card (also used by the Settings page's provider list)."""
    counts = await sync_service.counts(session)
    stored = await sync_service.get_status(redis)
    _, sheet = await settings_service.load(session, env)
    body: dict[str, Any] = {
        "configured": settings.sheets_configured,
        "tab": settings.google_sheet_tab,
        "sheet_id": settings.google_sheet_id,
        "sheet_url": sheet_url(settings.google_sheet_id),
        "sheet_source": "settings" if sheet.sheet_id else ("env" if env.google_sheet_id else None),
        "sheet_changed_at": sheet.changed_at,
        "can_edit": can_edit,
        "key_configured": bool(settings.google_service_account_json),
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
            message="No service account key (GOOGLE_SERVICE_ACCOUNT_JSON)"
            if not settings.google_service_account_json
            else "No sheet chosen yet",
        )
        return body

    async def cached_check() -> dict[str, Any] | None:
        raw = await redis.get(sync_service.CHECK_CACHE_KEY)
        found = json.loads(raw) if raw else None
        return found if found and found.get("sheet_id") == settings.google_sheet_id else None

    check = None if refresh else await cached_check()
    if check is None:
        service = _sheets(request, settings)
        started = datetime.now(UTC).isoformat()
        # One live check at a time; a request that waited reuses the result it waited for
        async with service.lock:
            check = await cached_check()
            if check is None or (refresh and check["checked_at"] < started):
                result = await service.check_unlocked()
                check = {
                    "sheet_id": settings.google_sheet_id,
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
    return body


@router.get("/status", response_model=DataResponse[SheetsStatus])
async def sheets_status(
    request: Request,
    session: SessionDep,
    redis: RedisDep,
    settings: EffectiveSettingsDep,
    env: SettingsDep,
    user: CurrentUser,
    refresh: bool = False,
) -> dict[str, Any]:
    """Configured, reachable, header ok, last success, pending and failed counts."""
    return ok(
        await sheets_status_body(
            request,
            session,
            redis,
            settings,
            env=env,
            refresh=refresh,
            can_edit=user.role == UserRole.ADMIN,
        )
    )


@router.post(
    "/sync/{candidate_id}",
    response_model=DataResponse[ManualSyncResult],
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_candidate(
    candidate_id: uuid.UUID, session: SessionDep, settings: EffectiveSettingsDep
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


@router.post(
    "/backfill", response_model=DataResponse[BackfillResult], status_code=status.HTTP_202_ACCEPTED
)
async def backfill(session: SessionDep, settings: EffectiveSettingsDep) -> dict[str, Any]:
    """ "Sync all": queue every active candidate's row."""
    if not settings.sheets_configured:
        raise conflict("sheets_not_configured", "Google Sheets is not configured")
    queued = await sync_service.backfill(session)
    return ok({"queued_candidates": queued, "queued": await sync_service.request_sync(settings)})


async def _check_sheet(
    request: Request, settings: Settings, body: SheetChange
) -> tuple[str, str, SheetAccessCheck]:
    sheet_id = settings_service.parse_sheet_link(body.link)
    if sheet_id is None:
        raise unprocessable(
            "sheet_link_invalid",
            "Paste the sheet's link (https://docs.google.com/spreadsheets/d/…) or its id",
        )
    if not settings.google_service_account_json:
        raise conflict("sheets_key_missing", "No service account key (GOOGLE_SERVICE_ACCOUNT_JSON)")
    tab = (body.tab or "").strip() or settings.google_sheet_tab
    trial = settings.model_copy(update={"google_sheet_id": sheet_id, "google_sheet_tab": tab})
    result = await SheetsService(trial).check()  # its own client: the live one stays as it is
    check = SheetAccessCheck(
        sheet_id=sheet_id,
        sheet_url=sheet_url(sheet_id) or "",
        tab=tab,
        reachable=result.reachable,
        header=result.header,
        message=result.message,
        service_account_email=result.service_email,
        can_save=result.reachable and result.header in ("ok", "empty"),
    )
    return sheet_id, tab, check


@router.post("/check", response_model=DataResponse[SheetAccessCheck])
async def check_sheet(
    body: SheetChange, request: Request, settings: EffectiveSettingsDep, admin: AdminUser
) -> dict[str, Any]:
    """Admin: can the service account edit this sheet, and is its header ours or empty?"""
    _, _, check = await _check_sheet(request, settings, body)
    return ok(check)


@router.put("/sheet", response_model=DataResponse[SheetAccessCheck])
async def change_sheet(
    body: SheetChange,
    request: Request,
    session: SessionDep,
    redis: RedisDep,
    settings: EffectiveSettingsDep,
    admin: AdminUser,
) -> dict[str, Any]:
    """Admin: copy candidates to another sheet from now on. Checked first; then every active
    candidate is queued so the new sheet is filled. The old sheet keeps its rows."""
    sheet_id, tab, check = await _check_sheet(request, settings, body)
    if not check.can_save:
        raise conflict(
            "sheet_not_usable",
            check.message or "The service account can't use this sheet",
            check.model_dump(mode="json"),
        )
    previous = settings.google_sheet_id
    await settings_service.update_sheet(
        session,
        sheet_id=sheet_id,
        tab=(body.tab or "").strip() or None,
        user_id=admin.id,
        now=datetime.now(UTC).isoformat(),
    )
    await redis.delete(sync_service.CHECK_CACHE_KEY)
    await sync_service.set_status(redis, state="unknown", message=None)
    queued = await sync_service.backfill(session)
    new_settings = settings.model_copy(
        update={"google_sheet_id": sheet_id, "google_sheet_tab": tab}
    )
    await sync_service.request_sync(new_settings)
    logger.info(
        "sheet_switched",
        user_id=str(admin.id),
        previous_sheet_id=previous,
        sheet_id=sheet_id,
        queued_candidates=queued,
    )
    return ok(check)
