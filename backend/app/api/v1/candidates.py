import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, status

from app.api.deps import SessionDep, SettingsDep
from app.api.responses import ok
from app.database.models import ScreeningStatus
from app.schemas.candidate import CandidateCreate, CandidateOut, CandidateSort, CandidateUpdate
from app.schemas.common import DataResponse, PageResponse
from app.services import candidate_service, sync_service

router = APIRouter(prefix="/candidates", tags=["candidates"])


@router.post("", response_model=DataResponse[CandidateOut], status_code=status.HTTP_201_CREATED)
async def create_candidate(
    body: CandidateCreate, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    candidate = await candidate_service.create(session, body)
    await sync_service.request_sync(settings)
    return ok(candidate)


@router.get("", response_model=PageResponse[CandidateOut])
async def list_candidates(
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=200, description="Name, phone or email")] = None,
    screening_status: ScreeningStatus | None = None,
    job_id: uuid.UUID | None = None,
    interested: bool | None = None,
    sort: CandidateSort = "-created_at",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    items, total = await candidate_service.search(
        session,
        q=q,
        screening_status=screening_status,
        job_id=job_id,
        interested=interested,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return ok(items, {"page": page, "page_size": page_size, "total": total})


@router.get("/{candidate_id}", response_model=DataResponse[CandidateOut])
async def get_candidate(candidate_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    return ok(await candidate_service.get(session, candidate_id))


@router.patch("/{candidate_id}", response_model=DataResponse[CandidateOut])
async def update_candidate(
    candidate_id: uuid.UUID, body: CandidateUpdate, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    candidate = await candidate_service.update(session, candidate_id, body)
    await sync_service.request_sync(settings)
    return ok(candidate)


@router.delete("/{candidate_id}", response_model=DataResponse[None])
async def delete_candidate(candidate_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    await candidate_service.soft_delete(session, candidate_id)
    return ok(None)
