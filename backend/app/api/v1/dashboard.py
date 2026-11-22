"""Recruiter dashboard (phase-08 §5.1, §5.2): stat tiles, activity, needs attention, quick start,
plus the Phase 1 summary (charts, live calls, latest transcript)."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request

from app.api.deps import CurrentUser, EffectiveSettingsDep, RedisDep, SessionDep, SettingsDep
from app.api.responses import ok
from app.api.v1.calls import voice_ready
from app.repositories import candidate_repo
from app.schemas.common import DataResponse
from app.schemas.dashboard import (
    ActivityItem,
    AttentionItem,
    DashboardStats,
    DashboardSummary,
    QuickStart,
)
from app.services import call_service, call_slots, dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])
QUICK_START_LIMIT = 20  # phase-08 P8-T2: at most 20 calls per action
QUICK_START_SCAN = 500


@router.get("/summary", response_model=DataResponse[DashboardSummary])
async def get_summary(
    user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    return ok(await dashboard_service.summary(session, viewer=user, tz=settings.app_timezone))


@router.get("/stats", response_model=DataResponse[DashboardStats])
async def get_stats(
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    range: Annotated[Literal["today", "7d", "all"], Query()] = "all",
) -> dict[str, Any]:
    """The stat tiles; `definitions` holds each one's tooltip."""
    return ok(
        await dashboard_service.stats(session, viewer=user, tz=settings.app_timezone, range_=range)
    )


@router.get("/activity", response_model=DataResponse[list[ActivityItem]])
async def get_activity(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    return ok(await dashboard_service.activity(session, viewer=user))


@router.get("/attention", response_model=DataResponse[list[AttentionItem]])
async def get_attention(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    return ok(await dashboard_service.attention(session, viewer=user))


@router.get("/quick-start", response_model=DataResponse[QuickStart])
async def get_quick_start(
    user: CurrentUser,
    session: SessionDep,
    redis: RedisDep,
    settings: EffectiveSettingsDep,
    request: Request,
) -> dict[str, Any]:
    """Eligible candidates who were never called, oldest first (the dashboard's quick start)."""
    never_called, _ = await candidate_repo.search(
        session,
        q=None,
        screening_status=None,
        job_id=None,
        interested=None,
        call_status=candidate_repo.NOT_CALLED,
        sort="created_at",
        page=1,
        page_size=QUICK_START_SCAN,
        viewer=user,
    )
    ready = voice_ready(request, settings)
    eligibility = await call_service.eligibility_for(
        session, never_called, settings, voice_ready=ready
    )
    eligible = [c for c in never_called if eligibility[c.id] is None]
    # Why nobody can be called (pause, window, telephony, voice): the same for everyone
    blocked = None
    if never_called and not eligible:
        reasons = {eligibility[c.id] for c in never_called}
        common = {
            call_service.Ineligible.PAUSED,
            call_service.Ineligible.OUTSIDE_WINDOW,
            call_service.Ineligible.NOT_CONFIGURED,
            call_service.Ineligible.VOICE_UNAVAILABLE,
        }
        blocked = next((r for r in reasons if r in common), None)
    if blocked is None and not never_called:
        blocked = call_service.global_problem(settings)
    try:
        live = len(await call_slots.in_use(redis, size=settings.max_concurrent_calls))
    except Exception:
        live = 0
    return ok(
        {
            "candidates": [
                {"candidate_id": c.id, "name": c.name, "applied_role": c.applied_role}
                for c in eligible[:QUICK_START_LIMIT]
            ],
            "total": len(eligible),
            "limit": QUICK_START_LIMIT,
            "calling_now": settings.calling_enabled and call_service.in_calling_window(settings),
            "blocked_reason": blocked,
            "blocked_message": call_service.INELIGIBLE_MESSAGES.get(blocked or "") or None,
            "max_concurrent_calls": settings.max_concurrent_calls,
            "live_calls": live,
        }
    )
