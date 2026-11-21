"""Liveness and readiness endpoints.

Provider connectivity (OpenAI, Deepgram, Exotel, Sheets) is deliberately not part of readiness;
it belongs to /api/v1/settings/status (Phase 8) so a provider outage never restarts the backend.

/health/connections is the public summary of those checks for the /status page: generic names
and a state only. No provider names, messages, models or phone numbers, and no `refresh`, so
anyone can open it without learning the setup or making us call the providers more than once
a minute (the 60 s cache).
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import ok
from app.config import Settings, get_settings
from app.database.connection import check_database, get_session
from app.services import provider_status_service, settings_service
from app.utils.redis import check_redis, check_worker_heartbeat, get_redis

router = APIRouter(tags=["health"])

ComponentCheck = Callable[[], Awaitable[None]]
CHECK_TIMEOUT_SECONDS = 2.0


def get_readiness_checks() -> dict[str, ComponentCheck]:
    """Overridable in tests."""
    return {
        "database": check_database,
        "redis": check_redis,
        "worker": check_worker_heartbeat,
    }


async def _run_check(check: ComponentCheck) -> str | None:
    """Return None if healthy, otherwise a short error message (no connection details)."""
    try:
        await asyncio.wait_for(check(), timeout=CHECK_TIMEOUT_SECONDS + 0.5)
    except TimeoutError:
        return "timed out"
    except Exception as exc:
        return type(exc).__name__
    return None


@router.get("/health")
async def liveness(settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, Any]:
    return ok({"status": "ok", "version": settings.app_version})


@router.get("/health/ready")
async def readiness(
    checks: Annotated[dict[str, ComponentCheck], Depends(get_readiness_checks)],
) -> JSONResponse:
    names = list(checks)
    results = await asyncio.gather(*(_run_check(checks[name]) for name in names))

    components: dict[str, str] = {}
    errors: dict[str, str] = {}
    for name, problem in zip(names, results, strict=True):
        components[name] = "ok" if problem is None else "error"
        if problem is not None:
            errors[name] = problem

    healthy = not errors
    data: dict[str, Any] = {"status": "ok" if healthy else "error", "components": components}
    if errors:
        data["errors"] = errors
    return JSONResponse(ok(data), status_code=200 if healthy else 503)


# Public ids and names for the providers the calls depend on (never the provider's own name)
PUBLIC_NAMES = {
    "openai": ("agent", "AI agent"),
    "deepgram": ("speech", "Speech recognition"),
    "exotel": ("telephony", "Telephony"),
    "tts": ("voice", "AI voice"),
}


def _public_state(result: dict[str, Any]) -> str:
    if not result.get("configured"):
        return "not_set_up"
    return "ok" if result.get("reachable") else "problem"


@router.get("/health/connections")
async def connections(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    env: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any]:
    """Each connection's state (ok | problem | not_set_up) and when it was checked. Public."""
    effective = await settings_service.effective(session, env)
    results = await provider_status_service.all_statuses(
        redis, effective, tts=getattr(request.app.state, "tts", None), refresh=False
    )
    return ok(
        [
            {
                "name": PUBLIC_NAMES[r["name"]][0],
                "label": PUBLIC_NAMES[r["name"]][1],
                "state": _public_state(r),
                "last_checked": r["last_checked"],
            }
            for r in results
            if r["name"] in PUBLIC_NAMES
        ]
    )
