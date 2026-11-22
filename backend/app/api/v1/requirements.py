"""Requirements (openings) at a client: list and add under a client, view and edit one."""

import uuid
from typing import Any

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, SessionDep
from app.api.responses import ok
from app.schemas.common import DataResponse
from app.schemas.requirement import (
    JobListItem,
    RequirementCreate,
    RequirementListItem,
    RequirementOut,
    RequirementUpdate,
    ScreeningCallQuestion,
)
from app.services import requirement_service, screening_job

router = APIRouter(tags=["requirements"])


@router.get(
    "/clients/{client_id}/requirements", response_model=DataResponse[list[RequirementListItem]]
)
async def list_requirements(
    client_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    """Open first, then on hold, filled and closed; newest first within each. Each row carries
    its candidates, how many were called and how many are interested."""
    rows = await requirement_service.list_for_client(session, user, client_id)
    counts = await requirement_service.candidate_counts(session, user, [r.id for r in rows])
    items = []
    for r in rows:
        total, called, interested = counts.get(r.id, (0, 0, 0))
        items.append(
            RequirementListItem.model_validate(r).model_copy(
                update={"candidates": total, "called": called, "interested": interested}
            )
        )
    return ok(items)


@router.get("/requirements", response_model=DataResponse[list[JobListItem]])
async def list_jobs(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    """Every requirement (job) across the clients this account sees, with its client and its
    screening numbers. Open first, then on hold, filled and closed; newest first."""
    rows = await requirement_service.list_all(session, user)
    counts = await requirement_service.candidate_counts(session, user, [r.id for r, _ in rows])
    items = []
    for r, client in rows:
        total, called, interested = counts.get(r.id, (0, 0, 0))
        items.append(
            JobListItem.model_validate(r).model_copy(
                update={
                    "candidates": total,
                    "called": called,
                    "interested": interested,
                    "client_name": client.name,
                    "client_status": client.status,
                }
            )
        )
    return ok(items)


@router.post(
    "/clients/{client_id}/requirements",
    response_model=DataResponse[RequirementOut],
    status_code=status.HTTP_201_CREATED,
)
async def create_requirement(
    client_id: uuid.UUID, body: RequirementCreate, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    requirement = await requirement_service.create_requirement(session, user, client_id, body)
    return ok(RequirementOut.model_validate(requirement))


@router.get("/requirements/{requirement_id}", response_model=DataResponse[RequirementOut])
async def get_requirement(
    requirement_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    requirement, _client = await requirement_service.get_requirement(session, user, requirement_id)
    return ok(RequirementOut.model_validate(requirement))


@router.patch("/requirements/{requirement_id}", response_model=DataResponse[RequirementOut])
async def update_requirement(
    requirement_id: uuid.UUID, body: RequirementUpdate, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    requirement = await requirement_service.update_requirement(session, user, requirement_id, body)
    return ok(RequirementOut.model_validate(requirement))


@router.get(
    "/requirements/{requirement_id}/screening-questions",
    response_model=DataResponse[list[ScreeningCallQuestion]],
)
async def screening_questions(
    requirement_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    """What this requirement's screening call asks, in order: the default questions, then one
    yes / no question per must-have."""
    requirement, _client = await requirement_service.get_requirement(session, user, requirement_id)
    musts = list(requirement.must_haves or [])
    items = []
    for number, (source, q) in enumerate(
        await screening_job.call_questions(session, requirement), start=1
    ):
        key = str(q["key"])
        index = int(key.removeprefix("must_have_")) - 1 if source == "must_have" else -1
        items.append(
            ScreeningCallQuestion(
                number=number,
                key=key,
                prompt=str(q["prompt"]),
                type=str(q.get("type") or "string"),
                source=source,
                must_have=musts[index] if 0 <= index < len(musts) else None,
            )
        )
    return ok(items)
