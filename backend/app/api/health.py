"""Liveness and readiness endpoints.

Provider connectivity (OpenAI, Deepgram, Exotel, Sheets) is deliberately not part of readiness;
it belongs to /api/v1/settings/status (Phase 8) so a provider outage never restarts the backend.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.responses import ok
from app.config import Settings, get_settings
from app.database.connection import check_database
from app.utils.redis import check_redis, check_worker_heartbeat

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
