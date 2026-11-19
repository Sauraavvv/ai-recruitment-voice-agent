"""Recruiter dashboard: KPIs, charts and live calls in one request."""

from typing import Any

from fastapi import APIRouter

from app.api.deps import SessionDep, SettingsDep
from app.api.responses import ok
from app.schemas.common import DataResponse
from app.schemas.dashboard import DashboardSummary
from app.services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=DataResponse[DashboardSummary])
async def get_summary(session: SessionDep, settings: SettingsDep) -> dict[str, Any]:
    return ok(await dashboard_service.summary(session, tz=settings.app_timezone))
