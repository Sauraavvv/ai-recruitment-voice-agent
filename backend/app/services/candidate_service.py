"""Candidate rules and transactions (plan.md Module A).

Every candidate write goes through this module.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.schemas import FieldName
from app.database.models import Candidate, ConsentSource, Conversation, ScreeningStatus, User
from app.repositories import candidate_repo
from app.schemas.candidate import CandidateCreate, CandidateUpdate
from app.services import call_service, job_service
from app.services.errors import conflict, not_found, unprocessable
from app.utils.log import get_logger

logger = get_logger(__name__)
MAX_PAGE_SIZE = 100
STANDARD_FIELDS = frozenset(f.value for f in FieldName)


async def _ensure_phone_free(
    session: AsyncSession,
    phone: str,
    *,
    organization_id: uuid.UUID,
    exclude_id: uuid.UUID | None = None,
    requirement_id: uuid.UUID | None = None,
) -> None:
    existing = await candidate_repo.get_by_phone(
        session, phone, organization_id=organization_id, requirement_id=requirement_id
    )
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


async def create(session: AsyncSession, user: User, data: CandidateCreate) -> Candidate:
    """A candidate of the original job flow, in the user's organization."""
    if not data.consent_attested:
        raise unprocessable(
            "consent_required",
            "Confirm the candidate agreed to be contacted by phone about this role",
        )
    job = await job_service.resolve(session, data.job_id)
    org = user.organization_id
    await _ensure_phone_free(session, data.phone, organization_id=org)

    candidate = Candidate(
        **data.model_dump(exclude={"job_id", "consent_attested"}),
        organization_id=org,
        uploaded_by_id=user.id,
        job_id=job.id,
        consent_source=ConsentSource.MANUAL,
        consent_at=datetime.now(UTC),
    )
    session.add(candidate)
    try:
        await session.flush()
        await session.commit()
    except IntegrityError:
        # Lost a race with a concurrent insert of the same phone.
        await session.rollback()
        await _ensure_phone_free(session, data.phone, organization_id=org)
        raise
    await session.refresh(candidate)
    logger.info("candidate_created", candidate_id=str(candidate.id))
    return candidate


async def get_visible(session: AsyncSession, user: User, candidate_id: uuid.UUID) -> Candidate:
    """The candidate, if this account may see it (its organization, and the requirement's
    client); otherwise not found, the same as a candidate that doesn't exist."""
    stmt = select(Candidate).where(
        Candidate.id == candidate_id,
        Candidate.deleted_at.is_(None),
        candidate_repo.visible_to(user),
    )
    candidate = (await session.execute(stmt)).scalar_one_or_none()
    if candidate is None:
        raise not_found("candidate_not_found", "Candidate not found")
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
    call_status: str | None = None,
    requirement_id: uuid.UUID | None = None,
    viewer: User | None = None,
    client_id: uuid.UUID | None = None,
) -> tuple[list[Candidate], int]:
    return await candidate_repo.search(
        session,
        q=q,
        screening_status=screening_status,
        job_id=job_id,
        interested=interested,
        call_status=call_status,
        requirement_id=requirement_id,
        viewer=viewer,
        client_id=client_id,
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
        await _ensure_phone_free(
            session,
            changes["phone"],
            organization_id=candidate.organization_id,
            exclude_id=candidate.id,
            requirement_id=candidate.requirement_id,
        )
    if "job_id" in changes and candidate.requirement_id is not None:
        raise unprocessable(
            "requirement_candidate", "This candidate belongs to a requirement, not to a job"
        )
    if "job_id" in changes and changes["job_id"] != candidate.job_id:
        await job_service.get(session, changes["job_id"])
    if changes.get("opted_out") and not candidate.opted_out:
        changes["screening_status"] = ScreeningStatus.OPTED_OUT

    opting_out = bool(changes.get("opted_out")) and not candidate.opted_out
    for key, value in changes.items():
        setattr(candidate, key, value)
    if opting_out:
        # Same transaction (phase-09 P9-T7): nothing scheduled may dial after an opt-out
        await call_service.cancel_scheduled(session, candidate.id, reason="opted_out")
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        if "phone" in changes:
            await _ensure_phone_free(
                session,
                changes["phone"],
                organization_id=candidate.organization_id,
                exclude_id=candidate_id,
                requirement_id=candidate.requirement_id,
            )
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


async def resolve_conflict(
    session: AsyncSession,
    candidate_id: uuid.UUID,
    field: str,
    choice: str,
    *,
    user_id: uuid.UUID,
) -> Candidate:
    """Settle a data conflict from the final pass (phase-08, decided with the user).

    keep: the stored value stays. use: the other value (the final pass's, with its quote)
    replaces it. Either way the conflict is marked resolved (who, when, choice) on the field's
    meta and in that call's `final.conflicts`.
    """
    candidate = await candidate_repo.get(session, candidate_id)
    if candidate is None:
        raise not_found("candidate_not_found", "Candidate not found")
    await session.refresh(candidate, with_for_update=True)
    meta = dict(candidate.screening_field_meta or {})
    entry = dict(meta.get(field) or {})
    conflict_info = entry.get("conflict")
    if not isinstance(conflict_info, dict):
        raise conflict("no_conflict", "This field has no open conflict")

    now = datetime.now(UTC)
    standard = hasattr(Candidate, field) and field in STANDARD_FIELDS
    stored = getattr(candidate, field) if standard else entry.get("value")
    resolution = {
        "choice": choice,
        "by": str(user_id),
        "at": now.isoformat(),
        "stored_value": stored,
        "other_value": conflict_info.get("final_value"),
        "reason": conflict_info.get("reason"),
    }
    if choice == "use":
        value = conflict_info.get("final_value")
        if standard:
            setattr(candidate, field, value)
        entry["previous"] = [
            *(entry.get("previous") or []),
            {"value": stored, "raw_text": entry.get("raw_text"), "seq": entry.get("seq")},
        ]
        entry.update(
            value=value,
            raw_text=conflict_info.get("quote"),
            seq=conflict_info.get("seq"),
            status="answered",
            source="recruiter",
        )
    entry["conflict"] = None
    entry["conflict_resolution"] = resolution
    meta[field] = entry
    candidate.screening_field_meta = meta

    # The call's own record of the conflict
    attempt_id = entry.get("call_attempt_id")
    if attempt_id:
        conv = (
            await session.execute(
                select(Conversation)
                .where(Conversation.call_attempt_id == uuid.UUID(str(attempt_id)))
                .with_for_update()
            )
        ).scalar_one_or_none()
        final = dict((conv.extracted_data or {}).get("final") or {}) if conv else {}
        conflicts = dict(final.get("conflicts") or {})
        if conv is not None and field in conflicts:
            conflicts[field] = {**(conflicts[field] or {}), "resolved": resolution}
            final["conflicts"] = conflicts
            conv.extracted_data = dict(conv.extracted_data or {}) | {"final": final}

    await session.commit()
    await session.refresh(candidate)
    logger.info(
        "conflict_resolved",
        candidate_id=str(candidate.id),
        field=field,
        choice=choice,
        user_id=str(user_id),
    )
    return candidate
