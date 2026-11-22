"""Version 1 API router.

Every route requires a logged-in user except POST /auth/login and POST /auth/signup.
State-changing requests must also come from the frontend origin (CSRF guard). Telephony webhooks
and the media stream have their own router (api/v1/webhooks.py) with a URL token instead of a
session.
"""

from fastapi import APIRouter, Depends

from app.api.deps import require_user, verify_origin
from app.api.v1 import (
    auth,
    calls,
    candidates,
    clients,
    dashboard,
    imports,
    jobs,
    requirements,
    settings,
    team,
    telephonic,
)

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(verify_origin)])

api_router.include_router(auth.public_router)

protected = APIRouter(dependencies=[Depends(require_user)])
protected.include_router(auth.router)
protected.include_router(imports.router)  # before candidates: /candidates/import/...
protected.include_router(candidates.router)
protected.include_router(clients.router)
protected.include_router(requirements.router)
protected.include_router(telephonic.router)
protected.include_router(jobs.router)
protected.include_router(calls.router)
protected.include_router(dashboard.router)
protected.include_router(settings.router)
protected.include_router(team.router)
api_router.include_router(protected)
