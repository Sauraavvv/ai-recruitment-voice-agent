"""Per-turn transcript persistence (phase-06 §5.7) and the post-call summary job."""

import contextlib
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CallAttempt, Candidate, Conversation, Job
from app.services import finalization_service, screening_store, transcript_service
from app.tests.conftest import make_settings
from app.tests.unit.agent.results import make_result
from app.workers import call_worker


@pytest.fixture
def sessions(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    @contextlib.asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    for module in (transcript_service, screening_store, finalization_service, call_worker):
        monkeypatch.setattr(module, "get_sessionmaker", lambda: factory)


async def _attempt(db: AsyncSession) -> CallAttempt:
    job = Job(job_title="Backend Developer", company_name="Test Co", is_active=True)
    db.add(job)
    await db.flush()
    candidate = Candidate(
        name="Asha Rao", phone="+919000009070", job_id=job.id, applied_role="Backend Developer"
    )
    db.add(candidate)
    await db.flush()
    attempt = CallAttempt(candidate_id=candidate.id, attempt_number=1, provider="exotel")
    db.add(attempt)
    await db.commit()
    return attempt


async def _conversation(db: AsyncSession, attempt_id: uuid.UUID) -> Conversation:
    conv = (
        await db.execute(select(Conversation).where(Conversation.call_attempt_id == attempt_id))
    ).scalar_one()
    await db.refresh(conv)
    return conv


def entry(seq: int, speaker: str, text: str, **extra: Any) -> dict[str, Any]:
    return {"seq": seq, "speaker": speaker, "text": text, "timestamp": "t", **extra}


async def test_turns_are_merged_by_seq_and_idempotent(
    db_session: AsyncSession, sessions: None
) -> None:
    attempt = await _attempt(db_session)
    await transcript_service.open_conversation(attempt.id)
    await transcript_service.open_conversation(attempt.id)  # twice: still one row

    writer = transcript_service.TranscriptWriter(attempt.id)
    turns = [entry(1, "assistant", "Hello?"), entry(2, "candidate", "Yes", interrupted=False)]
    assert await writer.save(turns, live={"turn": 1}) == 2
    assert await writer.save(turns) == 0  # nothing new: no write at all
    await transcript_service.save_turns(attempt.id, turns)  # replayed directly: no change
    conv = await _conversation(db_session, attempt.id)
    assert conv.transcript == [
        entry(1, "assistant", "Hello?"),
        entry(2, "candidate", "Yes"),  # empty optional keys dropped
    ]
    assert conv.extracted_data == {"live": {"turn": 1}}

    # The agent's turn 3 is saved, then turns out to have been interrupted: replaced in place
    turns.append(entry(3, "assistant", "Hi Asha, I'm calling about"))
    await writer.save(turns)
    turns[2] = entry(3, "assistant", "Hi Asha, I'm calling about", interrupted=True)
    turns.append(entry(4, "candidate", "Sorry?"))
    assert await writer.save(turns, live={"turn": 2}) == 2
    conv = await _conversation(db_session, attempt.id)
    assert [e["seq"] for e in conv.transcript] == [1, 2, 3, 4]
    assert conv.transcript[2]["interrupted"] is True
    assert conv.extracted_data == {"live": {"turn": 2}}


async def test_finalize_call_finalizes_and_summarizes_once(
    db_session: AsyncSession, sessions: None
) -> None:
    attempt = await _attempt(db_session)
    ctx: dict[str, Any] = {"settings": make_settings()}  # no OpenAI key: facts-only summary
    assert await call_worker.finalize_call(ctx, str(attempt.id)) == "no_result"
    await screening_store.store_outcome(
        attempt_id=attempt.id, candidate_id=attempt.candidate_id, result=make_result()
    )
    assert await call_worker.finalize_call(ctx, str(attempt.id)) == "finalized"
    conv = await _conversation(db_session, attempt.id)
    assert conv.summary and "summary_sections" in conv.extracted_data
    assert conv.extracted_data["result"]["end_reason"] == "completed"
    assert await call_worker.finalize_call(ctx, str(attempt.id)) == "already_done"
