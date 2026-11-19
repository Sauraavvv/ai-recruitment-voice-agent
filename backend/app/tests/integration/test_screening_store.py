"""End of the call: the conversation row gets the transcript and live result; the candidate is
left to finalization, except an opt-out (written at once, with its outbox row)."""

import contextlib
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.conversation_manager import ScreeningResult
from app.database.models import CallAttempt, Candidate, Conversation, ScreeningStatus, SyncLog
from app.services import screening_store
from app.tests.unit.agent.results import make_result


def _result(**overrides: Any) -> ScreeningResult:
    """Kept for older imports."""
    return make_result(**overrides)


@pytest.fixture
def sessions(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    @contextlib.asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(screening_store, "get_sessionmaker", lambda: factory)


async def _setup(authed: AsyncClient, db: AsyncSession) -> tuple[uuid.UUID, CallAttempt]:
    response = await authed.post(
        "/api/v1/candidates",
        json={
            "name": "Tester",
            "phone": "+91 90000 09060",
            "applied_role": "Dev",
            "consent_attested": True,
        },
    )
    cid = uuid.UUID(response.json()["data"]["id"])
    attempt = CallAttempt(
        candidate_id=cid, attempt_number=1, provider="exotel", call_status="completed"
    )
    db.add(attempt)
    await db.flush()
    return cid, attempt


async def _outbox(db: AsyncSession, cid: uuid.UUID) -> int:
    return int(await db.scalar(select(func.count()).where(SyncLog.candidate_id == cid)) or 0)


async def test_store_outcome_stores_the_conversation_only(
    authed: AsyncClient, active_job: dict[str, Any], db_session: AsyncSession, sessions: None
) -> None:
    cid, attempt = await _setup(authed, db_session)
    before = await _outbox(db_session, cid)
    await screening_store.store_outcome(
        attempt_id=attempt.id, candidate_id=cid, result=make_result(), extra={"end_reason": "x"}
    )
    conv = (
        await db_session.execute(
            select(Conversation).where(Conversation.call_attempt_id == attempt.id)
        )
    ).scalar_one()
    assert len(conv.transcript) == 8 and conv.finalized_at is None
    assert conv.extracted_data["result"]["end_reason"] == "completed"
    assert conv.extracted_data["end_reason"] == "x"
    assert "transcript" not in conv.extracted_data["result"]

    candidate = await db_session.get(Candidate, cid)
    assert candidate is not None
    await db_session.refresh(candidate)
    assert candidate.current_location is None  # finalization writes the fields
    assert candidate.screening_status == "not_started"
    assert await _outbox(db_session, cid) == before

    # Stored again (e.g. a retry of the end-of-call write): one row, updated
    await screening_store.store_outcome(
        attempt_id=attempt.id, candidate_id=cid, result=make_result(turns=9)
    )
    rows = (
        await db_session.execute(
            select(Conversation).where(Conversation.call_attempt_id == attempt.id)
        )
    ).scalars()
    assert [c.extracted_data["result"]["turns"] for c in rows] == [9]


async def test_opt_out_is_written_at_once(
    authed: AsyncClient, active_job: dict[str, Any], db_session: AsyncSession, sessions: None
) -> None:
    cid, attempt = await _setup(authed, db_session)
    before = await _outbox(db_session, cid)
    await screening_store.store_outcome(
        attempt_id=attempt.id,
        candidate_id=cid,
        result=make_result(opted_out=True, screening_status=ScreeningStatus.OPTED_OUT),
    )
    candidate = await db_session.get(Candidate, cid)
    assert candidate is not None
    await db_session.refresh(candidate)
    assert candidate.opted_out and candidate.screening_status == "opted_out"
    assert await _outbox(db_session, cid) == before + 1
