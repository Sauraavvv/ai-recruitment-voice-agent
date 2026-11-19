import uuid
from typing import Any

from fastapi import APIRouter, status

from app.api.deps import SessionDep
from app.api.responses import ok
from app.repositories import job_repo
from app.schemas.common import DataResponse
from app.schemas.job import (
    DefaultQuestionsOut,
    DefaultQuestionsUpdate,
    JobCreate,
    JobOut,
    JobUpdate,
)
from app.schemas.job import ScreeningQuestion as ScreeningQuestionSchema
from app.services import default_questions_service, job_service

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=DataResponse[list[JobOut]])
async def list_jobs(session: SessionDep) -> dict[str, Any]:
    return ok(await job_service.list_jobs(session))


@router.get(
    "/default-screening-questions",
    response_model=DataResponse[list[ScreeningQuestionSchema]],
)
async def default_questions(session: SessionDep) -> dict[str, Any]:
    return ok(await default_questions_service.get(session))


@router.put(
    "/default-screening-questions",
    response_model=DataResponse[DefaultQuestionsOut],
)
async def update_default_questions(
    body: DefaultQuestionsUpdate, session: SessionDep
) -> dict[str, Any]:
    """Replace the default questions (reword, reorder, remove, add).

    Jobs still asking exactly the old defaults, in any order, switch to the new list."""
    questions, updated = await default_questions_service.update(session, body.questions)
    return ok(DefaultQuestionsOut(questions=questions, jobs_updated=updated))


@router.delete(
    "/default-screening-questions",
    response_model=DataResponse[DefaultQuestionsOut],
)
async def reset_default_questions(session: SessionDep) -> dict[str, Any]:
    """Restore the ten original questions."""
    questions, updated = await default_questions_service.reset(session)
    return ok(DefaultQuestionsOut(questions=questions, jobs_updated=updated))


@router.post("", response_model=DataResponse[JobOut], status_code=status.HTTP_201_CREATED)
async def create_job(body: JobCreate, session: SessionDep) -> dict[str, Any]:
    return ok(await job_service.create(session, body))


@router.get("/active", response_model=DataResponse[JobOut | None])
async def active_job(session: SessionDep) -> dict[str, Any]:
    return ok(await job_repo.get_active(session))


@router.get("/{job_id}", response_model=DataResponse[JobOut])
async def get_job(job_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    return ok(await job_service.get(session, job_id))


@router.patch("/{job_id}", response_model=DataResponse[JobOut])
async def update_job(job_id: uuid.UUID, body: JobUpdate, session: SessionDep) -> dict[str, Any]:
    return ok(await job_service.update(session, job_id, body))


@router.post("/{job_id}/activate", response_model=DataResponse[JobOut])
async def activate_job(job_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    return ok(await job_service.activate(session, job_id))
