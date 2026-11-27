"""Settings page (phase-08 §5.4): organization, agent introduction, calling preferences, retry
configuration, the global pause, and provider status. No secret value is ever returned."""

from typing import Any

from fastapi import APIRouter, Request

from app.agent.prompts import CandidateContext, JobConfig, introduction
from app.api.deps import AdminUser, RedisDep, SessionDep, SettingsDep
from app.api.responses import AppError, ok
from app.config import Settings
from app.schemas.common import DataResponse
from app.schemas.settings import SettingsOut, StatusOut
from app.services import call_service, job_service, provider_status_service, settings_service
from app.services.settings_service import GeneralSettings, GeneralUpdate

router = APIRouter(prefix="/settings", tags=["settings"])
SAMPLE_FIRST_NAME = "Asha"


async def _body(session: Any, env: Settings, general: GeneralSettings) -> dict[str, Any]:
    effective = settings_service.apply(env, general)
    try:
        job = await job_service.get_active(session)
        company, title = job.company_name, job.job_title
    except AppError:
        company, title = "your company", "open"  # no active job yet
    job_config = JobConfig.from_dict(
        {
            "job_title": title,
            "company_name": company,
            "introduction_template": general.agent_introduction,
            "organization": general.organization_name,
        }
    )
    text = introduction(CandidateContext(name=SAMPLE_FIRST_NAME), job_config)
    return {
        "general": general,
        "limits": {
            "max_concurrent_calls": env.max_concurrent_calls,
            "timezone": env.app_timezone,
            "calling_enabled_env": env.calling_enabled,
            "voice_engine_env": env.voice_engine,
            "realtime_model": env.openai_realtime_model,
        },
        "introduction": {
            "text": text,
            "sample_first_name": SAMPLE_FIRST_NAME,
            "company": company,
            "job_title": title,
            "organization": general.organization_name,
            "built_in": general.agent_introduction is None,
        },
        "calling_now": effective.calling_enabled and call_service.in_calling_window(effective),
    }


@router.get("", response_model=DataResponse[SettingsOut])
async def get_settings_page(session: SessionDep, env: SettingsDep) -> dict[str, Any]:
    """Readable by every user: the start-calls dialog shows the calling hours from it."""
    general = await settings_service.load(session, env)
    return ok(await _body(session, env, general))


@router.patch("", response_model=DataResponse[SettingsOut])
async def update_settings(
    body: GeneralUpdate, session: SessionDep, env: SettingsDep, user: AdminUser
) -> dict[str, Any]:
    """Partial update (super admins only); each section is validated. Changes are logged with
    the user id."""
    general = await settings_service.update_general(session, env, body, user_id=user.id)
    return ok(await _body(session, env, general))


@router.get("/status", response_model=DataResponse[StatusOut])
async def provider_status(
    request: Request,
    session: SessionDep,
    redis: RedisDep,
    env: SettingsDep,
    _admin: AdminUser,
    refresh: bool = False,
) -> dict[str, Any]:
    """Per provider (super admins only): configured, reachable, last checked, message. Cached
    for 60 s."""
    effective = await settings_service.effective(session, env)
    providers = await provider_status_service.all_statuses(
        redis, effective, tts=getattr(request.app.state, "tts", None), refresh=refresh
    )
    return ok({"providers": providers})
