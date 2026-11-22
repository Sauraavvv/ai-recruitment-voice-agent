"""The AI evaluation of telephonic round calls (phase-11 step 6c): queued after finalization,
stored next to the answers, shown on the answers, the roster and the calls list; "Re-evaluate";
the reconciler. Fake queue and model; no live AI."""

import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.state import EndReason
from app.config import Settings
from app.database.models import CallAttempt, Candidate, Conversation
from app.services import finalization_service, telephonic_evaluation
from app.tests.conftest import make_settings
from app.tests.integration.test_telephonic_calls import (
    _call,
    _clean_slots,  # noqa: F401  (autouse fixture)
    _round,
    _setup,
    enqueued,  # noqa: F401  (fixture)
    sessions,  # noqa: F401  (fixture)
)
from app.tests.integration.test_telephony import EXOTEL
from app.tests.unit.test_round_evaluation import ScriptedLLM
from app.workers import evaluation_worker

QUESTIONS: list[dict[str, Any]] = [
    {
        "text": "Walk me through a RAG pipeline you built.",
        "rubric": "Chunking, embeddings, a vector store, retrieval, and how it was checked.",
        "weight": 3,
    },
    {
        "text": "How have you used LangChain in a project?",
        "rubric": "Chains or agents, tools, memory, in a real project.",
        "weight": 2,
    },
    {
        "text": "How would you notice model drift in production?",
        "rubric": "Watch input and output distributions, alerts, retraining.",
        "weight": 1,
    },
]
RAG = "We did chunking, then embeddings into Pinecone, and top-k retrieval."
LANGCHAIN = "I have used it a bit, not much."
MODEL_OUTPUT = {
    "answers": [
        {"id": "q1", "score": 4, "quote": "embeddings into Pinecone", "reason": "Solid basics."},
        {"id": "q2", "score": 1, "quote": "used it a bit", "reason": "No details."},
    ],
    "strengths": "Knows RAG basics.",
    "gaps": "No LangChain depth.",
}
WITH_AI = {**EXOTEL, "groq_api_keys": "test-key"}
NO_AI = {"groq_api_keys": None, "groq_api_key": None}


@pytest.fixture
def settings() -> Settings:
    return make_settings(**WITH_AI, telephony_capture_dir=None)


@pytest.fixture
def evaluation_sessions(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    sessions: None,  # noqa: F811
) -> None:
    @contextlib.asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    for module in (telephonic_evaluation, evaluation_worker):
        monkeypatch.setattr(module, "get_sessionmaker", lambda: factory)


class FakePool:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...], str]] = []

    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> None:
        self.jobs.append((function, args, kwargs["_job_id"]))


@pytest.fixture
def queued_evaluations(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str | None]]:
    jobs: list[tuple[str, str | None]] = []

    async def fake(attempt_id: str, token: str | None) -> None:
        jobs.append((attempt_id, token))

    monkeypatch.setattr("app.api.v1.calls.enqueue_evaluate_round", fake)
    return jobs


async def _approve_questions(api: AsyncClient, rid: str, questions: list[dict[str, Any]]) -> Any:
    base = f"/api/v1/requirements/{rid}/telephonic"
    saved = await api.put(f"{base}/draft", json={"questions": questions})
    assert saved.status_code == 200, saved.text
    approved = await api.post(f"{base}/approve")
    assert approved.status_code == 200, approved.text
    return approved.json()["data"]


async def _round_call(
    api: AsyncClient, db: AsyncSession
) -> tuple[str, Candidate, CallAttempt, list[dict[str, Any]]]:
    """Ravi's round call asking QUESTIONS (approved as the latest set)."""
    rid, people, _ = await _setup(api, db)
    approved = await _approve_questions(api, rid, QUESTIONS)
    (result,) = await _call(api, rid, candidate_ids=[str(people["ravi"].id)])
    attempt = await db.get(CallAttempt, uuid.UUID(result["call_attempt_id"]))
    assert attempt is not None
    return rid, people["ravi"], attempt, approved["questions"]


def _answers(questions: list[dict[str, Any]], *answers: tuple[str, str]) -> list[dict[str, Any]]:
    return [
        {"question_id": q["id"], "question": q["text"], "status": status, "answer": words}
        for q, (status, words) in zip(questions, answers, strict=True)
    ]


async def _finish(
    db: AsyncSession,
    attempt: CallAttempt,
    answers: list[dict[str, Any]],
    *,
    end: EndReason = EndReason.COMPLETED,
    pool: FakePool | None = None,
) -> None:
    from app.services import screening_store

    now = datetime.now(UTC)
    attempt.call_status, attempt.stream_id = "completed", "stream-1"
    attempt.start_time, attempt.end_time, attempt.duration_seconds = now, now, 300
    await db.commit()
    result = _round(attempt, end, [a["status"] for a in answers])
    result.answers = answers
    await screening_store.store_telephonic_outcome(
        attempt_id=attempt.id, candidate_id=attempt.candidate_id, result=result
    )
    outcome = await finalization_service.finalize_attempt(
        attempt.id, settings=make_settings(**WITH_AI), llm=None, pool=pool
    )
    assert outcome == "finalized"


async def _stored(db: AsyncSession, attempt: CallAttempt) -> dict[str, Any]:
    conv = await db.scalar(
        select(Conversation)
        .where(Conversation.call_attempt_id == attempt.id)
        .execution_options(populate_existing=True)
    )
    assert conv is not None
    return telephonic_evaluation.stored(conv)


async def test_a_finished_round_is_evaluated_and_shown(
    admin: AsyncClient,
    db_session: AsyncSession,
    enqueued: list[str],  # noqa: F811
    evaluation_sessions: None,
) -> None:
    rid, ravi, attempt, questions = await _round_call(admin, db_session)
    pool = FakePool()
    answers = _answers(questions, ("answered", RAG), ("partial", LANGCHAIN), ("dont_know", "No."))
    await _finish(db_session, attempt, answers, pool=pool)

    # Finalizing queued the automatic evaluation
    aid = str(attempt.id)
    assert pool.jobs == [("evaluate_round", (aid, None), f"evaluate:{aid}:auto")]

    llm = ScriptedLLM(MODEL_OUTPUT)
    settings = make_settings(**WITH_AI)
    assert await telephonic_evaluation.run(attempt.id, token=None, llm=llm, settings=settings) == (
        "done"
    )
    # Nothing personal goes to the model
    prompt = "\n".join(m.content for m in llm.calls[0])
    assert ravi.name not in prompt and ravi.name.split()[0] not in prompt
    assert ravi.phone not in prompt
    assert QUESTIONS[0]["rubric"] in prompt and RAG in prompt

    stored = await _stored(db_session, attempt)
    assert stored["state"] == "done" and stored["result"]["score"] == 47
    assert stored["result"]["verdict"] == "possible_fit" and not stored["result"]["incomplete"]

    # The answers view
    body = (await admin.get(f"/api/v1/calls/{aid}/answers")).json()["data"]
    evaluation = body["evaluation"]
    assert evaluation["state"] == "done"
    assert [(q["score"], q["rule"]) for q in evaluation["result"]["questions"]] == [
        (4, "model"),
        (1, "model"),
        (0, "dont_know"),
    ]
    assert evaluation["result"]["questions"][0]["quote"] == "embeddings into Pinecone"
    assert evaluation["result"]["rubric_version"] == 2

    # The roster row and the calls list carry the badge
    roster = (await admin.get(f"/api/v1/requirements/{rid}/telephonic/candidates")).json()["data"]
    (row,) = [r for r in roster["rows"] if r["candidate_id"] == str(ravi.id)]
    assert row["evaluation"] == {
        "call_attempt_id": aid,
        "state": "done",
        "score": 47,
        "verdict": "possible_fit",
        "incomplete": False,
    }
    calls = (await admin.get("/api/v1/calls", params={"purpose": "telephonic"})).json()["data"]
    assert [c["evaluation"]["score"] for c in calls if c["id"] == aid] == [47]

    # The finalize job running twice changes nothing
    again = await telephonic_evaluation.run(attempt.id, token=None, llm=None, settings=settings)
    assert again == "already_done"


async def test_a_round_cut_short_is_marked_incomplete(
    admin: AsyncClient,
    db_session: AsyncSession,
    enqueued: list[str],  # noqa: F811
    evaluation_sessions: None,
) -> None:
    _, _, attempt, questions = await _round_call(admin, db_session)
    answers = _answers(questions, ("answered", RAG), ("partial", LANGCHAIN), ("not_asked", ""))
    await _finish(db_session, attempt, answers, end=EndReason.HANGUP)
    llm = ScriptedLLM(MODEL_OUTPUT)
    await telephonic_evaluation.run(attempt.id, token=None, llm=llm, settings=make_settings())
    result = (await _stored(db_session, attempt))["result"]
    # (3·4 + 2·1) / (5·5) = 56: the question not asked isn't counted
    assert (result["score"], result["incomplete"]) == (56, True)
    assert result["not_covered"] == [QUESTIONS[2]["text"]]


async def test_a_round_with_nothing_said_is_skipped(
    admin: AsyncClient,
    db_session: AsyncSession,
    enqueued: list[str],  # noqa: F811
    evaluation_sessions: None,
) -> None:
    _, _, attempt, questions = await _round_call(admin, db_session)
    answers = _answers(questions, ("not_asked", ""), ("not_asked", ""), ("not_asked", ""))
    await _finish(db_session, attempt, answers, end=EndReason.DECLINED)
    llm = ScriptedLLM()
    outcome = await telephonic_evaluation.run(
        attempt.id, token=None, llm=llm, settings=make_settings()
    )
    assert outcome == "skipped" and llm.calls == []
    assert (await _stored(db_session, attempt))["state"] == "skipped"


async def test_a_callback_is_evaluated_with_the_earlier_answers(
    admin: AsyncClient,
    db_session: AsyncSession,
    enqueued: list[str],  # noqa: F811
    evaluation_sessions: None,
) -> None:
    _, ravi, first, questions = await _round_call(admin, db_session)
    answers = _answers(questions, ("answered", RAG), ("not_asked", ""), ("not_asked", ""))
    await _finish(db_session, first, answers, end=EndReason.HANGUP)
    second = CallAttempt(
        candidate_id=ravi.id,
        attempt_number=first.attempt_number + 1,
        attempt_type="manual",
        purpose="telephonic",
        question_set_id=first.question_set_id,
        provider="exotel",
        call_status="queued",
    )
    db_session.add(second)
    await db_session.commit()
    # The second call resumed: question 1 came from the earlier call
    later = _answers(questions, ("not_asked", ""), ("partial", LANGCHAIN), ("dont_know", "No."))
    await _finish(db_session, second, later)

    llm = ScriptedLLM(MODEL_OUTPUT)
    await telephonic_evaluation.run(second.id, token=None, llm=llm, settings=make_settings())
    result = (await _stored(db_session, second))["result"]
    assert [q["from_earlier_call"] for q in result["questions"]] == [True, False, False]
    assert (result["score"], result["incomplete"]) == (47, False)


async def test_reevaluate_uses_the_sharpened_rubric(
    admin: AsyncClient,
    db_session: AsyncSession,
    enqueued: list[str],  # noqa: F811
    evaluation_sessions: None,
    queued_evaluations: list[tuple[str, str | None]],
) -> None:
    rid, _, attempt, questions = await _round_call(admin, db_session)
    answers = _answers(questions, ("answered", RAG), ("partial", LANGCHAIN), ("dont_know", "No."))
    await _finish(db_session, attempt, answers)
    await telephonic_evaluation.run(
        attempt.id, token=None, llm=ScriptedLLM(MODEL_OUTPUT), settings=make_settings()
    )
    aid = str(attempt.id)

    # The recruiter sharpens question 1's rubric (same question, a new approved version)
    sharper = [dict(q) for q in questions]
    sharper[0]["rubric"] = "Must name the chunk size and an evaluation metric."
    await _approve_questions(admin, rid, sharper)

    response = await admin.post(f"/api/v1/calls/{aid}/evaluate")
    assert response.status_code == 202, response.text
    evaluation = response.json()["data"]["evaluation"]
    assert evaluation["state"] == "pending"
    assert evaluation["result"]["score"] == 47  # the old result stays meanwhile
    ((queued_id, token),) = queued_evaluations
    assert queued_id == aid and token

    # An older automatic run finishing now must not overwrite the request
    stale = await telephonic_evaluation.run(
        attempt.id, token=None, llm=ScriptedLLM(), settings=make_settings()
    )
    assert stale == "superseded"

    llm = ScriptedLLM(MODEL_OUTPUT)
    assert await telephonic_evaluation.run(
        attempt.id, token=token, llm=llm, settings=make_settings()
    ) == ("done")
    assert "Must name the chunk size" in llm.calls[0][1].content
    stored = await _stored(db_session, attempt)
    assert stored["state"] == "done" and stored["result"]["rubric_version"] == 3


async def test_the_question_sets_level_decides_how_gently_answers_are_scored(
    admin: AsyncClient,
    db_session: AsyncSession,
    enqueued: list[str],  # noqa: F811
    evaluation_sessions: None,
) -> None:
    from app.database.models import QuestionSet

    _, _, attempt, questions = await _round_call(admin, db_session)
    question_set = await db_session.get(QuestionSet, attempt.question_set_id)
    assert question_set is not None
    question_set.level = "easy"
    await db_session.commit()
    answers = _answers(questions, ("answered", RAG), ("partial", LANGCHAIN), ("dont_know", "No."))
    await _finish(db_session, attempt, answers)
    llm = ScriptedLLM(MODEL_OUTPUT)
    await telephonic_evaluation.run(attempt.id, token=None, llm=llm, settings=make_settings())
    assert llm.calls[0][1].content.startswith("LEVEL: easy")
    assert (await _stored(db_session, attempt))["result"]["level"] == "easy"


async def test_reevaluate_is_refused_when_it_cannot_run(
    admin: AsyncClient,
    db_session: AsyncSession,
    enqueued: list[str],  # noqa: F811
    evaluation_sessions: None,
    queued_evaluations: list[tuple[str, str | None]],
) -> None:
    _, _, attempt, _ = await _round_call(admin, db_session)
    response = await admin.post(f"/api/v1/calls/{attempt.id}/evaluate")
    assert response.status_code == 409 and response.json()["error"]["code"] == "not_finalized"
    response = await admin.post(f"/api/v1/calls/{uuid.uuid4()}/evaluate")
    assert response.status_code == 404
    assert queued_evaluations == []


async def test_a_failed_evaluation_keeps_the_old_result_and_the_reconciler_retries(
    admin: AsyncClient,
    db_session: AsyncSession,
    enqueued: list[str],  # noqa: F811
    evaluation_sessions: None,
) -> None:
    from app.providers.llm.base import LLMUnavailableError

    _, _, attempt, questions = await _round_call(admin, db_session)
    answers = _answers(questions, ("answered", RAG), ("partial", LANGCHAIN), ("dont_know", "No."))
    await _finish(db_session, attempt, answers)
    ctx: dict[str, Any] = {"settings": make_settings(**WITH_AI), "redis": FakePool()}
    aid = str(attempt.id)

    # Just finalized: the automatic job gets a head start
    assert await evaluation_worker.reconcile_evaluations(ctx) == 0
    later = datetime.now(UTC) + timedelta(minutes=5)
    # Never evaluated (the job was lost): queued again
    assert await evaluation_worker.reconcile_evaluations(ctx, now=later) == 1
    assert ctx["redis"].jobs[-1] == ("evaluate_round", (aid, None), f"evaluate:{aid}:auto")

    busy = ScriptedLLM(LLMUnavailableError("busy"))
    outcome = await telephonic_evaluation.run(
        attempt.id, token=None, llm=busy, settings=make_settings()
    )
    assert outcome == "failed:ai_unavailable"
    stored = await _stored(db_session, attempt)
    assert (stored["state"], stored["error"], stored["failures"]) == ("failed", "ai_unavailable", 1)

    # Failed: retried after a while, at most three times
    assert await evaluation_worker.reconcile_evaluations(ctx, now=later) == 0
    assert await evaluation_worker.reconcile_evaluations(ctx, now=later + timedelta(hours=1)) == 1
    await telephonic_evaluation.run(
        attempt.id, token=None, llm=ScriptedLLM(MODEL_OUTPUT), settings=make_settings()
    )
    assert (await _stored(db_session, attempt))["state"] == "done"
    assert await evaluation_worker.reconcile_evaluations(ctx, now=later + timedelta(hours=2)) == 0

    # Without the AI configured the reconciler does nothing
    assert await evaluation_worker.reconcile_evaluations({"settings": make_settings(**NO_AI)}) == 0
