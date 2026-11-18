"""Version 1 API router.

Every route requires a logged-in recruiter except POST /auth/login. State-changing requests must
also come from the frontend origin (CSRF guard). Telephony webhooks (Phase 5) will get their own
router with provider verification instead of a session.
"""

from fastapi import APIRouter, Depends

from app.api.deps import require_user, verify_origin
from app.api.v1 import auth, candidates, imports, jobs

api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(verify_origin)])

api_router.include_router(auth.public_router)

protected = APIRouter(dependencies=[Depends(require_user)])
protected.include_router(auth.router)
protected.include_router(imports.router)  # before candidates: /candidates/import/...
protected.include_router(candidates.router)
protected.include_router(jobs.router)
api_router.include_router(protected)
