"""Job configuration (plan.md Module B). One active job for the MVP."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Job
from app.repositories import job_repo
from app.schemas.job import JobCreate, JobUpdate
from app.services import default_questions_service
from app.services.errors import not_found, unprocessable


async def get(session: AsyncSession, job_id: uuid.UUID) -> Job:
    job = await job_repo.get(session, job_id)
    if job is None:
        raise not_found("job_not_found", "Job not found")
    return job


async def get_active(session: AsyncSession) -> Job:
    job = await job_repo.get_active(session)
    if job is None:
        raise unprocessable("no_active_job", "No active job. Create one in Settings → Job first.")
    return job


async def resolve(session: AsyncSession, job_id: uuid.UUID | None) -> Job:
    """The given job, or the active job when none is given."""
    return await get(session, job_id) if job_id else await get_active(session)


async def list_jobs(session: AsyncSession) -> list[Job]:
    return await job_repo.list_all(session)


async def create(session: AsyncSession, data: JobCreate, organization_id: uuid.UUID) -> Job:
    """A job of the original flow; without questions of its own it asks the creating
    company's defaults."""
    questions = data.screening_questions or await default_questions_service.get(
        session, organization_id
    )
    job = Job(
        **data.model_dump(exclude={"screening_questions"}),
        screening_questions=[q.model_dump(exclude_none=True) for q in questions],
        # The first job becomes the active one so the app is usable straight away.
        is_active=await job_repo.get_active(session) is None,
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def update(session: AsyncSession, job_id: uuid.UUID, data: JobUpdate) -> Job:
    job = await get(session, job_id)
    # Every job field is required, so null means "leave unchanged".
    changes = data.model_dump(exclude_unset=True, exclude_none=True)
    if data.screening_questions is not None:
        changes["screening_questions"] = [
            q.model_dump(exclude_none=True) for q in data.screening_questions
        ]
    for key, value in changes.items():
        setattr(job, key, value)
    await session.commit()
    await session.refresh(job)
    return job


async def activate(session: AsyncSession, job_id: uuid.UUID) -> Job:
    """Make this the only active job, in one transaction."""
    job = await get(session, job_id)
    if not job.is_active:
        await job_repo.deactivate_all(session)
        await session.flush()
        job.is_active = True
    await session.commit()
    await session.refresh(job)
    return job
