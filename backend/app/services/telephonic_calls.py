"""Starting telephonic round calls for a requirement (phase-11 step 6b).

The rules are in `call_service` (purpose telephonic): interested on a completed screening, an
approved question set, not already done unless the recruiter confirms. This module scopes the
request to one requirement (access follows it) and picks "everyone not called yet".
"""

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import (
    CallAttempt,
    CallAttemptType,
    CallPurpose,
    CallStatus,
    Candidate,
    ScreeningStatus,
    User,
)
from app.schemas.telephonic import MAX_TELEPHONIC_BATCH, TelephonicCallsRequest
from app.services import call_service, requirement_service
from app.services.call_service import Ineligible, StartResult

Enqueue = Callable[[str], Awaitable[None]]


async def not_called_interested(
    session: AsyncSession, requirement_id: uuid.UUID, *, limit: int = MAX_TELEPHONIC_BATCH
) -> list[uuid.UUID]:
    """Candidates of the requirement who finished screening interested and have no telephonic
    round call yet (cancelled ones don't count), oldest first."""
    had_round = exists().where(
        CallAttempt.candidate_id == Candidate.id,
        CallAttempt.purpose == CallPurpose.TELEPHONIC.value,
        CallAttempt.call_status != CallStatus.CANCELLED.value,
    )
    stmt = (
        select(Candidate.id)
        .where(
            Candidate.requirement_id == requirement_id,
            Candidate.deleted_at.is_(None),
            Candidate.opted_out.is_(False),
            Candidate.interested.is_(True),
            Candidate.screening_status == ScreeningStatus.COMPLETED.value,
            ~had_round,
        )
        .order_by(Candidate.created_at, Candidate.id)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars())


async def start(
    session: AsyncSession,
    user: User,
    requirement_id: uuid.UUID,
    body: TelephonicCallsRequest,
    settings: Settings,
    enqueue: Enqueue,
    *,
    voice_ready: bool,
) -> list[StartResult]:
    requirement, _client = await requirement_service.get_requirement(session, user, requirement_id)
    ids = list(dict.fromkeys(body.candidate_ids)) or await not_called_interested(
        session, requirement.id
    )
    if not ids:
        return []
    mine = set(
        (
            await session.execute(
                select(Candidate.id).where(
                    Candidate.id.in_(ids), Candidate.requirement_id == requirement.id
                )
            )
        ).scalars()
    )
    started = {
        r.candidate_id: r
        for r in await call_service.start_calls(
            session,
            [i for i in ids if i in mine],
            settings,
            enqueue,
            attempt_type=CallAttemptType.MANUAL,
            voice_ready=voice_ready,
            dry_run=body.dry_run,
            override_limit=body.override_limit,
            purpose=CallPurpose.TELEPHONIC,
            call_again=body.call_again,
        )
    }
    # Someone else's candidate, or another opening's: not found here
    return [started.get(i) or StartResult(i, error=Ineligible.NOT_FOUND) for i in ids]
