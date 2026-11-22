"""Phase 9 against Postgres and Redis: a no-answer webhook schedules a retry (P9-AC1), the
dispatcher dials only what's due and inside the window (P9-AC2), three misses exhaust the
attempts (P9-AC3), declined and opted-out candidates are never retried at any checkpoint
(P9-AC4), callbacks at the requested time or moved into the window (P9-AC5), and no duplicate
retries or dials (P9-AC6). The provider is a fake; real calls are in docs/retries.md."""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.agent.state import EndReason
from app.config import Settings
from app.database.models import (
    CallAttempt,
    Candidate,
    Conversation,
    Job,
    Organization,
    ScreeningStatus,
)
from app.providers.telephony import webhook_token
from app.services import (
    call_slots,
    call_state,
    finalization_service,
    retry_service,
    screening_store,
    settings_service,
)
from app.tests.conftest import make_settings
from app.tests.integration.test_telephony import EXOTEL, FakeProvider, _candidate, _start
from app.tests.unit.agent.results import make_result
from app.utils.calling_window import CallingWindow
from app.utils.clock import FrozenClock
from app.utils.redis import get_redis
from app.voice import websocket_handler as wh
from app.workers import call_worker, retry_worker

IST = ZoneInfo("Asia/Kolkata")
OFFICE = {
    "calling_days": "mon,tue,wed,thu,fri,sat",
    "calling_hour_start": 10,
    "calling_hour_end": 19,
}


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

    monkeypatch.setattr("app.api.v1.calls.enqueue_initiate_call", fake)
    return jobs


@pytest.fixture
def sessions(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    @contextlib.asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    for module in (
        call_worker,
        retry_worker,
        wh,
        finalization_service,
        screening_store,
        settings_service,
    ):
        monkeypatch.setattr(module, "get_sessionmaker", lambda: factory)


class Jobs:
    """A fake queue: records job ids like ARQ's (call:<attempt id>) and refuses duplicates."""

    def __init__(self, fail: bool = False) -> None:
        self.ids: list[str] = []
        self.fail = fail

    async def __call__(self, attempt_id: str) -> None:
        if self.fail:
            raise ConnectionError("redis down")
        job_id = f"call:{attempt_id}"
        if job_id not in self.ids:
            self.ids.append(job_id)


def ist(days_from_today: int, hour: int, minute: int = 0) -> datetime:
    today = datetime.now(IST).date()
    return datetime.combine(
        today + timedelta(days=days_from_today), datetime.min.time(), tzinfo=IST
    ).replace(hour=hour, minute=minute)


async def _dialed(
    authed: AsyncClient, db: AsyncSession, settings: Settings, phone: str
) -> CallAttempt:
    """A call placed through the API and the worker (status initiating, provider id set)."""
    cid = await _candidate(authed, phone)
    (result,) = await _start(authed, cid)
    await call_worker.initiate_call(
        {"settings": settings, "telephony": FakeProvider()}, result["call_attempt_id"]
    )
    attempt = await db.get(CallAttempt, uuid.UUID(result["call_attempt_id"]))
    assert attempt is not None
    await db.refresh(attempt)
    return attempt


async def _end(
    db: AsyncSession, attempt: CallAttempt, status: str, at: datetime, **fields: Any
) -> None:
    await db.refresh(attempt)
    if status in ("no_answer", "busy"):
        fields.setdefault("end_reason", status)  # as the webhook sets it
    assert call_state.transition(attempt, status, now=at, end_time=at, **fields), (
        attempt.call_status,
        status,
    )
    await db.commit()
    await call_slots.release(get_redis(), str(attempt.id), size=4)  # the line is free again


async def _attempts(db: AsyncSession, candidate_id: uuid.UUID) -> list[CallAttempt]:
    rows = await db.execute(
        select(CallAttempt)
        .where(CallAttempt.candidate_id == candidate_id)
        .order_by(CallAttempt.attempt_number)
        .execution_options(populate_existing=True)
    )
    return list(rows.scalars())


async def _effective(db: AsyncSession, settings: Settings) -> Settings:
    return await settings_service.effective(db, settings)


# --- P9-AC1: a no-answer webhook schedules a retry --------------------------------------------


async def test_no_answer_webhook_schedules_a_retry(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    attempt = await _dialed(authed, db_session, settings, "+91 90000 19001")
    sid, cid = attempt.provider_call_id, attempt.candidate_id
    url = f"/api/v1/webhooks/exotel/status/{webhook_token(settings)}"
    response = await authed.post(
        url,
        json={"CallSid": attempt.provider_call_id, "Status": "no-answer"},
        headers={"Origin": ""},
    )
    assert response.json()["outcome"] == "applied"

    first, retry = await _attempts(db_session, attempt.candidate_id)
    assert (first.call_status, first.retry_decision) == ("no_answer", "retry_scheduled")
    assert (retry.call_status, retry.attempt_type, retry.attempt_number) == (
        "retry_scheduled",
        "retry",
        2,
    )
    assert retry.retry_count == 1
    window = CallingWindow.from_settings(settings)
    assert first.end_time is not None and retry.next_retry_at is not None
    rules = retry_service.RetryRules.from_settings(await _effective(db_session, settings))
    expected = retry_service.retry_time(first.end_time, rules, window.half(first.end_time))
    assert retry.next_retry_at == expected
    # two calendar days later in IST, alternating to the other half of the day
    assert window.local(retry.next_retry_at).date() == (
        window.local(first.end_time).date() + timedelta(days=2)
    )
    assert window.half(retry.next_retry_at) != window.half(first.end_time)

    # The same webhook again (Exotel re-sends): nothing new. (The duplicate path rolls back
    # the request's session, which here is the test's: use the ids saved above.)
    await authed.post(url, json={"CallSid": sid, "Status": "no-answer"}, headers={"Origin": ""})
    assert len(await _attempts(db_session, cid)) == 2


# --- P9-AC2 / AC3: dispatch on the configured day; three misses → exhausted ------------------


async def test_three_misses_exhaust_the_attempts(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    effective = await _effective(db_session, settings)
    clock = FrozenClock(datetime.now(UTC))
    provider = FakeProvider()
    ctx = {"settings": settings, "telephony": provider}
    attempt = await _dialed(authed, db_session, settings, "+91 90000 19002")
    cid = attempt.candidate_id

    for n, status in ((1, "no_answer"), (2, "busy")):
        await _end(db_session, attempt, status, clock.now())
        ev = await retry_service.evaluate(db_session, attempt.id, effective, clock=clock)
        assert ev.decision == "retry_scheduled" and ev.new_attempt_id
        nxt = await db_session.get(CallAttempt, ev.new_attempt_id)
        assert nxt is not None and nxt.next_retry_at is not None

        # Not due yet: one minute before the time nothing is dispatched
        clock.set(nxt.next_retry_at - timedelta(minutes=1))
        jobs = Jobs()
        assert (
            await retry_service.dispatch_due(db_session, effective, jobs, clock=clock)
        ).queued == []
        # Two days later (P9-AC2): dispatched and dialed once
        clock.set(nxt.next_retry_at)
        assert nxt.next_retry_at - (attempt.end_time or clock.now()) >= timedelta(days=1)
        out = await retry_service.dispatch_due(db_session, effective, jobs, clock=clock)
        assert out.queued == [str(nxt.id)] and jobs.ids == [f"call:{nxt.id}"]
        assert await call_worker.initiate_call(ctx, str(nxt.id)) == "initiated"
        await db_session.refresh(nxt)
        assert nxt.call_status == "initiating" and nxt.attempt_number == n + 1
        attempt = nxt

    # Third miss on the last allowed attempt → exhausted, nothing scheduled
    await _end(db_session, attempt, "no_answer", clock.now())
    ev = await retry_service.evaluate(db_session, attempt.id, effective, clock=clock)
    assert ev.decision == "exhausted" and ev.new_attempt_id is None
    rows = await _attempts(db_session, cid)
    assert [a.call_status for a in rows] == ["no_answer", "busy", "exhausted"]
    assert rows[-1].end_reason == "no_answer"  # the reason stays
    assert [a.attempt_type for a in rows] == ["manual", "retry", "retry"]
    clock.advance(timedelta(days=10))
    assert (
        await retry_service.dispatch_due(db_session, effective, Jobs(), clock=clock)
    ).queued == []
    assert len(provider.placed) == 2  # the two retries (the first call used another fake)

    # Shown as exhausted on the list and in the attention list
    listed = (await authed.get("/api/v1/candidates")).json()["data"]
    row = next(r for r in listed if r["id"] == str(cid))
    assert row["retry_status"]["kind"] == "exhausted"
    assert row["retry_status"]["attempts_made"] == 3
    attention = (await authed.get("/api/v1/dashboard/attention")).json()["data"]
    assert any(
        i["candidate_id"] == str(cid) and i["reason"] == "attempts_exhausted" for i in attention
    )
    # A manual call needs the recruiter's override now
    started = await authed.post("/api/v1/calls/start", json={"candidate_ids": [str(cid)]})
    assert started.json()["data"][0]["error"]["code"] == "max_attempts_reached"
    forced = await authed.post(
        "/api/v1/calls/start", json={"candidate_ids": [str(cid)], "override_limit": True}
    )
    assert forced.json()["data"][0]["ok"] is True


async def test_dispatcher_window_and_pause(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    office = settings.model_copy(update=OFFICE)
    attempt = await _dialed(authed, db_session, settings, "+91 90000 19003")
    await _end(db_session, attempt, "no_answer", datetime.now(UTC))
    ev = await retry_service.evaluate(db_session, attempt.id, office)
    retry = await db_session.get(CallAttempt, ev.new_attempt_id)
    assert retry is not None and retry.next_retry_at is not None

    # Due on a Sunday at noon (not a calling day) → moved to Monday 10:00 IST, not dialed
    sunday = datetime(2026, 11, 22, 12, 0, tzinfo=IST)
    retry.next_retry_at = sunday - timedelta(hours=1)
    await db_session.commit()
    out = await retry_service.dispatch_due(db_session, office, Jobs(), clock=FrozenClock(sunday))
    assert (out.queued, out.moved) == ([], 1)
    await db_session.refresh(retry)
    assert retry.next_retry_at == datetime(2026, 11, 23, 10, 0, tzinfo=IST)
    assert retry.call_status == "retry_scheduled"

    # Paused: left scheduled, dispatched once calling resumes
    monday = datetime(2026, 11, 23, 10, 5, tzinfo=IST)
    paused = office.model_copy(update={"calling_enabled": False})
    out = await retry_service.dispatch_due(db_session, paused, Jobs(), clock=FrozenClock(monday))
    assert (out.queued, out.held) == ([], 1)
    jobs = Jobs()
    out = await retry_service.dispatch_due(db_session, office, jobs, clock=FrozenClock(monday))
    assert out.queued == [str(retry.id)]


async def test_retry_that_waited_past_the_window_is_rescheduled(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    attempt = await _dialed(authed, db_session, settings, "+91 90000 19004")
    await _end(db_session, attempt, "no_answer", datetime.now(UTC))
    ev = await retry_service.evaluate(db_session, attempt.id, settings)
    retry = await db_session.get(CallAttempt, ev.new_attempt_id)
    assert retry is not None
    call_state.transition(retry, "queued")
    await db_session.commit()
    # The window is closed whenever the worker picks it up: an empty day list isn't allowed,
    # so use a one-hour window that isn't now
    hour = (datetime.now(IST).hour + 12) % 23
    closed = settings.model_copy(update={"calling_hour_start": hour, "calling_hour_end": hour + 1})
    provider = FakeProvider()
    out = await call_worker.initiate_call(
        {"settings": closed, "telephony": provider}, str(retry.id)
    )
    assert out == "rescheduled" and provider.placed == []
    await db_session.refresh(retry)
    assert retry.call_status == "retry_scheduled"
    assert retry.next_retry_at is not None
    assert CallingWindow.from_settings(closed).contains(retry.next_retry_at)


# --- P9-AC4: declined and opted-out candidates are never retried -----------------------------


async def test_opt_out_at_every_checkpoint(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    provider = FakeProvider()
    ctx = {"settings": settings, "telephony": provider}

    async def scheduled(phone: str) -> tuple[Candidate, CallAttempt]:
        attempt = await _dialed(authed, db_session, settings, phone)
        await _end(db_session, attempt, "no_answer", datetime.now(UTC))
        ev = await retry_service.evaluate(db_session, attempt.id, settings)
        retry = await db_session.get(CallAttempt, ev.new_attempt_id)
        cand = await db_session.get(Candidate, attempt.candidate_id)
        assert retry is not None and cand is not None
        return cand, retry

    # 1. Scheduling: opted out before the attempt ended → no retry
    attempt = await _dialed(authed, db_session, settings, "+91 90000 19010")
    cand = await db_session.get(Candidate, attempt.candidate_id)
    assert cand is not None
    cand.opted_out = True
    await _end(db_session, attempt, "no_answer", datetime.now(UTC))
    ev = await retry_service.evaluate(db_session, attempt.id, settings)
    assert (ev.decision, ev.new_attempt_id) == ("no_retry:opted_out", None)

    # 2. Dispatch: opted out behind the API's back while a retry was scheduled → cancelled
    cand, retry = await scheduled("+91 90000 19011")
    cand.opted_out = True
    retry.next_retry_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()
    out = await retry_service.dispatch_due(db_session, settings, Jobs())
    assert (out.queued, out.cancelled) == ([], 1)
    await db_session.refresh(retry)
    assert (retry.call_status, retry.failure_reason) == ("cancelled", "ineligible:opted_out")

    # 3. Initiation: queued, then opted out → the worker cancels and never dials
    cand, retry = await scheduled("+91 90000 19012")
    call_state.transition(retry, "queued")
    cand.opted_out = True
    await db_session.commit()
    assert await call_worker.initiate_call(ctx, str(retry.id)) == "cancelled"
    assert provider.placed == []

    # The API opt-out cancels a scheduled retry in the same transaction (P9-T7)
    cand, retry = await scheduled("+91 90000 19013")
    response = await authed.patch(f"/api/v1/candidates/{cand.id}", json={"opted_out": True})
    assert response.status_code == 200
    await db_session.refresh(retry)
    assert (retry.call_status, retry.failure_reason) == ("cancelled", "opted_out")

    # Declined (a later screening status) also stops a scheduled retry at dispatch
    cand, retry = await scheduled("+91 90000 19014")
    cand.screening_status = ScreeningStatus.DECLINED.value
    retry.next_retry_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()
    out = await retry_service.dispatch_due(db_session, settings, Jobs())
    assert out.cancelled == 1
    await db_session.refresh(retry)
    assert retry.failure_reason == "ineligible:declined"


async def _conversation_call(
    authed: AsyncClient,
    db: AsyncSession,
    settings: Settings,
    phone: str,
    *,
    settings_page: dict[str, Any] | None = None,
    **result: Any,
) -> CallAttempt:
    """An answered call whose conversation ended with `result`, finalized like the worker does.
    `settings_page`: saved on the Settings page after dialing (finalization reads it)."""
    attempt = await _dialed(authed, db, settings, phone)
    if settings_page:
        response = await authed.patch("/api/v1/settings", json=settings_page)
        assert response.status_code == 200, response.text
    attempt.stream_id = "stream-1"
    call_state.transition(attempt, "in_progress")
    await db.commit()
    await screening_store.store_outcome(
        attempt_id=attempt.id, candidate_id=attempt.candidate_id, result=make_result(**result)
    )
    await _end(db, attempt, "completed", datetime.now(UTC), end_reason="agent_completed")
    # The webhook path waits for finalization
    ev = await retry_service.evaluate(db, attempt.id, settings)
    assert ev.decision == "awaiting_finalization"
    await finalization_service.finalize_attempt(attempt.id, settings=settings, llm=None)
    await db.refresh(attempt)
    return attempt


async def test_declined_call_is_not_retried(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    attempt = await _conversation_call(
        authed,
        db_session,
        settings,
        "+91 90000 19020",
        end_reason=EndReason.DECLINED,
        screening_status=ScreeningStatus.DECLINED,
        declined_opportunity=True,
    )
    assert attempt.retry_decision == "no_retry:declined"
    assert len(await _attempts(db_session, attempt.candidate_id)) == 1


# --- P9-AC5: callbacks ------------------------------------------------------------------------


def _callback(when: datetime, text: str) -> dict[str, Any]:
    return {
        "end_reason": EndReason.CALLBACK,
        "screening_status": ScreeningStatus.CALLBACK_REQUESTED,
        "callback": {"requested": True, "time_text": text, "time_iso": when.isoformat()},
    }


async def test_callback_at_the_requested_time(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    when = ist(1, 17)  # "tomorrow at 5 PM"
    attempt = await _conversation_call(
        authed, db_session, settings, "+91 90000 19030", **_callback(when, "tomorrow at 5")
    )
    assert attempt.retry_decision == "callback_scheduled"
    first, callback = await _attempts(db_session, attempt.candidate_id)
    assert (callback.call_status, callback.attempt_type) == ("callback_requested", "callback")
    assert callback.next_retry_at == when
    assert callback.retry_count == first.retry_count  # callbacks aren't retries

    overview = (await authed.get(f"/api/v1/candidates/{attempt.candidate_id}/overview")).json()
    status = overview["data"]["retry_status"]
    assert status["kind"] == "callback" and status["callbacks_made"] == 1
    assert datetime.fromisoformat(status["at"]) == when

    # The callback session resumes with what's known and the callback opener (P9-T6)
    ctx = await wh.load_context(callback.id, None, settings)
    assert ctx.candidate.call_kind == "callback"
    assert ctx.prior_fields["current_ctc"]["value"] == 12.0
    assert "declined" == ctx.prior_fields["notice_period"]["status"]


async def test_callback_outside_the_window_is_moved_and_noted(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    asked = ist(1, 21)  # 9 PM tomorrow: outside 10:00-19:00
    every_day = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    attempt = await _conversation_call(
        authed,
        db_session,
        settings,
        "+91 90000 19031",
        settings_page={"calling": {"days": every_day, "start_hour": 10, "end_hour": 19}},
        **_callback(asked, "tomorrow at 9 pm"),
    )
    _, callback = await _attempts(db_session, attempt.candidate_id)
    assert callback.next_retry_at == ist(2, 10)
    assert attempt.retry_note and "outside calling hours" in attempt.retry_note
    conv = (
        await db_session.execute(
            select(Conversation).where(Conversation.call_attempt_id == attempt.id)
        )
    ).scalar_one()
    await db_session.refresh(conv)
    assert conv.summary and "moved to" in conv.summary


async def test_vague_callback_and_callback_limit_go_to_attention(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    vague = await _conversation_call(
        authed,
        db_session,
        settings,
        "+91 90000 19032",
        end_reason=EndReason.CALLBACK,
        screening_status=ScreeningStatus.CALLBACK_REQUESTED,
        callback={"requested": True, "time_text": "later", "needs_recruiter": True},
    )
    assert vague.retry_decision == "no_retry:vague_callback"

    capped = await _conversation_call(
        authed,
        db_session,
        settings,
        "+91 90000 19033",
        settings_page={"retry": {"max_callbacks": 0}},
        **_callback(ist(1, 12), "tomorrow noon"),
    )
    assert capped.retry_decision == "no_retry:callback_limit"
    reasons = {
        (i["candidate_id"], i["reason"])
        for i in (await authed.get("/api/v1/dashboard/attention")).json()["data"]
    }
    assert (str(vague.candidate_id), "vague_callback") in reasons
    assert (str(capped.candidate_id), "callback_not_scheduled") in reasons


# --- P9-AC6: no duplicate retries -------------------------------------------------------------


async def test_worker_restart_mid_dispatch_never_dials_twice(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    attempt = await _dialed(authed, db_session, settings, "+91 90000 19040")
    await _end(db_session, attempt, "no_answer", datetime.now(UTC))
    ev = await retry_service.evaluate(db_session, attempt.id, settings)
    retry = await db_session.get(CallAttempt, ev.new_attempt_id)
    assert retry is not None
    retry.next_retry_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    # The queue is down: the attempt goes back on the schedule (5 minutes later)
    out = await retry_service.dispatch_due(db_session, settings, Jobs(fail=True))
    assert out.enqueue_failed == 1
    await db_session.refresh(retry)
    assert retry.call_status == "retry_scheduled"
    assert retry.next_retry_at is not None and retry.next_retry_at > datetime.now(UTC)

    # The worker stops after the commit, before the enqueue: the job is lost
    retry.next_retry_at = datetime.now(UTC) - timedelta(minutes=1)
    await db_session.commit()

    async def lost(attempt_id: str) -> None:
        return None

    await retry_service.dispatch_due(db_session, settings, lost)
    await db_session.refresh(retry)
    assert retry.call_status == "queued"
    # A dispatcher run before the stale limit leaves it alone
    jobs = Jobs()
    assert await retry_service.requeue_stale(db_session, jobs) == 0
    # After the restart, the next run enqueues it again, twice even: one job id
    later = FrozenClock(datetime.now(UTC) + timedelta(minutes=11))
    await retry_service.requeue_stale(db_session, jobs, clock=later)
    await retry_service.requeue_stale(db_session, jobs, clock=later)
    rid = str(retry.id)
    assert jobs.ids == [f"call:{rid}"]
    # Even if the job ran twice, only one call is placed
    provider = FakeProvider()
    ctx = {"settings": settings, "telephony": provider}
    assert await call_worker.initiate_call(ctx, rid) == "initiated"
    assert await call_worker.initiate_call(ctx, rid) == "skipped"
    assert provider.placed == [rid]


async def test_concurrent_evaluate_creates_one_attempt(migrated_database: str) -> None:
    """Two workers evaluate the same ended attempt at the same moment (separate connections,
    real commits): exactly one retry is created."""
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    settings = make_settings(**EXOTEL)
    phone = f"+9190000{uuid.uuid4().int % 100000:05d}"
    async with maker() as s:
        job = Job(job_title="Backend Developer", company_name="Test Co", is_active=True)
        org = Organization(name="Race Co")
        s.add_all([job, org])
        await s.flush()
        cand = Candidate(
            organization_id=org.id,
            name="Race Test",
            phone=phone,
            job_id=job.id,
            applied_role="Backend Developer",
            consent_at=datetime.now(UTC),
        )
        s.add(cand)
        await s.flush()
        attempt = CallAttempt(
            candidate_id=cand.id,
            attempt_number=1,
            provider="exotel",
            call_status="no_answer",
            end_time=datetime.now(UTC),
        )
        s.add(attempt)
        await s.commit()
        ids = (job.id, cand.id, attempt.id)
    try:

        async def run() -> retry_service.Evaluation:
            async with maker() as s:
                return await retry_service.evaluate(s, ids[2], settings)

        results = await asyncio.gather(*(run() for _ in range(4)))
        assert sorted(r.decision for r in results) == ["retry_scheduled"] * 4
        assert len({r.new_attempt_id for r in results if r.new_attempt_id}) == 1
        async with maker() as s:
            rows = list(
                (
                    await s.execute(select(CallAttempt).where(CallAttempt.candidate_id == ids[1]))
                ).scalars()
            )
        assert sorted(a.call_status for a in rows) == ["no_answer", "retry_scheduled"]
    finally:
        async with maker() as s:
            await s.execute(delete(CallAttempt).where(CallAttempt.candidate_id == ids[1]))
            await s.execute(delete(Candidate).where(Candidate.id == ids[1]))
            await s.execute(delete(Job).where(Job.id == ids[0]))
            await s.commit()
        await engine.dispose()


# --- Recruiter side ---------------------------------------------------------------------------


async def test_manual_call_replaces_a_scheduled_retry(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    attempt = await _dialed(authed, db_session, settings, "+91 90000 19050")
    await _end(db_session, attempt, "no_answer", datetime.now(UTC))
    ev = await retry_service.evaluate(db_session, attempt.id, settings)

    listed = (await authed.get("/api/v1/candidates")).json()["data"]
    row = next(r for r in listed if r["id"] == str(attempt.candidate_id))
    status = row["retry_status"]
    assert (status["kind"], status["attempt"], status["max_attempts"]) == ("retry", 2, 3)
    assert row["last_call"]["call_status"] == "no_answer"  # the dialed call, not the schedule
    assert row["eligibility"]["can_call"] is True  # a scheduled retry doesn't block "Call"

    (result,) = await _start(authed, str(attempt.candidate_id))
    assert result["ok"] is True
    retry = await db_session.get(CallAttempt, ev.new_attempt_id)
    assert retry is not None
    await db_session.refresh(retry)
    assert (retry.call_status, retry.failure_reason) == ("cancelled", "replaced_by_manual_call")
    rows = await _attempts(db_session, attempt.candidate_id)
    assert [a.call_status for a in rows] == ["no_answer", "cancelled", "queued"]


async def test_reconciler_evaluates_missed_attempts(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    """The webhook path failed: the cron finds the ended attempt and schedules the retry."""
    attempt = await _dialed(authed, db_session, settings, "+91 90000 19060")
    await _end(db_session, attempt, "busy", datetime.now(UTC))
    soon = FrozenClock(datetime.now(UTC) + timedelta(minutes=1))
    assert await retry_service.evaluate_pending(db_session, settings, clock=soon) == 0
    later = FrozenClock(datetime.now(UTC) + timedelta(minutes=3))
    assert await retry_service.evaluate_pending(db_session, settings, clock=later) >= 1
    await db_session.refresh(attempt)
    assert attempt.retry_decision == "retry_scheduled"
    # Through the cron entry point: nothing left to do for this one
    result = await retry_worker.dispatch_retries(
        {"settings": settings, "redis": _Pool(), "clock": later}
    )
    assert result["queued"] == 0


class _Pool:
    def __init__(self) -> None:
        self.jobs: list[tuple[Any, ...]] = []

    async def enqueue_job(self, *args: Any, **kwargs: Any) -> None:
        self.jobs.append((*args, kwargs.get("_job_id")))


async def test_settings_retry_section(
    authed: AsyncClient, active_job: dict[str, Any], db_session: AsyncSession, sessions: None
) -> None:
    response = await authed.patch("/api/v1/settings", json={"retry": {"enabled": False}})
    assert response.status_code == 200, response.text
    retry = response.json()["data"]["general"]["retry"]
    assert retry == {
        "max_attempts": 3,
        "interval_days": 2,
        "enabled": False,
        "max_callbacks": 2,
        "alternate_slots": True,
    }
    bad = await authed.patch("/api/v1/settings", json={"retry": {"interval_days": 5}})
    assert bad.status_code == 422
    bad = await authed.patch("/api/v1/settings", json={"retry": {"max_callbacks": 9}})
    assert bad.status_code == 422
