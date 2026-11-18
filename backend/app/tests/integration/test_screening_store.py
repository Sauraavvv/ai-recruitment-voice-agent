"""Storing a screening result: candidate fields, metadata, status and the conversation row."""

import contextlib
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.conversation_manager import ScreeningResult
from app.agent.state import EndReason
from app.database.models import CallAttempt, Candidate, Conversation, ScreeningStatus
from app.services import screening_store


@pytest.fixture
def sessions(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    @contextlib.asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    monkeypatch.setattr(screening_store, "get_sessionmaker", lambda: factory)


def _result(**overrides: Any) -> ScreeningResult:
    values: dict[str, Any] = {
        "end_reason": EndReason.COMPLETED,
        "screening_status": ScreeningStatus.COMPLETED,
        "collected_data": {
            "current_location": "Delhi",
            "total_experience": 3.0,
            "current_ctc": 12.0,
            "interested": True,
            "notice_period": None,
        },
        "fields": {
            "current_location": {"status": "confirmed", "raw_text": "I'm in Delhi"},
            "total_experience": {"status": "confirmed", "raw_text": "three years"},
            "current_ctc": {"status": "confirmed", "raw_text": "twelve lakhs"},
            "interested": {"status": "confirmed", "raw_text": "yes"},
            "notice_period": {"status": "declined"},
        },
        "missing_fields": [],
        "callback": {"requested": False},
        "opted_out": False,
        "declined_opportunity": False,
        "identity_confirmed": True,
        "candidate_questions": [],
        "escalation_reason": None,
        "transcript": [
            {"speaker": "agent", "text": "Hello"},
            {"speaker": "candidate", "text": "Hi"},
        ],
        "turns": 2,
        "llm_calls": 1,
        "input_tokens": 10,
        "output_tokens": 5,
    }
    values.update(overrides)
    return ScreeningResult(**values)


async def test_save_result_updates_candidate_and_conversation(
    authed: AsyncClient, active_job: dict[str, Any], db_session: AsyncSession, sessions: None
) -> None:
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
    db_session.add(attempt)
    await db_session.flush()

    await screening_store.save_result(
        attempt_id=attempt.id,
        candidate_id=cid,
        result=_result(),
        job_title="Dev",
        candidate_name="Tester",
        llm=None,
    )
    candidate = await db_session.get(Candidate, cid)
    assert candidate is not None
    await db_session.refresh(candidate)
    assert (candidate.current_location, candidate.total_experience, candidate.current_ctc) == (
        "Delhi",
        3.0,
        12.0,
    )
    assert candidate.interested is True and candidate.notice_period is None
    assert candidate.screening_status == "completed"
    assert candidate.screening_field_meta["current_ctc"]["raw_text"] == "twelve lakhs"
    assert candidate.screening_field_meta["current_ctc"]["call_attempt_id"] == str(attempt.id)
    conv = (
        await db_session.execute(
            select(Conversation).where(Conversation.call_attempt_id == attempt.id)
        )
    ).scalar_one()
    assert conv.screening_completed and len(conv.transcript) == 2
    assert conv.summary and "transcript" not in conv.extracted_data

    # Opt-out on a later save is stored too, and the row is updated, not duplicated
    await screening_store.save_result(
        attempt_id=attempt.id,
        candidate_id=cid,
        result=_result(opted_out=True, screening_status=ScreeningStatus.OPTED_OUT),
        job_title="Dev",
        candidate_name="Tester",
        llm=None,
    )
    await db_session.refresh(candidate)
    assert candidate.opted_out and candidate.screening_status == "opted_out"
