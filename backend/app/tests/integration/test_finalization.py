"""Finalization against the database (phase-07 §5, P7-T1 to P7-T4, P7-AC1 to AC3)."""

import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.state import EndReason
from app.database.models import (
    CallAttempt,
    Candidate,
    Conversation,
    Job,
    Organization,
    ScreeningStatus,
)
from app.services import finalization_service, screening_store
from app.tests.conftest import make_settings
from app.tests.unit.agent.results import final_output, make_result
from app.tests.unit.agent.stub_llm import ScriptedLLM
from app.workers import call_worker

SETTINGS = make_settings()

FULL = {
    "current_location": ("Pune", "I live in Pune"),
    "current_company": ("Infosys", "I work at Infosys"),
    "total_experience": (5.0, "five years total"),
    "relevant_experience": (3.0, "three years in backend"),
    "current_ctc": (12.0, "twelve lakhs"),
    "expected_ctc": (18.0, "eighteen lakhs"),
    "notice_period": ("30 days", "thirty days notice"),
    "reason_for_change": ("better growth", "looking for better growth"),
    "interested": (True, "yes I am interested"),
    "interview_availability": ("Monday after 4 pm", "Monday after 4 pm works"),
}


def full_result(keys: list[str] | None = None, **overrides: Any) -> Any:
    keys = list(FULL) if keys is None else keys
    transcript: list[dict[str, Any]] = []
    fields: dict[str, Any] = {}
    for i, key in enumerate(FULL):
        value, words = FULL[key]
        transcript.append({"seq": 2 * i + 1, "speaker": "assistant", "text": f"Ask {key}?"})
        if key in keys:
            transcript.append({"seq": 2 * i + 2, "speaker": "candidate", "text": words})
            fields[key] = {"value": value, "status": "confirmed", "raw_text": words, "turn": i + 1}
        else:
            fields[key] = {"value": None, "status": "missing"}
    values: dict[str, Any] = {
        "fields": fields,
        "collected_data": {k: f["value"] for k, f in fields.items()},
        "missing_fields": [k for k in FULL if k not in keys],
        "transcript": transcript,
    }
    values.update(overrides)
    return make_result(**values)


@pytest.fixture
def sessions(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    @contextlib.asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    for module in (screening_store, finalization_service, call_worker):
        monkeypatch.setattr(module, "get_sessionmaker", lambda: factory)
    return []


async def _attempt(db: AsyncSession, phone: str = "+919000009070", **candidate: Any) -> CallAttempt:
    job = Job(job_title="Backend Developer", company_name="Test Co", is_active=True)
    org = Organization(name="Test Co")
    db.add_all([job, org])
    await db.flush()
    person = Candidate(
        organization_id=org.id,
        name="Asha Rao",
        phone=phone,
        job_id=job.id,
        applied_role="Backend Developer",
        **candidate,
    )
    db.add(person)
    await db.flush()
    attempt = CallAttempt(
        candidate_id=person.id, attempt_number=1, provider="exotel", call_status="completed"
    )
    db.add(attempt)
    await db.commit()
    return attempt


async def _store(db: AsyncSession, attempt: CallAttempt, result: Any) -> None:
    await screening_store.store_outcome(
        attempt_id=attempt.id, candidate_id=attempt.candidate_id, result=result
    )


async def _state(db: AsyncSession, attempt: CallAttempt) -> tuple[Candidate, Conversation]:
    candidate = await db.get(Candidate, attempt.candidate_id)
    conv = (
        await db.execute(select(Conversation).where(Conversation.call_attempt_id == attempt.id))
    ).scalar_one()
    assert candidate is not None
    await db.refresh(candidate)
    await db.refresh(conv)
    return candidate, conv


async def test_completed_call_updates_the_candidate(
    db_session: AsyncSession, sessions: list[str]
) -> None:
    """P7-AC1 (automated), P7-AC3: fields, status, conversation, summary."""
    attempt = await _attempt(db_session)
    await _store(db_session, attempt, full_result())
    out = await finalization_service.finalize_attempt(attempt.id, settings=SETTINGS, llm=None)
    assert out == "finalized"

    candidate, conv = await _state(db_session, attempt)
    for key, (value, _) in FULL.items():
        assert getattr(candidate, key) == value, key
    assert candidate.screening_status == "completed"
    assert candidate.screening_field_meta["current_ctc"]["raw_text"] == "twelve lakhs"
    assert candidate.screening_field_meta["current_ctc"]["call_attempt_id"] == str(attempt.id)
    assert conv.finalized_at is not None and conv.screening_completed
    assert conv.extracted_data["final"]["screening_status"] == "completed"
    assert conv.extracted_data["final"]["missing_fields"] == []
    assert conv.summary and "Missing" not in conv.summary
    await db_session.refresh(attempt)
    assert attempt.end_reason == "agent_completed"


async def test_finalize_twice_gives_one_result(
    db_session: AsyncSession, sessions: list[str]
) -> None:
    attempt = await _attempt(db_session)
    await _store(db_session, attempt, full_result())
    ctx: dict[str, Any] = {"settings": SETTINGS}
    assert await call_worker.finalize_call(ctx, str(attempt.id)) == "finalized"
    _, conv = await _state(db_session, attempt)
    first = (conv.finalized_at, conv.summary)
    assert await call_worker.finalize_call(ctx, str(attempt.id)) == "already_done"
    _, conv = await _state(db_session, attempt)
    assert (conv.finalized_at, conv.summary) == first


async def test_no_result_yet(db_session: AsyncSession, sessions: list[str]) -> None:
    attempt = await _attempt(db_session)
    out = await finalization_service.finalize_attempt(attempt.id, settings=SETTINGS, llm=None)
    assert out == "no_result"


async def test_partial_call_keeps_the_answers_given(
    db_session: AsyncSession, sessions: list[str]
) -> None:
    """P7-AC2: hang up after 4 answers → those 4 saved, partially_completed."""
    attempt = await _attempt(db_session)
    four = ["current_location", "current_company", "total_experience", "relevant_experience"]
    await _store(db_session, attempt, full_result(four, end_reason=EndReason.HANGUP))
    await finalization_service.finalize_attempt(attempt.id, settings=SETTINGS, llm=None)
    candidate, conv = await _state(db_session, attempt)
    assert candidate.screening_status == "partially_completed"
    assert [k for k in FULL if getattr(candidate, k) is not None] == four
    assert not conv.screening_completed
    assert conv.summary and "Missing:" in conv.summary and "current ctc" in conv.summary  # AC3


async def test_null_never_overwrites_and_opt_out_is_sticky(
    db_session: AsyncSession, sessions: list[str]
) -> None:
    attempt = await _attempt(
        db_session,
        current_ctc=10.0,
        opted_out=True,
        screening_field_meta={"current_ctc": {"value": 10.0, "raw_text": "ten lakhs"}},
    )
    result = full_result(["current_location"], end_reason=EndReason.HANGUP)
    result.fields["current_ctc"] = {"value": None, "status": "declined"}  # declined this time
    await _store(db_session, attempt, result)
    await finalization_service.finalize_attempt(attempt.id, settings=SETTINGS, llm=None)
    candidate, _ = await _state(db_session, attempt)
    assert candidate.current_ctc == 10.0  # the earlier answer stays
    assert candidate.screening_field_meta["current_ctc"]["raw_text"] == "ten lakhs"
    assert candidate.current_location == "Pune"
    assert candidate.opted_out is True  # never back to false


async def test_final_pass_fills_a_missed_answer_and_rejects_invented_ones(
    db_session: AsyncSession, sessions: list[str]
) -> None:
    attempt = await _attempt(db_session)
    keys = [k for k in FULL if k != "expected_ctc"]
    result = full_result(keys)
    # STT/agent missed it live, but the candidate said it
    result.transcript.append(
        {"seq": 99, "speaker": "candidate", "text": "expecting eighteen lakhs"}
    )
    await _store(db_session, attempt, result)
    llm = ScriptedLLM(
        [
            final_output(
                {"expected_ctc_lpa": 18, "current_company": "Google"},
                [
                    ("expected_ctc_lpa", "expecting eighteen lakhs", 99),
                    ("current_company", "I work at Google", 4),
                ],
            ),
            "Asha lives in Pune and works at Infosys.",  # the summary
        ]
    )
    await finalization_service.finalize_attempt(attempt.id, settings=SETTINGS, llm=llm)
    candidate, conv = await _state(db_session, attempt)
    assert candidate.expected_ctc == 18.0
    assert candidate.screening_field_meta["expected_ctc"]["source"] == "final_pass"
    assert candidate.current_company == "Infosys"  # live, confirmed; Google had no evidence
    final = conv.extracted_data["final"]
    assert final["final_pass_ran"] and "current_company" in final["rejected"]
    assert candidate.screening_status == "completed"
    assert conv.summary and conv.summary.startswith("Asha lives in Pune")


async def test_final_pass_failure_still_saves_the_live_state(
    db_session: AsyncSession, sessions: list[str]
) -> None:
    from app.providers.llm.base import LLMTimeoutError

    attempt = await _attempt(db_session)
    await _store(db_session, attempt, full_result())
    llm = ScriptedLLM([LLMTimeoutError("t")] * 4)  # final pass, then 3 summary tries
    await finalization_service.finalize_attempt(attempt.id, settings=SETTINGS, llm=llm)
    candidate, conv = await _state(db_session, attempt)
    assert candidate.screening_status == "completed" and candidate.current_ctc == 12.0
    assert not conv.extracted_data["final"]["final_pass_ran"]
    assert conv.extracted_data["summary_sections"]["generated_by"] == "deterministic"


async def test_failure_mid_transaction_saves_nothing(
    db_session: AsyncSession, sessions: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """One transaction: when it fails after the fields were merged, nothing is saved."""
    attempt = await _attempt(db_session)
    await _store(db_session, attempt, full_result())
    real = finalization_service.merge_candidate

    def explode(*args: Any, **kwargs: Any) -> Any:
        real(*args, **kwargs)  # the candidate's fields are changed, then the transaction fails
        raise RuntimeError("boom")

    monkeypatch.setattr(finalization_service, "merge_candidate", explode)
    with pytest.raises(RuntimeError):
        await finalization_service.finalize_attempt(attempt.id, settings=SETTINGS, llm=None)
    await db_session.rollback()  # what closing the session does in production
    await db_session.refresh(attempt)
    candidate, conv = await _state(db_session, attempt)
    assert candidate.current_location is None and candidate.screening_status == "not_started"
    assert conv.finalized_at is None and "final" not in conv.extracted_data

    monkeypatch.setattr(finalization_service, "merge_candidate", real)  # fixed: the retry works
    out = await finalization_service.finalize_attempt(attempt.id, settings=SETTINGS, llm=None)
    assert out == "finalized"


async def test_opt_out_cancels_scheduled_attempts(
    db_session: AsyncSession, sessions: list[str]
) -> None:
    attempt = await _attempt(db_session)
    scheduled = CallAttempt(
        candidate_id=attempt.candidate_id,
        attempt_number=2,
        provider="exotel",
        call_status="retry_scheduled",
        next_retry_at=datetime.now(UTC) + timedelta(days=2),
    )
    db_session.add(scheduled)
    await db_session.commit()
    await _store(
        db_session,
        attempt,
        full_result(["current_location"], end_reason=EndReason.OPTED_OUT, opted_out=True),
    )
    await finalization_service.finalize_attempt(attempt.id, settings=SETTINGS, llm=None)
    candidate, _ = await _state(db_session, attempt)
    await db_session.refresh(scheduled)
    assert candidate.opted_out and candidate.screening_status == ScreeningStatus.OPTED_OUT
    assert scheduled.call_status == "cancelled" and scheduled.failure_reason == "opted_out"


async def test_summary_failure_never_blocks_and_is_retried(
    db_session: AsyncSession, sessions: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt = await _attempt(db_session)
    await _store(db_session, attempt, full_result())

    async def broken(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("summary down")

    real = finalization_service.generate_summary
    monkeypatch.setattr(finalization_service, "generate_summary", broken)
    assert (
        await finalization_service.finalize_attempt(attempt.id, settings=SETTINGS, llm=None)
        == "finalized"
    )
    candidate, conv = await _state(db_session, attempt)
    assert candidate.screening_status == "completed" and conv.summary is None

    # The reconciler re-queues it ...
    queued: list[tuple[Any, ...]] = []

    class Pool:
        async def enqueue_job(self, *args: Any, **kwargs: Any) -> None:
            queued.append(args)

    later = datetime.now(UTC) + timedelta(minutes=11)
    assert await call_worker.reconcile_finalize({"redis": Pool()}, now=later) >= 1
    assert ("finalize_call", str(attempt.id)) in queued
    # ... and the next run only writes the summary
    monkeypatch.setattr(finalization_service, "generate_summary", real)
    assert (
        await finalization_service.finalize_attempt(attempt.id, settings=SETTINGS, llm=None)
        == "summarized"
    )
    _, conv = await _state(db_session, attempt)
    assert conv.summary


async def test_an_older_call_finalized_late_never_overwrites_a_newer_one(
    db_session: AsyncSession, sessions: list[str]
) -> None:
    """A backlog finalized out of order (seen 2026-11-19 when the reconciler first ran)."""
    older = await _attempt(db_session)
    newer = CallAttempt(
        candidate_id=older.candidate_id,
        attempt_number=2,
        provider="exotel",
        call_status="completed",
    )
    db_session.add(newer)
    await db_session.commit()
    await _store(db_session, older, full_result(end_reason=EndReason.CALLBACK))
    newer_result = full_result(["current_location", "current_ctc"], end_reason=EndReason.HANGUP)
    newer_result.fields["current_ctc"]["value"] = 15.0
    await _store(db_session, newer, newer_result)

    await finalization_service.finalize_attempt(newer.id, settings=SETTINGS, llm=None)
    await finalization_service.finalize_attempt(older.id, settings=SETTINGS, llm=None)
    candidate, conv = await _state(db_session, older)
    assert candidate.screening_status == "partially_completed"  # the newer call's
    assert candidate.current_ctc == 15.0  # not overwritten by the older 12.0
    assert candidate.notice_period == "30 days"  # an empty field is still filled
    assert conv.extracted_data["final"]["superseded"] is True
