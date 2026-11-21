"""What a candidate's screening call is about, as a `Job`.

Job candidates (the original single-job flow) use their job row. Requirement candidates get a
`Job` built on the fly from the requirement (never added to the session, never saved):

- company_name: the organization (the HR firm). Screening calls are made on the firm's behalf,
  so the client's name is never said, confidential or not.
- job_title, location, experience and skills from the requirement; no job description (the JD
  is for the telephonic round, and may name the client).
- questions: the organization's default screening questions, then one yes/no question per
  must-have (keys must_have_1, must_have_2, ...).
- is_active: the requirement is open and its client active, so calls stop when either is
  closed or put on hold.
"""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Candidate, Client, Job, Organization, Requirement
from app.database.models.enums import ClientStatus, RequirementStatus
from app.services import default_questions_service

SCREENING_INSTRUCTIONS = (
    "This is a first screening call on behalf of {firm}, a recruitment firm. Don't name the "
    "client company, even if asked: say the details are shared in the next round. Confirm the "
    "candidate is open to a change and collect the answers; the job description comes later."
)
WORK_MODE_WORDS = {"onsite": "on-site", "hybrid": "hybrid", "remote": "remote"}


def _years(value: Decimal | None) -> str:
    return f"{float(value):g}" if value is not None else ""


def experience_text(requirement: Requirement) -> str:
    low, high = _years(requirement.experience_min), _years(requirement.experience_max)
    if low and high:
        return f"{low} to {high} years" if low != high else f"{low} years"
    if low:
        return f"{low}+ years"
    return f"up to {high} years" if high else ""


def must_have_questions(must_haves: list[str]) -> list[dict[str, object]]:
    return [
        {
            "key": f"must_have_{n}",
            "prompt": f"One requirement for this role: {text}. Does that apply to you?",
            "required": True,
            "type": "boolean",
        }
        for n, text in enumerate(must_haves, start=1)
    ]


async def for_requirement(session: AsyncSession, requirement: Requirement) -> Job:
    client = await session.get(Client, requirement.client_id)
    organization = await session.get(Organization, requirement.organization_id)
    firm = organization.name if organization else ""
    defaults = [
        q.model_dump(exclude_none=True) for q in await default_questions_service.get(session)
    ]
    location = requirement.location
    if requirement.work_mode:
        mode = WORK_MODE_WORDS.get(requirement.work_mode, requirement.work_mode)
        location = f"{location} ({mode})" if location else mode
    return Job(
        id=requirement.id,
        job_title=requirement.title,
        company_name=firm,
        job_description="",
        location=location,
        required_experience=experience_text(requirement),
        skills=list(requirement.skills or []),
        screening_questions=defaults + must_have_questions(list(requirement.must_haves or [])),
        agent_instructions=SCREENING_INSTRUCTIONS.format(firm=firm or "our firm"),
        is_active=requirement.status == RequirementStatus.OPEN.value
        and client is not None
        and client.status == ClientStatus.ACTIVE.value,
    )


async def for_candidate(session: AsyncSession, candidate: Candidate | None) -> Job | None:
    """The job the candidate is screened for (None when it no longer exists)."""
    if candidate is None:
        return None
    if candidate.requirement_id is not None:
        requirement = await session.get(Requirement, candidate.requirement_id)
        return await for_requirement(session, requirement) if requirement else None
    return await session.get(Job, candidate.job_id) if candidate.job_id else None


async def callable_requirements(
    session: AsyncSession, requirement_ids: set[uuid.UUID]
) -> set[uuid.UUID]:
    """Of these requirements, the ones whose candidates may be called (open, client active)."""
    if not requirement_ids:
        return set()
    stmt = (
        select(Requirement.id)
        .join(Client, Client.id == Requirement.client_id)
        .where(
            Requirement.id.in_(requirement_ids),
            Requirement.status == RequirementStatus.OPEN.value,
            Client.status == ClientStatus.ACTIVE.value,
        )
    )
    return set((await session.execute(stmt)).scalars())
