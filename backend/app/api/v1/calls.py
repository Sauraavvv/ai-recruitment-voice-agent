"""Call attempts (plan.md Module F). Recruiter-only; the UI comes in Phase 8."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from app.api.deps import SessionDep, SettingsDep
from app.api.responses import ok
from app.database.models import CallAttemptType, CallStatus
from app.repositories import call_repo
from app.schemas.call import CallAttemptOut, StartCallResult, StartCallsRequest
from app.schemas.common import DataResponse, PageResponse
from app.services import call_service
from app.utils.queue import enqueue_initiate_call

router = APIRouter(prefix="/calls", tags=["calls"])


@router.post(
    "/start",
    response_model=DataResponse[list[StartCallResult]],
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_calls(
    body: StartCallsRequest, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    """Queue a call per candidate. Each candidate gets its own result (ok or a reason)."""
    results = await call_service.start_calls(
        session,
        body.candidate_ids,
        settings,
        enqueue_initiate_call,
        attempt_type=CallAttemptType.MANUAL,
    )
    return ok([r.as_dict() for r in results])


@router.get("", response_model=PageResponse[CallAttemptOut])
async def list_calls(
    session: SessionDep,
    candidate_id: uuid.UUID | None = None,
    call_status: CallStatus | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    items, total = await call_repo.search(
        session,
        candidate_id=candidate_id,
        status=call_status.value if call_status else None,
        page=page,
        page_size=page_size,
    )
    return ok(items, {"page": page, "page_size": page_size, "total": total})


@router.get("/{call_attempt_id}", response_model=DataResponse[CallAttemptOut])
async def get_call(call_attempt_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    return ok(await call_service.get(session, call_attempt_id))
