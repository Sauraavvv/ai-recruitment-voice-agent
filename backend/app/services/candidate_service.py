"""Candidate rules and transactions (plan.md Module A).

Every candidate write goes through this module and adds a Sheets outbox row (sync_service) in
the same transaction; the API queues the sync after the commit.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Candidate, ConsentSource, ScreeningStatus
from app.repositories import candidate_repo
from app.schemas.candidate import CandidateCreate, CandidateUpdate
from app.services import job_service, sync_service
from app.services.errors import conflict, not_found, unprocessable
from app.utils.log import get_logger

logger = get_logger(__name__)
MAX_PAGE_SIZE = 100


async def _ensure_phone_free(
    session: AsyncSession, phone: str, *, exclude_id: uuid.UUID | None = None
) -> None:
    existing = await candidate_repo.get_by_phone(session, phone)
    if existing is None or existing.id == exclude_id:
        return
    deleted = existing.deleted_at is not None
    raise conflict(
        "duplicate_phone",
        "A deleted candidate already used this phone number"
        if deleted
        else "A candidate with this phone number already exists",
        {"existing_candidate_id": str(existing.id), "deleted": deleted},
    )


async def create(session: AsyncSession, data: CandidateCreate) -> Candidate:
    if not data.consent_attested:
        raise unprocessable(
            "consent_required",
            "Confirm the candidate agreed to be contacted by phone about this role",
        )
    job = await job_service.resolve(session, data.job_id)
    await _ensure_phone_free(session, data.phone)

    candidate = Candidate(
        **data.model_dump(exclude={"job_id", "consent_attested"}),
        job_id=job.id,
        consent_source=ConsentSource.MANUAL,
        consent_at=datetime.now(UTC),
    )
    session.add(candidate)
    try:
        await session.flush()  # the id, for the outbox row
        sync_service.record_change(session, candidate.id)
        await session.commit()
    except IntegrityError:
        # Lost a race with a concurrent insert of the same phone.
        await session.rollback()
        await _ensure_phone_free(session, data.phone)
        raise
    await session.refresh(candidate)
    logger.info("candidate_created", candidate_id=str(candidate.id))
    return candidate


async def get(session: AsyncSession, candidate_id: uuid.UUID) -> Candidate:
    candidate = await candidate_repo.get(session, candidate_id)
    if candidate is None:
        raise not_found("candidate_not_found", "Candidate not found")
    return candidate


async def search(
    session: AsyncSession,
    *,
    q: str | None = None,
    screening_status: ScreeningStatus | None = None,
    job_id: uuid.UUID | None = None,
    interested: bool | None = None,
    sort: str = "-created_at",
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[Candidate], int]:
    return await candidate_repo.search(
        session,
        q=q,
        screening_status=screening_status,
        job_id=job_id,
        interested=interested,
        sort=sort,
        page=max(page, 1),
        page_size=min(max(page_size, 1), MAX_PAGE_SIZE),
    )


async def update(
    session: AsyncSession, candidate_id: uuid.UUID, data: CandidateUpdate
) -> Candidate:
    candidate = await get(session, candidate_id)
    changes = data.model_dump(exclude_unset=True)

    if changes.get("opted_out") is False and candidate.opted_out:
        raise conflict("opt_out_irreversible", "A candidate who opted out can't be opted back in")
    if "phone" in changes and changes["phone"] != candidate.phone:
        await _ensure_phone_free(session, changes["phone"], exclude_id=candidate.id)
    if "job_id" in changes and changes["job_id"] != candidate.job_id:
        await job_service.get(session, changes["job_id"])
    if changes.get("opted_out") and not candidate.opted_out:
        changes["screening_status"] = ScreeningStatus.OPTED_OUT

    for key, value in changes.items():
        setattr(candidate, key, value)
    if changes:
        sync_service.record_change(session, candidate.id)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        if "phone" in changes:
            await _ensure_phone_free(session, changes["phone"], exclude_id=candidate_id)
        raise
    await session.refresh(candidate)
    logger.info("candidate_updated", candidate_id=str(candidate.id), fields=sorted(changes))
    return candidate


async def soft_delete(session: AsyncSession, candidate_id: uuid.UUID) -> None:
    """Hide the candidate and block future calls; call history is kept."""
    candidate = await get(session, candidate_id)
    candidate.deleted_at = datetime.now(UTC)
    await session.commit()
    logger.info("candidate_deleted", candidate_id=str(candidate_id))
