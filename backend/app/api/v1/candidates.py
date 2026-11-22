import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request, status

from app.api.deps import CurrentUser, EffectiveSettingsDep, SessionDep, SettingsDep
from app.api.responses import ok
from app.api.v1.calls import voice_ready
from app.database.models import CallStatus, ScreeningStatus
from app.schemas.candidate import (
    CandidateCreate,
    CandidateListItem,
    CandidateOut,
    CandidateOverview,
    CandidateSort,
    CandidateUpdate,
    ConflictResolution,
)
from app.schemas.common import DataResponse, PageResponse
from app.services import (
    call_service,
    candidate_service,
    candidate_view_service,
    client_service,
    requirement_service,
)

# The latest call's status, or not_called (never called)
CALL_STATUS_PATTERN = "^(" + "|".join([*(s.value for s in CallStatus), "not_called"]) + ")$"

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.post("", response_model=DataResponse[CandidateOut], status_code=status.HTTP_201_CREATED)
async def create_candidate(
    body: CandidateCreate, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    candidate = await candidate_service.create(session, user, body)
    return ok(candidate)


@router.get("", response_model=PageResponse[CandidateListItem])
async def list_candidates(
    user: CurrentUser,
    session: SessionDep,
    settings: EffectiveSettingsDep,
    request: Request,
    q: Annotated[str | None, Query(max_length=200, description="Name, phone or email")] = None,
    screening_status: ScreeningStatus | None = None,
    call_status: Annotated[
        str | None,
        Query(
            pattern=CALL_STATUS_PATTERN,
            description="Status of the latest call; not_called = never called",
        ),
    ] = None,
    job_id: uuid.UUID | None = None,
    requirement_id: Annotated[
        uuid.UUID | None, Query(description="Only this requirement's candidates")
    ] = None,
    client_id: Annotated[
        uuid.UUID | None, Query(description="Only the candidates of this client's jobs")
    ] = None,
    interested: bool | None = None,
    sort: CandidateSort = "-created_at",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    """Rows include `eligibility` (can_call + why not) and the latest call. A requirement's
    candidates are listed only for whoever can see the requirement's client."""
    if requirement_id is not None:
        await requirement_service.get_requirement(session, user, requirement_id)  # else 404
    if client_id is not None:
        await client_service.get_client(session, user, client_id)  # else 404
    items, total = await candidate_service.search(
        session,
        q=q,
        screening_status=screening_status,
        call_status=call_status,
        job_id=job_id,
        requirement_id=requirement_id,
        client_id=client_id,
        viewer=user,
        interested=interested,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    rows = await candidate_view_service.list_rows(
        session, items, settings, voice_ready=voice_ready(request, settings)
    )
    return ok(rows, {"page": page, "page_size": page_size, "total": total})


@router.get("/{candidate_id}", response_model=DataResponse[CandidateOut])
async def get_candidate(
    candidate_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    return ok(await candidate_service.get_visible(session, user, candidate_id))


@router.patch("/{candidate_id}", response_model=DataResponse[CandidateOut])
async def update_candidate(
    candidate_id: uuid.UUID,
    body: CandidateUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    await candidate_service.get_visible(session, user, candidate_id)  # else 404
    candidate = await candidate_service.update(session, candidate_id, body)
    return ok(candidate)


@router.delete("/{candidate_id}", response_model=DataResponse[None])
async def delete_candidate(
    candidate_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    await candidate_service.get_visible(session, user, candidate_id)  # else 404
    await candidate_service.soft_delete(session, candidate_id)
    return ok(None)


@router.get("/{candidate_id}/overview", response_model=DataResponse[CandidateOverview])
async def candidate_overview(
    candidate_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: EffectiveSettingsDep,
    request: Request,
) -> dict[str, Any]:
    """Eligibility, the summary, open conflicts and the retry status."""
    candidate = await candidate_service.get_visible(session, user, candidate_id)
    eligibility = await call_service.eligibility_for(
        session, [candidate], settings, voice_ready=voice_ready(request, settings)
    )
    return ok(
        {
            "eligibility": call_service.eligibility_dict(eligibility[candidate.id]),
            "summary": await candidate_view_service.summary(session, candidate.id),
            "conflicts": candidate_view_service.open_conflicts(candidate),
            "retry_status": await candidate_view_service.retry_status_for(
                session, candidate.id, settings
            ),
        }
    )


@router.post("/{candidate_id}/conflicts/{field}/resolve", response_model=DataResponse[CandidateOut])
async def resolve_conflict(
    candidate_id: uuid.UUID,
    field: Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")],
    body: ConflictResolution,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUser,
) -> dict[str, Any]:
    """Keep the stored value or use the other one."""
    await candidate_service.get_visible(session, user, candidate_id)  # else 404
    candidate = await candidate_service.resolve_conflict(
        session, candidate_id, field, body.choice, user_id=user.id
    )
    return ok(candidate)
