"""Telephonic round calls (phase-11 step 6b): who may be called, the start endpoint, the question
set pinned at queue time, per-purpose attempt counts, retries that keep their purpose (build
step 1); the call's context, the conversation it builds and what it stores (build step 2).
Fake queue, provider, voice and AI; no live call, no live AI."""

import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.state import EndReason
from app.agent.telephonic_manager import TelephonicManager, TelephonicResult
from app.config import Settings
from app.database.models import (
    CallAttempt,
    CallAttemptType,
    Candidate,
    Client,
    Conversation,
    Requirement,
)
from app.repositories import call_repo
from app.services import (
    finalization_service,
    retry_service,
    screening_store,
    settings_service,
    telephonic_call,
    telephonic_finalization,
    transcript_service,
)
from app.tests.conftest import make_settings
from app.tests.integration.test_requirement_screening import _confirm, _import, _requirement
from app.tests.integration.test_telephony import EXOTEL, FakeProvider
from app.utils.clock import FrozenClock
from app.utils.redis import get_redis
from app.voice import websocket_handler as wh
from app.workers import call_worker

QUESTION = "Tell me about the last product you sold."
JD = "We need a sales executive who can sell CRM software to small businesses in Pune."
CSV = (
    b"Name,Phone\nRavi Kumar,9876543210\nPriya Shah,9876543211\nAmit Rao,9876543212\n"
    b"Neha Jain,9876543213\n"
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(**EXOTEL, telephony_capture_dir=None)


@pytest.fixture(autouse=True)
async def _clean_slots(client: AsyncClient) -> AsyncIterator[None]:
    redis = get_redis()
    for key in await redis.keys("rcai:call:slot:*"):
        await redis.delete(key)
    yield
    for key in await redis.keys("rcai:call:slot:*"):
        await redis.delete(key)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    jobs: list[str] = []

    async def fake(attempt_id: str, *, ignore_window: bool = False) -> None:
        jobs.append(attempt_id)

    monkeypatch.setattr("app.api.v1.telephonic.enqueue_initiate_call", fake)
    return jobs


async def _approve(api: AsyncClient, rid: str, text: str) -> str:
    base = f"/api/v1/requirements/{rid}/telephonic"
    saved = await api.put(f"{base}/draft", json={"questions": [{"text": text}]})
    assert saved.status_code == 200, saved.text
    approved = await api.post(f"{base}/approve")
    assert approved.status_code == 200, approved.text
    return str(approved.json()["data"]["id"])


async def _setup(
    api: AsyncClient, db: AsyncSession, *, approve: bool = True
) -> tuple[str, dict[str, Candidate], str | None]:
    """A requirement with four candidates after screening: Ravi interested (completed), Priya
    interested but the call broke off, Amit not interested, Neha interested but opted out."""
    requirement = await _requirement(api, job_description=JD)
    rid = requirement["id"]
    await _confirm(api, (await _import(api, rid, CSV))["id"])
    rows = (await db.execute(select(Candidate).where(Candidate.requirement_id == rid))).scalars()
    people = {c.name.split()[0].lower(): c for c in rows}
    for name, interested, status in (
        ("ravi", True, "completed"),
        ("priya", True, "partially_completed"),
        ("amit", False, "completed"),
        ("neha", True, "completed"),
    ):
        people[name].interested, people[name].screening_status = interested, status
    people["neha"].opted_out = True
    await db.commit()
    set_id = await _approve(api, rid, QUESTION) if approve else None
    return rid, people, set_id


async def _call(api: AsyncClient, rid: str, **body: Any) -> list[dict[str, Any]]:
    response = await api.post(f"/api/v1/requirements/{rid}/telephonic/calls", json=body)
    assert response.status_code == 202, response.text
    data: list[dict[str, Any]] = response.json()["data"]
    return data


def _codes(results: list[dict[str, Any]]) -> dict[str, str | None]:
    return {r["candidate_id"]: (r["error"] or {}).get("code") for r in results}


async def _telephonic(db: AsyncSession, candidate_id: uuid.UUID) -> list[CallAttempt]:
    rows = await db.execute(
        select(CallAttempt)
        .where(CallAttempt.candidate_id == candidate_id, CallAttempt.purpose == "telephonic")
        .order_by(CallAttempt.attempt_number)
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


def _ended(
    candidate: Candidate, number: int, status: str, *, purpose: str = "screening", **fields: Any
) -> CallAttempt:
    return CallAttempt(
        candidate_id=candidate.id,
        attempt_number=number,
        attempt_type=fields.pop("attempt_type", "manual"),
        purpose=purpose,
        provider="exotel",
        call_status=status,
        end_time=datetime.now(UTC),
        retry_evaluated_at=datetime.now(UTC),
        **fields,
    )


async def test_who_gets_the_telephonic_round(
    admin: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    rid, people, _ = await _setup(admin, db_session, approve=False)
    ids = [str(people[n].id) for n in ("ravi", "priya", "amit", "neha")]

    codes = _codes(await _call(admin, rid, candidate_ids=ids, dry_run=True))
    assert codes == {
        ids[0]: "no_approved_questions",
        ids[1]: "screening_not_completed",  # said interested, but the call broke off
        ids[2]: "not_interested",
        ids[3]: "opted_out",
    }

    await _approve(admin, rid, QUESTION)
    codes = _codes(await _call(admin, rid, candidate_ids=ids, dry_run=True))
    assert codes[ids[0]] is None

    # Nobody listed: everyone interested who hasn't had the round (only Ravi). Dry run: nothing
    # is queued.
    results = await _call(admin, rid, dry_run=True)
    assert [(r["candidate_id"], r["ok"]) for r in results] == [(ids[0], True)]
    assert enqueued == []
    assert await _telephonic(db_session, people["ravi"].id) == []

    # Another opening's candidate isn't found here; an unknown requirement is a 404
    other = await _requirement(admin)
    preview = await _import(admin, other["id"], b"Name,Phone\nX Y,9876500001\n")
    await _confirm(admin, preview["id"])
    stranger = await db_session.scalar(
        select(Candidate.id).where(Candidate.requirement_id == other["id"])
    )
    codes = _codes(await _call(admin, rid, candidate_ids=[str(stranger)], dry_run=True))
    assert codes == {str(stranger): "candidate_not_found"}
    response = await admin.post(
        f"/api/v1/requirements/{uuid.uuid4()}/telephonic/calls", json={"dry_run": True}
    )
    assert response.status_code == 404


async def test_a_call_pins_the_approved_set(
    admin: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    rid, people, v1 = await _setup(admin, db_session)
    ravi = people["ravi"]

    (result,) = await _call(admin, rid)
    assert result["ok"], result
    (attempt,) = await _telephonic(db_session, ravi.id)
    assert enqueued == [str(attempt.id)]
    assert (attempt.call_status, attempt.attempt_type, str(attempt.question_set_id)) == (
        "queued",
        "manual",
        v1,
    )

    # A later approval doesn't change the queued call
    v2 = await _approve(admin, rid, "How do you handle a customer who says it's too costly?")
    assert v2 != v1
    await db_session.refresh(attempt)
    assert str(attempt.question_set_id) == v1

    detail = (await admin.get(f"/api/v1/calls/{attempt.id}")).json()["data"]
    assert (detail["purpose"], detail["question_set_id"]) == ("telephonic", v1)

    # The calls list splits by purpose; a round call names the job and the version it asks
    db_session.add(_ended(people["amit"], 1, "completed"))
    await db_session.commit()
    (listed_round,) = (await admin.get("/api/v1/calls", params={"purpose": "telephonic"})).json()[
        "data"
    ]
    requirement = await db_session.get(Requirement, uuid.UUID(rid))
    assert requirement is not None
    assert listed_round["id"] == str(attempt.id)
    assert listed_round["round"] == {
        "requirement_id": rid,
        "client_id": str(requirement.client_id),
        "title": "Sales Executive",
        "version": 1,
    }
    (listed_screening,) = (
        await admin.get("/api/v1/calls", params={"purpose": "screening"})
    ).json()["data"]
    assert (listed_screening["purpose"], listed_screening["round"]) == ("screening", None)
    everything = (await admin.get("/api/v1/calls")).json()["meta"]["total"]
    assert everything == 2

    # One live call per candidate; "everyone not called" no longer includes Ravi
    codes = _codes(await _call(admin, rid, candidate_ids=[str(ravi.id)]))
    assert codes == {str(ravi.id): "call_already_active"}
    assert await _call(admin, rid) == []

    # The screening list doesn't show the telephonic call
    listed = await admin.get("/api/v1/candidates", params={"requirement_id": rid})
    row = next(r for r in listed.json()["data"] if r["id"] == str(ravi.id))
    assert row["last_call"] is None and row["retry_status"] is None


async def test_a_finished_round_needs_a_confirmation(
    admin: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    rid, people, v1 = await _setup(admin, db_session)
    ravi = people["ravi"]
    db_session.add(
        _ended(
            ravi,
            1,
            "completed",
            purpose="telephonic",
            question_set_id=uuid.UUID(v1 or ""),
            end_reason="agent_completed",
        )
    )
    await db_session.commit()
    v2 = await _approve(admin, rid, "How do you handle a customer who says it's too costly?")

    assert await _call(admin, rid) == []  # already had the round
    codes = _codes(await _call(admin, rid, candidate_ids=[str(ravi.id)]))
    assert codes == {str(ravi.id): "telephonic_done"}

    (result,) = await _call(admin, rid, candidate_ids=[str(ravi.id)], call_again=True)
    assert result["ok"], result
    _, again = await _telephonic(db_session, ravi.id)
    assert str(again.question_set_id) == v2  # a new call asks the latest approved set


async def test_attempts_are_counted_per_purpose(
    admin: AsyncClient, db_session: AsyncSession, enqueued: list[str]
) -> None:
    rid, people, v1 = await _setup(admin, db_session)
    ravi = people["ravi"]
    set_id = uuid.UUID(v1 or "")
    # Three screening calls (the maximum) don't use up the telephonic tries
    for n in (1, 2, 3):
        db_session.add(_ended(ravi, n, "no_answer"))
    await db_session.commit()
    (result,) = await _call(admin, rid, candidate_ids=[str(ravi.id)])
    assert result["ok"], result

    (attempt,) = await _telephonic(db_session, ravi.id)
    attempt.call_status, attempt.end_time = "no_answer", datetime.now(UTC)
    attempt.retry_evaluated_at = datetime.now(UTC)
    for n in (5, 6):
        db_session.add(_ended(ravi, n, "busy", purpose="telephonic", question_set_id=set_id))
    await db_session.commit()

    counts = call_repo.attempt_counts
    assert (await counts(db_session, [ravi.id], purpose="screening"))[ravi.id] == (3, 0)
    assert (await counts(db_session, [ravi.id], purpose="telephonic"))[ravi.id] == (3, 0)
    assert (await counts(db_session, [ravi.id], purpose=None))[ravi.id] == (6, 0)

    codes = _codes(await _call(admin, rid, candidate_ids=[str(ravi.id)]))
    assert codes == {str(ravi.id): "max_attempts_reached"}
    (result,) = await _call(admin, rid, candidate_ids=[str(ravi.id)], override_limit=True)
    assert result["ok"], result


async def test_retries_keep_the_purpose(
    admin: AsyncClient,
    db_session: AsyncSession,
    enqueued: list[str],
    settings: Settings,
) -> None:
    rid, people, v1 = await _setup(admin, db_session)
    ravi = people["ravi"]
    db_session.add(
        _ended(ravi, 1, "completed", end_reason="agent_completed")  # the screening call
    )
    attempt = _ended(
        ravi, 2, "no_answer", purpose="telephonic", question_set_id=uuid.UUID(v1 or "")
    )
    attempt.retry_evaluated_at = None
    db_session.add(attempt)
    await db_session.commit()
    v2 = await _approve(admin, rid, "How do you handle a customer who says it's too costly?")

    effective = await settings_service.effective(db_session, settings)
    ev = await retry_service.evaluate(db_session, attempt.id, effective)
    assert ev.decision == "retry_scheduled"
    _, retry = await _telephonic(db_session, ravi.id)
    assert (retry.attempt_type, retry.call_status) == ("retry", "retry_scheduled")
    assert str(retry.question_set_id) == v2  # nothing was asked yet: the latest set

    # A callback resumes the same questions
    kept = await retry_service._next_question_set(
        db_session, attempt, ravi, CallAttemptType.CALLBACK
    )
    assert str(kept) == v1

    # The dispatcher re-checks the telephonic rules: no longer interested → cancelled
    await db_session.refresh(ravi)
    ravi.interested = False
    await db_session.commit()
    later = FrozenClock(datetime.now(UTC) + timedelta(days=10))
    out = await retry_service.dispatch_due(db_session, effective, _noop, clock=later)
    assert out.cancelled == 1
    await db_session.refresh(retry)
    assert (retry.call_status, retry.failure_reason) == ("cancelled", "ineligible:not_interested")


async def _noop(attempt_id: str) -> None:
    return None


async def test_worker_dials_and_the_screening_agent_never_runs(
    admin: AsyncClient,
    db_session: AsyncSession,
    enqueued: list[str],
    sessions: None,
    settings: Settings,
) -> None:
    rid, _, _ = await _setup(admin, db_session)
    (result,) = await _call(admin, rid)
    provider = FakeProvider()
    outcome = await call_worker.initiate_call(
        {"settings": settings, "telephony": provider}, result["call_attempt_id"]
    )
    assert outcome == "initiated"
    assert provider.placed == [result["call_attempt_id"]]

    # The call context is the round's, never the screening questions
    ctx = await wh.load_context(uuid.UUID(result["call_attempt_id"]), "sid", settings)
    assert ctx.telephonic is not None and ctx.job.questions == []
    assert [q.text for q in ctx.telephonic.questions] == [QUESTION]


@pytest.fixture
def sessions(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    @contextlib.asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    for module in (
        call_worker,
        wh,
        settings_service,
        transcript_service,
        screening_store,
        finalization_service,
        telephonic_finalization,
    ):
        monkeypatch.setattr(module, "get_sessionmaker", lambda: factory)


# --- Build step 2: the call's context, conversation and stored result ------------------------


async def _queued(
    admin: AsyncClient, db: AsyncSession
) -> tuple[str, dict[str, Candidate], CallAttempt]:
    rid, people, _ = await _setup(admin, db)
    (result,) = await _call(admin, rid)
    attempt = await db.get(CallAttempt, uuid.UUID(result["call_attempt_id"]))
    assert attempt is not None
    return rid, people, attempt


async def test_the_call_context(
    admin: AsyncClient, db_session: AsyncSession, enqueued: list[str], sessions: None
) -> None:
    rid, _, attempt = await _queued(admin, db_session)
    requirement = (await admin.get(f"/api/v1/requirements/{rid}")).json()["data"]
    client = await db_session.get(Client, uuid.UUID(requirement["client_id"]))
    assert client is not None
    jd = f"Join {client.name} Pvt Ltd in Pune. At {client.name.upper()} you will sell CRM."
    response = await admin.patch(
        f"/api/v1/requirements/{rid}", json={"job_description": jd, "skills": ["CRM"]}
    )
    assert response.status_code == 200, response.text
    await _approve(admin, rid, "A newer question that this queued call must not ask.")

    # Named client: the agent may say it; the JD is as written
    ctx = await telephonic_call.for_attempt(db_session, attempt)
    assert ctx.client_name == client.name and client.name in ctx.job_description
    assert [q.text for q in ctx.questions] == [QUESTION] and ctx.version == 1
    assert client.name in ctx.keyterms and "CRM" in ctx.keyterms and "Pune" in ctx.keyterms

    # Confidential client: never named, and taken out of the JD (any case, legal suffix too)
    client.is_confidential = True
    await db_session.commit()
    ctx = await telephonic_call.for_attempt(db_session, attempt)
    assert ctx.client_name is None and client.name not in ctx.keyterms
    assert ctx.job_description == "Join our client in Pune. At our client you will sell CRM."


async def test_a_callback_resumes_the_round(
    admin: AsyncClient, db_session: AsyncSession, enqueued: list[str], sessions: None
) -> None:
    _, people, first = await _queued(admin, db_session)
    first.call_status, first.end_reason = "completed", "callback_scheduled"
    first.retry_evaluated_at = datetime.now(UTC)
    answered = {"question_id": "x", "status": "answered", "answer": "A billing app."}
    qid = (await telephonic_call.for_attempt(db_session, first)).questions[0].id
    db_session.add(
        Conversation(
            call_attempt_id=first.id,
            extracted_data={"telephonic": {"answers": [answered | {"question_id": qid}]}},
        )
    )
    callback = _ended(
        people["ravi"],
        first.attempt_number + 1,
        "queued",
        purpose="telephonic",
        question_set_id=first.question_set_id,
        attempt_type="callback",
    )
    callback.retry_evaluated_at = None
    db_session.add(callback)
    await db_session.commit()

    ctx = await wh.load_context(callback.id, "sid", make_settings())
    assert ctx.candidate.call_kind == "callback"
    assert ctx.telephonic is not None
    assert ctx.telephonic.prior_answers[qid]["answer"] == "A billing app."


async def test_calling_again_after_a_finished_round_starts_fresh(
    admin: AsyncClient, db_session: AsyncSession, enqueued: list[str], sessions: None
) -> None:
    """Real call: "Call again" after a round that asked every question said "I only have 0
    questions left". A finished round is never resumed."""
    _, people, first = await _queued(admin, db_session)
    first.call_status, first.end_reason = "completed", "agent_completed"
    first.retry_evaluated_at = datetime.now(UTC)
    qid = (await telephonic_call.for_attempt(db_session, first)).questions[0].id
    answered = {"question_id": qid, "status": "partial", "answer": "Software."}
    db_session.add(
        Conversation(
            call_attempt_id=first.id, extracted_data={"telephonic": {"answers": [answered]}}
        )
    )
    again = _ended(
        people["ravi"],
        first.attempt_number + 1,
        "queued",
        purpose="telephonic",
        question_set_id=first.question_set_id,
    )
    again.retry_evaluated_at = None
    db_session.add(again)
    await db_session.commit()

    ctx = await wh.load_context(again.id, "sid", make_settings())
    assert ctx.candidate.call_kind == "first"
    assert ctx.telephonic is not None and ctx.telephonic.prior_answers == {}


async def test_the_conversation_built_for_a_round(
    admin: AsyncClient,
    db_session: AsyncSession,
    enqueued: list[str],
    sessions: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tests.unit.voice.session_harness import FakeSTT, FakeTTS, Harness

    _, _, attempt = await _queued(admin, db_session)
    monkeypatch.setattr(wh, "create_stt_provider", lambda settings, keyterms=(): FakeSTT())
    h = Harness(attempt_id=str(attempt.id))  # only for its fake line parts
    parts: dict[str, Any] = {"sender": h.sender, "inbound": h.inbound, "marks": h.marks}

    # No AI key: no call (the screening model is never used instead)
    built = await wh.build_conversation(
        make_settings(), str(attempt.id), "sid", tts=FakeTTS(), **parts
    )
    assert built == "llm_not_configured"

    # Even with the trial realtime engine selected, the round runs the pipeline
    settings = make_settings(groq_api_key="gsk-test", voice_engine="realtime")
    built = await wh.build_conversation(settings, str(attempt.id), "sid", tts=FakeTTS(), **parts)
    assert isinstance(built, wh.Conversation)
    try:
        session = built.session
        assert isinstance(session.manager, TelephonicManager)  # type: ignore[union-attr]
        assert session.settings.max_call_duration_s == settings.telephonic_max_call_duration_s
        assert session.settings.call_wrap_up_s == settings.telephonic_wrap_up_s
        assert session.settings.silence_timeout_s == settings.telephonic_silence_timeout_s == 12
    finally:
        await built.llm.aclose()


async def test_the_round_result_is_stored_apart_from_screening(
    admin: AsyncClient, db_session: AsyncSession, enqueued: list[str], sessions: None
) -> None:
    _, people, attempt = await _queued(admin, db_session)
    ravi = people["ravi"]
    answers = [{"question_id": "q1", "question": QUESTION, "status": "answered", "answer": "Hi"}]
    result = TelephonicResult(
        end_reason=EndReason.OPTED_OUT,
        question_set_id=str(attempt.question_set_id),
        version=1,
        answers=answers,
        candidate_questions=["salary"],
        callback={},
        opted_out=True,
        declined_round=False,
        identity_confirmed=True,
        escalation_reason=None,
        all_asked=True,
        transcript=[{"seq": 1, "speaker": "assistant", "text": "Hello?"}],
        turns=1,
        llm_calls=1,
        llm_errors=0,
        input_tokens=1,
        output_tokens=1,
    )
    await screening_store.store_telephonic_outcome(
        attempt_id=attempt.id, candidate_id=ravi.id, result=result, extra={"end_reason": "x"}
    )
    conv = await db_session.scalar(
        select(Conversation)
        .where(Conversation.call_attempt_id == attempt.id)
        .execution_options(populate_existing=True)
    )
    assert conv is not None
    data = conv.extracted_data
    assert data["telephonic"] == {
        "question_set_id": str(attempt.question_set_id),
        "version": 1,
        "answers": answers,
        "candidate_questions": ["salary"],
    }
    assert data["result"]["purpose"] == "telephonic" and not conv.screening_completed
    await db_session.refresh(ravi)
    assert ravi.opted_out and ravi.screening_status == "completed"  # screening untouched

    # Finalization: kept apart from screening (no fields merged, status unchanged), summary
    outcome = await finalization_service.finalize_attempt(
        attempt.id, settings=make_settings(**EXOTEL), llm=None
    )
    assert outcome == "finalized"
    await db_session.refresh(ravi)
    assert ravi.interested is True and ravi.screening_status == "completed"
    assert ravi.current_company is None and ravi.screening_field_meta in (None, {})
    await db_session.refresh(conv)
    assert conv.finalized_at is not None and "final" not in conv.extracted_data
    assert conv.summary == (
        "Telephonic round (questions v1). 1 of 1 question answered. The candidate asked "
        "about: salary. The candidate asked not to be called again."
    )


# --- Build step 3: finalization, retries, and screening numbers unchanged ----------------------


def _round(
    attempt: CallAttempt,
    end: EndReason,
    statuses: list[str],
    **fields: Any,
) -> TelephonicResult:
    answers = [
        {"question_id": f"q{n}", "question": f"Q{n}", "status": st, "answer": "words"}
        for n, st in enumerate(statuses, start=1)
    ]
    values: dict[str, Any] = {
        "end_reason": end,
        "question_set_id": str(attempt.question_set_id),
        "version": 1,
        "answers": answers,
        "candidate_questions": [],
        "callback": {},
        "opted_out": False,
        "declined_round": False,
        "identity_confirmed": True,
        "escalation_reason": None,
        "all_asked": "not_asked" not in statuses,
        "transcript": [{"seq": 1, "speaker": "assistant", "text": "Hello?"}],
        "turns": 5,
        "llm_calls": 5,
        "llm_errors": 0,
        "input_tokens": 1,
        "output_tokens": 1,
    } | fields
    return TelephonicResult(**values)


async def _answered(db: AsyncSession, attempt: CallAttempt, result: TelephonicResult) -> str:
    """The call was answered and ended; the round's result is stored, then finalized."""
    now = datetime.now(UTC)
    attempt.call_status, attempt.stream_id = "completed", "stream-1"
    attempt.start_time, attempt.end_time = now - timedelta(minutes=8), now
    attempt.duration_seconds = 480
    await db.commit()
    await screening_store.store_telephonic_outcome(
        attempt_id=attempt.id, candidate_id=attempt.candidate_id, result=result
    )
    return await finalization_service.finalize_attempt(
        attempt.id, settings=make_settings(**EXOTEL), llm=None
    )


async def test_a_finished_round(
    admin: AsyncClient, db_session: AsyncSession, enqueued: list[str], sessions: None
) -> None:
    rid, people, attempt = await _queued(admin, db_session)
    statuses = ["answered", "partial", "declined", "dont_know"]
    result = _round(attempt, EndReason.COMPLETED, statuses)
    assert await _answered(db_session, attempt, result) == "finalized"
    await db_session.refresh(attempt)
    assert (attempt.end_reason, attempt.retry_decision) == ("agent_completed", "no_retry:completed")
    conv = await db_session.scalar(
        select(Conversation)
        .where(Conversation.call_attempt_id == attempt.id)
        .execution_options(populate_existing=True)
    )
    assert conv is not None and conv.summary == (
        "Telephonic round (questions v1). 1 of 4 questions answered, 1 partly, 1 didn't know, "
        "1 refused. The round was completed."
    )
    # Done: another round needs the recruiter's confirmation
    codes = _codes(await _call(admin, rid, candidate_ids=[str(people["ravi"].id)]))
    assert codes == {str(people["ravi"].id): "telephonic_done"}
    # Finalizing again changes nothing
    again = await finalization_service.finalize_attempt(
        attempt.id, settings=make_settings(**EXOTEL), llm=None
    )
    assert again == "already_done"


async def test_a_round_callback_resumes_the_same_questions(
    admin: AsyncClient, db_session: AsyncSession, enqueued: list[str], sessions: None
) -> None:
    _, people, attempt = await _queued(admin, db_session)
    when = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0)
    callback = {
        "requested": True,
        "time_text": "tomorrow",
        "time_iso": when.isoformat(),
        "needs_recruiter": False,
        "time_asked": False,
    }
    result = _round(attempt, EndReason.CALLBACK, ["answered", "not_asked"], callback=callback)
    assert await _answered(db_session, attempt, result) == "finalized"
    _, nxt = await _telephonic(db_session, people["ravi"].id)
    assert (nxt.attempt_type, nxt.call_status) == ("callback", "callback_requested")
    assert nxt.question_set_id == attempt.question_set_id and nxt.next_retry_at == when
    conv = await db_session.scalar(
        select(Conversation)
        .where(Conversation.call_attempt_id == attempt.id)
        .execution_options(populate_existing=True)
    )
    assert conv is not None and "They asked to be called back (tomorrow)." in (conv.summary or "")


@pytest.mark.parametrize(
    ("end", "statuses", "decision"),
    [
        (EndReason.HANGUP, ["answered", "not_asked"], "no_retry:partial"),
        (EndReason.MAX_TURNS, ["answered", "not_asked"], "no_retry:partial"),
        (EndReason.DECLINED, ["not_asked", "not_asked"], "no_retry:declined"),
        (EndReason.NO_RESPONSE, ["not_asked", "not_asked"], "retry_scheduled"),
    ],
)
async def test_how_a_round_ends_decides_the_retry(
    admin: AsyncClient,
    db_session: AsyncSession,
    enqueued: list[str],
    sessions: None,
    end: EndReason,
    statuses: list[str],
    decision: str,
) -> None:
    _, _, attempt = await _queued(admin, db_session)
    await _answered(db_session, attempt, _round(attempt, end, statuses))
    await db_session.refresh(attempt)
    assert attempt.retry_decision == decision


async def test_round_calls_never_change_the_screening_numbers(
    admin: AsyncClient, db_session: AsyncSession, enqueued: list[str], sessions: None
) -> None:
    from app.services import dashboard_service

    rid, people, _ = await _setup(admin, db_session)
    db_session.add(_ended(people["ravi"], 1, "completed", end_reason="agent_completed"))
    await db_session.commit()

    async def numbers() -> dict[str, Any]:
        stats = await dashboard_service.stats(db_session, tz="Asia/Kolkata")
        summary = await dashboard_service.summary(db_session, tz="Asia/Kolkata")
        listed = await admin.get("/api/v1/candidates", params={"requirement_id": rid})
        rows = {r["id"]: r["last_call"] for r in listed.json()["data"]}
        stats.pop("generated_at")
        return {
            "stats": stats,
            "kpis": summary["kpis"],
            "funnel": summary["funnel"],
            "outcomes": summary["outcomes"],
            "live": summary["live_calls"],
            "rows": rows,
            "activity": len(await dashboard_service.activity(db_session)),
            "latest": summary["latest_conversation"],
        }

    before = await numbers()
    (result,) = await _call(admin, rid)  # a queued telephonic call
    attempt = await db_session.get(CallAttempt, uuid.UUID(result["call_attempt_id"]))
    assert attempt is not None
    assert await numbers() == before
    await _answered(db_session, attempt, _round(attempt, EndReason.NO_RESPONSE, ["not_asked"]))
    after = await numbers()  # ended, and a telephonic retry is now scheduled
    assert after == before


# --- Build step 4: the roster and a call's answers (the UI's data) -----------------------------


async def test_the_roster_and_a_calls_answers(
    admin: AsyncClient, db_session: AsyncSession, enqueued: list[str], sessions: None
) -> None:
    rid, people, _ = await _setup(admin, db_session)
    url = f"/api/v1/requirements/{rid}/telephonic/candidates"

    async def roster() -> dict[str, Any]:
        response = await admin.get(url)
        assert response.status_code == 200, response.text
        data: dict[str, Any] = response.json()["data"]
        return data

    data = await roster()
    rows = {r["name"].split()[0].lower(): r for r in data["rows"]}
    assert data["approved_version"] == 1
    assert set(rows) == {"ravi", "priya", "neha"}  # interested only (Amit isn't)
    assert (rows["ravi"]["status"], rows["ravi"]["eligibility"]["can_call"]) == ("not_called", True)
    assert rows["priya"]["eligibility"]["reason"] == "screening_not_completed"
    assert rows["neha"]["eligibility"]["reason"] == "opted_out"

    def ravi_of(data: dict[str, Any]) -> dict[str, Any]:
        row: dict[str, Any] = next(r for r in data["rows"] if r["name"] == "Ravi Kumar")
        return row

    (result,) = await _call(admin, rid)
    ravi = ravi_of(await roster())
    assert ravi["status"] == "queued" and ravi["last_call"]["version"] == 1

    attempt = await db_session.get(CallAttempt, uuid.UUID(result["call_attempt_id"]))
    assert attempt is not None
    await _answered(
        db_session, attempt, _round(attempt, EndReason.COMPLETED, ["answered", "dont_know"])
    )
    await _approve(admin, rid, "A newer question.")
    data = await roster()
    ravi = ravi_of(data)
    assert data["approved_version"] == 2
    assert (ravi["status"], ravi["done_before"]) == ("done", True)
    assert ravi["eligibility"]["reason"] == "telephonic_done"  # "call again" asks first
    last = ravi["last_call"]
    assert (last["version"], last["finalized"], last["answered"], last["questions"]) == (
        1,
        True,
        1,
        2,
    )

    answers = (await admin.get(f"/api/v1/calls/{attempt.id}/answers")).json()["data"]
    assert answers["version"] == 1 and answers["finalized"]
    assert [(a["question_id"], a["status"]) for a in answers["answers"]] == [
        ("q1", "answered"),
        ("q2", "dont_know"),
    ]
    assert answers["summary"].startswith("Telephonic round (questions v1).")

    screening = _ended(people["ravi"], 99, "completed")
    db_session.add(screening)
    await db_session.commit()
    response = await admin.get(f"/api/v1/calls/{screening.id}/answers")
    assert (response.status_code, response.json()["error"]["code"]) == (409, "not_telephonic")
    assert (await admin.get(f"/api/v1/calls/{uuid.uuid4()}/answers")).status_code == 404


def test_where_a_candidate_stands() -> None:
    from app.services.telephonic_calls import round_status

    def attempt(status: str, end: str | None = None) -> CallAttempt:
        return CallAttempt(call_status=status, end_reason=end)

    assert round_status(None) == "not_called"
    cases = {
        ("queued", None): "queued",
        ("ringing", None): "on_call",
        ("retry_scheduled", None): "retry_scheduled",
        ("callback_requested", None): "callback",
        ("busy", "busy"): "no_answer",
        ("exhausted", "no_answer"): "no_answer",
        ("exhausted", "technical_failure"): "failed",
        ("completed", "agent_completed"): "done",
        ("completed", "declined"): "declined",
        ("completed", "opted_out"): "opted_out",
        ("completed", "max_duration"): "incomplete",
        ("completed", "candidate_hangup"): "incomplete",
    }
    for (status, end), expected in cases.items():
        assert round_status(attempt(status, end)) == expected, (status, end)
