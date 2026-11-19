"""Phase 5 integration: calls API, eligibility, webhooks, worker, reconciler and the media stream,
against real Postgres and Redis. The provider and the WebSocket are fakes: this is a harness,
never evidence that a real call works (that's docs/telephony.md §3).
"""

import asyncio
import base64
import contextlib
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import WebSocketDisconnect
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import CallAttempt, Candidate, Conversation, WebhookEvent
from app.providers.telephony import stream_token, webhook_token
from app.providers.telephony.base import (
    ProviderCall,
    ProviderCallStatus,
    TelephonyProvider,
    TelephonyRejectedError,
    TelephonyTimeoutError,
)
from app.services import call_service, call_slots
from app.tests.conftest import make_settings
from app.utils.redis import get_redis
from app.voice import telephony_poc
from app.voice import websocket_handler as wh
from app.voice.audio_processor import InboundQueue
from app.workers import call_worker

EXOTEL = {
    "exotel_api_key": "key",
    "exotel_api_token": "token",
    "exotel_account_sid": "acct1",
    "exotel_subdomain": "api.in.exotel.com",
    "exotel_caller_id": "08000000000",
    "exotel_app_id": "12345",
    "public_backend_url": "https://tunnel.example.com",
    # Monday-Sunday, all day: tests don't depend on the clock unless they say so
    "calling_days": "mon,tue,wed,thu,fri,sat,sun",
    "calling_hour_start": 0,
    "calling_hour_end": 24,
}
FIXTURES = Path(__file__).parents[1] / "fixtures" / "exotel"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(**EXOTEL, telephony_capture_dir=str(tmp_path / "calls"))


@pytest.fixture(autouse=True)
async def _clean_slots(client: AsyncClient) -> AsyncIterator[None]:
    redis = get_redis()
    for key in await redis.keys("rcai:call:slot:*"):
        await redis.delete(key)
    yield
    for key in await redis.keys("rcai:call:slot:*"):
        await redis.delete(key)


@pytest.fixture
def sessions(db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """Code that opens its own sessions (worker, stream) gets the test's transactional one."""

    @contextlib.asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    for module in (call_worker, wh):
        monkeypatch.setattr(module, "get_sessionmaker", lambda: factory)


@pytest.fixture
def enqueued(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    jobs: list[str] = []

    async def fake(attempt_id: str, *, ignore_window: bool = False) -> None:
        jobs.append(attempt_id)

    monkeypatch.setattr("app.api.v1.calls.enqueue_initiate_call", fake)
    return jobs


async def _candidate(authed: AsyncClient, phone: str = "+91 90000 09001", **extra: Any) -> str:
    response = await authed.post(
        "/api/v1/candidates",
        json={
            "name": "Tester",
            "phone": phone,
            "applied_role": "Backend Developer",
            "consent_attested": True,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["data"]["id"])


async def _start(authed: AsyncClient, *ids: str) -> list[dict[str, Any]]:
    response = await authed.post("/api/v1/calls/start", json={"candidate_ids": list(ids)})
    assert response.status_code == 202, response.text
    data: list[dict[str, Any]] = response.json()["data"]
    return data


class FakeProvider(TelephonyProvider):
    name = "exotel"

    def __init__(self) -> None:
        self.placed: list[str] = []
        self.next_error: Exception | None = None
        self.statuses: dict[str, ProviderCallStatus | None] = {}

    async def initiate_call(
        self, *, to_phone: str, call_attempt_id: str, status_callback_url: str
    ) -> ProviderCall:
        self.placed.append(call_attempt_id)
        if self.next_error:
            raise self.next_error
        return ProviderCall(provider_call_id=f"sid-{call_attempt_id[:8]}", raw_status="queued")

    async def get_call_status(self, provider_call_id: str) -> ProviderCallStatus | None:
        return self.statuses.get(provider_call_id)

    async def find_calls(self, *, to_phone: str, since: datetime) -> list[ProviderCallStatus]:
        return []


# --- Calls API and eligibility ----------------------------------------------------------------


async def test_start_creates_queued_attempt_and_enqueues(
    authed: AsyncClient, active_job: dict[str, Any], enqueued: list[str]
) -> None:
    cid = await _candidate(authed)
    (result,) = await _start(authed, cid, cid)  # duplicate id in one request → one call
    assert result["ok"] is True
    assert enqueued == [result["call_attempt_id"]]
    attempt = (await authed.get(f"/api/v1/calls/{result['call_attempt_id']}")).json()["data"]
    assert attempt["call_status"] == "queued"
    assert (attempt["attempt_number"], attempt["attempt_type"]) == (1, "manual")
    listed = (await authed.get("/api/v1/calls", params={"candidate_id": cid})).json()
    assert listed["meta"]["total"] == 1


async def test_second_start_while_live_is_refused(
    authed: AsyncClient, active_job: dict[str, Any], enqueued: list[str]
) -> None:
    cid = await _candidate(authed)
    await _start(authed, cid)
    (again,) = await _start(authed, cid)
    assert again["ok"] is False and again["error"]["code"] == "call_already_active"
    assert len(enqueued) == 1


async def test_db_enforces_one_live_attempt(
    db_session: AsyncSession, authed: AsyncClient, active_job: dict[str, Any]
) -> None:
    from sqlalchemy.exc import IntegrityError

    cid = uuid.UUID(await _candidate(authed))
    db_session.add(
        CallAttempt(candidate_id=cid, attempt_number=1, provider="exotel", call_status="queued")
    )
    await db_session.flush()
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            db_session.add(
                CallAttempt(
                    candidate_id=cid, attempt_number=2, provider="exotel", call_status="ringing"
                )
            )


async def test_per_candidate_eligibility_errors(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
) -> None:
    ok_id = await _candidate(authed, "+91 90000 09002")
    opted = await _candidate(authed, "+91 90000 09003")
    await authed.patch(f"/api/v1/candidates/{opted}", json={"opted_out": True})
    no_consent = await _candidate(authed, "+91 90000 09004")
    row = await db_session.get(Candidate, uuid.UUID(no_consent))
    assert row is not None
    row.consent_at = None
    await db_session.flush()
    deleted = await _candidate(authed, "+91 90000 09005")
    await authed.delete(f"/api/v1/candidates/{deleted}")
    missing = str(uuid.uuid4())

    results = {
        r["candidate_id"]: r
        for r in await _start(authed, ok_id, opted, no_consent, deleted, missing)
    }
    assert results[ok_id]["ok"]
    assert results[opted]["error"]["code"] == "opted_out"
    assert results[no_consent]["error"]["code"] == "consent_missing"
    assert results[deleted]["error"]["code"] == "candidate_deleted"
    assert results[missing]["error"]["code"] == "candidate_not_found"
    assert len(enqueued) == 1


async def test_calling_window(db_session: AsyncSession) -> None:
    s = make_settings(
        **{
            **EXOTEL,
            "calling_days": "mon,tue,wed,thu,fri,sat",
            "calling_hour_start": 10,
            "calling_hour_end": 19,
        }
    )
    ist = timedelta(hours=5, minutes=30)
    monday_noon = datetime(2026, 11, 16, 12, 0, tzinfo=UTC) - ist
    assert call_service.in_calling_window(s, monday_noon)
    assert not call_service.in_calling_window(s, monday_noon + timedelta(hours=7))  # 19:00
    assert not call_service.in_calling_window(s, monday_noon - timedelta(hours=2, minutes=1))
    assert not call_service.in_calling_window(s, monday_noon + timedelta(days=6))  # Sunday


async def test_start_without_telephony_config(
    authed: AsyncClient, active_job: dict[str, Any], enqueued: list[str], settings: Settings
) -> None:
    settings.exotel_app_id = None
    cid = await _candidate(authed)
    (result,) = await _start(authed, cid)
    assert result["error"]["code"] == "telephony_not_configured"


async def test_calls_api_requires_login(api: AsyncClient) -> None:
    assert (await api.get("/api/v1/calls")).status_code == 401
    response = await api.post("/api/v1/calls/start", json={"candidate_ids": [str(uuid.uuid4())]})
    assert response.status_code == 401


# --- Worker -----------------------------------------------------------------------------------


async def _queued_attempt(authed: AsyncClient, enqueued: list[str], phone: str) -> str:
    cid = await _candidate(authed, phone)
    (result,) = await _start(authed, cid)
    return str(result["call_attempt_id"])


async def test_worker_places_call_and_holds_slot(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    aid = await _queued_attempt(authed, enqueued, "+91 90000 09010")
    provider = FakeProvider()
    ctx = {"settings": settings, "telephony": provider}
    assert await call_worker.initiate_call(ctx, aid) == "initiated"
    attempt = await db_session.get(CallAttempt, uuid.UUID(aid))
    assert attempt is not None
    assert attempt.call_status == "initiating" and attempt.provider_call_id == f"sid-{aid[:8]}"
    assert await call_slots.in_use(get_redis(), size=1) == [aid]
    # running the job again (a re-delivery) does nothing
    assert await call_worker.initiate_call(ctx, aid) == "skipped"
    assert provider.placed == [aid]


async def test_worker_waits_when_no_slot(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    sessions: None,
    settings: Settings,
) -> None:
    from arq import Retry

    first = await _queued_attempt(authed, enqueued, "+91 90000 09011")
    second = await _queued_attempt(authed, enqueued, "+91 90000 09012")
    ctx = {"settings": settings, "telephony": FakeProvider()}
    await call_worker.initiate_call(ctx, first)
    with pytest.raises(Retry):
        await call_worker.initiate_call(ctx, second)


async def test_worker_timeout_is_not_retried(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    aid = await _queued_attempt(authed, enqueued, "+91 90000 09013")
    provider = FakeProvider()
    provider.next_error = TelephonyTimeoutError("slow")
    assert await call_worker.initiate_call({"settings": settings, "telephony": provider}, aid) == (
        "timeout"
    )
    attempt = await db_session.get(CallAttempt, uuid.UUID(aid))
    assert attempt is not None
    assert (attempt.call_status, attempt.failure_reason) == ("initiating", "initiate_timeout")
    assert provider.placed == [aid]


async def test_worker_rejection_fails_and_releases(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    aid = await _queued_attempt(authed, enqueued, "+91 90000 09014")
    provider = FakeProvider()
    provider.next_error = TelephonyRejectedError("not verified", status_code=400)
    await call_worker.initiate_call({"settings": settings, "telephony": provider}, aid)
    attempt = await db_session.get(CallAttempt, uuid.UUID(aid))
    assert attempt is not None
    assert (attempt.call_status, attempt.end_reason) == ("failed", "provider_failed")
    assert await call_slots.in_use(get_redis(), size=1) == []


async def test_worker_rechecks_eligibility(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    cid = await _candidate(authed, "+91 90000 09015")
    (result,) = await _start(authed, cid)
    # Opted out behind the API's back (the API also cancels queued calls, phase-09 P9-T7)
    candidate = await db_session.get(Candidate, uuid.UUID(cid))
    assert candidate is not None
    candidate.opted_out = True
    await db_session.flush()
    provider = FakeProvider()
    out = await call_worker.initiate_call(
        {"settings": settings, "telephony": provider}, result["call_attempt_id"]
    )
    assert out == "cancelled" and provider.placed == []


async def test_api_opt_out_cancels_a_queued_call(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    cid = await _candidate(authed, "+91 90000 09016")
    (result,) = await _start(authed, cid)
    await authed.patch(f"/api/v1/candidates/{cid}", json={"opted_out": True})
    attempt = await db_session.get(CallAttempt, uuid.UUID(result["call_attempt_id"]))
    assert attempt is not None
    await db_session.refresh(attempt)
    assert (attempt.call_status, attempt.failure_reason) == ("cancelled", "opted_out")
    provider = FakeProvider()
    out = await call_worker.initiate_call(
        {"settings": settings, "telephony": provider}, result["call_attempt_id"]
    )
    assert out == "skipped" and provider.placed == []


async def test_reconciler_applies_provider_status(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    aid = await _queued_attempt(authed, enqueued, "+91 90000 09016")
    provider = FakeProvider()
    await call_worker.initiate_call({"settings": settings, "telephony": provider}, aid)
    attempt = await db_session.get(CallAttempt, uuid.UUID(aid))
    assert attempt is not None and attempt.provider_call_id
    provider.statuses[attempt.provider_call_id] = ProviderCallStatus(
        provider_call_id=attempt.provider_call_id,
        raw_status="no-answer",
        status="no_answer",
        end_reason="no_answer",
    )
    ctx = {"settings": settings, "telephony": provider}
    assert await call_worker.reconcile_calls(ctx) == 0  # not stuck yet
    later = datetime.now(UTC) + timedelta(minutes=3)
    assert await call_worker.reconcile_calls(ctx, now=later) == 1
    await db_session.refresh(attempt)
    assert (attempt.call_status, attempt.end_reason) == ("no_answer", "no_answer")
    assert await call_slots.in_use(get_redis(), size=1) == []


# --- Webhooks ---------------------------------------------------------------------------------


def _payload(name: str, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text())
    data.update(overrides)
    return data


async def _initiated(
    authed: AsyncClient,
    enqueued: list[str],
    db_session: AsyncSession,
    settings: Settings,
    phone: str,
) -> CallAttempt:
    aid = await _queued_attempt(authed, enqueued, phone)
    await call_worker.initiate_call({"settings": settings, "telephony": FakeProvider()}, aid)
    attempt = await db_session.get(CallAttempt, uuid.UUID(aid))
    assert attempt is not None
    return attempt


async def test_webhook_rejects_bad_token(api: AsyncClient) -> None:
    response = await api.post("/api/v1/webhooks/exotel/status/wrong", json={"CallSid": "x"})
    assert response.status_code == 403


async def test_webhook_lifecycle_dedupe_and_out_of_order(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    attempt = await _initiated(authed, enqueued, db_session, settings, "+91 90000 09020")
    url = f"/api/v1/webhooks/exotel/status/{webhook_token(settings)}"
    sid = attempt.provider_call_id
    answered = _payload("docs_status_answered.json", CallSid=sid)
    terminal = _payload("docs_status_terminal.json", CallSid=sid)
    # Exotel sends no Origin header; the CSRF guard must not apply here
    no_origin = {"Origin": ""}

    r = await authed.post(url, json=answered, headers=no_origin)
    assert r.json()["outcome"] == "applied"
    await db_session.refresh(attempt)
    assert attempt.call_status == "in_progress"

    # The stream connected, so a completed call is a normal hang-up
    attempt.stream_id = "s1"
    await db_session.flush()
    assert (await authed.post(url, json=terminal)).json()["outcome"] == "applied"
    assert (await authed.post(url, json=terminal)).json()["outcome"] == "duplicate"
    late = _payload("docs_status_answered.json", CallSid=sid, DateUpdated="2026-11-18 15:06:00")
    assert (await authed.post(url, json=late)).json()["outcome"] == "ignored"

    await db_session.refresh(attempt)
    assert attempt.call_status == "completed"
    assert attempt.end_reason == "candidate_hangup"
    assert attempt.duration_seconds == 320
    assert attempt.provider_status == "completed"
    events = (
        (await db_session.execute(select(WebhookEvent).where(WebhookEvent.provider_call_id == sid)))
        .scalars()
        .all()
    )
    assert len(events) == 3  # the duplicate isn't stored twice
    assert await call_slots.in_use(get_redis(), size=1) == []


async def test_webhook_completed_without_stream_is_technical_failure(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    attempt = await _initiated(authed, enqueued, db_session, settings, "+91 90000 09021")
    url = f"/api/v1/webhooks/exotel/status/{webhook_token(settings)}"
    await authed.post(
        url, json=_payload("docs_status_terminal.json", CallSid=attempt.provider_call_id)
    )
    await db_session.refresh(attempt)
    assert (attempt.call_status, attempt.end_reason) == ("completed", "technical_failure")
    assert attempt.failure_reason == "stream_never_connected"


async def test_webhook_busy_and_custom_field_fallback(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    aid = await _queued_attempt(authed, enqueued, "+91 90000 09022")
    provider = FakeProvider()
    provider.next_error = TelephonyTimeoutError("slow")  # we never learned the CallSid
    await call_worker.initiate_call({"settings": settings, "telephony": provider}, aid)
    url = f"/api/v1/webhooks/exotel/status/{webhook_token(settings)}"
    busy = _payload(
        "docs_status_terminal.json",
        CallSid="sid-new",
        Status="busy",
        CustomField=aid,
        ConversationDuration=0,
    )
    assert (await authed.post(url, json=busy)).json()["outcome"] == "applied"
    attempt = await db_session.get(CallAttempt, uuid.UUID(aid))
    assert attempt is not None
    await db_session.refresh(attempt)
    assert (attempt.call_status, attempt.end_reason, attempt.provider_call_id) == (
        "busy",
        "busy",
        "sid-new",
    )


async def test_webhook_unknown_call_and_form_encoding(
    api: AsyncClient, settings: Settings, db_session: AsyncSession
) -> None:
    url = f"/api/v1/webhooks/exotel/status/{webhook_token(settings)}"
    r = await api.post(
        url,
        data={
            "CallSid": "nobody",
            "Status": "completed",
            "DateUpdated": "2026-11-18 10:00:00",
            "Legs[0][Status]": "completed",
        },
    )
    assert r.status_code == 200 and r.json()["outcome"] == "unknown_call"
    event = (
        await db_session.execute(
            select(WebhookEvent).where(WebhookEvent.provider_call_id == "nobody")
        )
    ).scalar_one()
    assert event.error == "unknown_call"
    assert event.payload["Legs"] == [{"Status": "completed"}]


async def test_two_calls_events_land_on_their_own_attempts(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    s2 = make_settings(**{**EXOTEL, "max_concurrent_calls": 2})
    first = await _initiated(authed, enqueued, db_session, s2, "+91 90000 09030")
    second = await _initiated(authed, enqueued, db_session, s2, "+91 90000 09031")
    url = f"/api/v1/webhooks/exotel/status/{webhook_token(settings)}"
    await authed.post(
        url,
        json=_payload(
            "docs_status_terminal.json", CallSid=second.provider_call_id, Status="no-answer"
        ),
    )
    await db_session.refresh(first)
    await db_session.refresh(second)
    assert (first.call_status, second.call_status) == ("initiating", "no_answer")


# --- Media stream -----------------------------------------------------------------------------


class FakeWebSocket:
    """Feeds scripted messages; records what the handler sends."""

    def __init__(self, messages: list[dict[str, Any]], app_state: Any, *, hold: bool = False):
        self._incoming: asyncio.Queue[str | None] = asyncio.Queue()
        for m in messages:
            self._incoming.put_nowait(json.dumps(m))
        if not hold:
            self._incoming.put_nowait(None)
        self.sent: list[dict[str, Any]] = []
        self.closed: int | None = None
        self.accepted = False
        self.app = type("App", (), {"state": app_state})()

    def feed(self, message: dict[str, Any] | None) -> None:
        self._incoming.put_nowait(json.dumps(message) if message else None)

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        item = await self._incoming.get()
        if item is None:
            raise WebSocketDisconnect(1000)
        return item

    async def send_text(self, text: str) -> None:
        self.sent.append(json.loads(text))

    async def close(self, code: int = 1000) -> None:
        self.closed = code
        self._incoming.put_nowait(None)


def _stream_messages(call_sid: str, *, rate: str = "8000") -> list[dict[str, Any]]:
    seq: list[dict[str, Any]] = json.loads((FIXTURES / "docs_stream_sequence.json").read_text())
    seq[1]["start"]["call_sid"] = call_sid
    seq[1]["start"]["media_format"]["sample_rate"] = rate
    seq[-1]["stop"]["call_sid"] = call_sid
    tone = base64.b64encode(b"\x10\x00" * 1600).decode()
    for m in seq:
        if m["event"] == "media":
            m["media"]["payload"] = tone
    return seq


class _State:
    tts = None  # beeps only: no voice model in tests


async def test_stream_caller_hangup_cleans_up(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    attempt = await _initiated(authed, enqueued, db_session, settings, "+91 90000 09040")
    await get_redis().set(wh.POC_MODE_KEY.format(attempt_id=attempt.id), "listen")
    ws = FakeWebSocket(_stream_messages(attempt.provider_call_id or ""), _State())
    await wh.handle_exotel_stream(ws, settings)  # type: ignore[arg-type]

    await db_session.refresh(attempt)
    assert attempt.call_status == "in_progress"  # terminal status comes from the webhook
    assert (attempt.stream_id, attempt.end_reason) == ("docs-stream-1", "candidate_hangup")
    assert str(attempt.id) not in wh.SESSIONS
    assert await call_slots.in_use(get_redis(), size=1) == []
    capture = json.loads(
        (Path(settings.telephony_capture_dir or "") / f"{attempt.id}_stream.json").read_text()
    )
    summary = capture["summary"]
    assert summary["counts"] == {"connected": 1, "start": 1, "media": 2, "dtmf": 1, "stop": 1}
    assert summary["media_chunk_sizes"] == {"3200": 2}
    assert summary["ended_by"] == "caller" and summary["mode"] == "listen"
    assert any("stop received: callended" in n for n in summary["notes"])
    assert summary["tasks_after"] <= summary["tasks_before"]
    assert "payload" not in json.dumps(capture["first_shapes"]).replace('"payload": "str', "")
    assert "9000009001" not in json.dumps(capture) and "acct" not in json.dumps(capture)


async def test_stream_full_mode_hangs_up_from_backend(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(telephony_poc, "ECHO_SECONDS", 0.3)
    monkeypatch.setattr(telephony_poc, "ECHO_DELAY_S", 0.05)
    attempt = await _initiated(authed, enqueued, db_session, settings, "+91 90000 09041")
    await get_redis().set(wh.POC_MODE_KEY.format(attempt_id=attempt.id), "full")
    msgs = _stream_messages(attempt.provider_call_id or "")[:2]  # connected, start
    ws = FakeWebSocket(msgs, _State(), hold=True)

    async def answer_marks() -> None:
        # Exotel echoes each mark once the audio before it has played
        while ws.closed is None:
            for m in list(ws.sent):
                if m["event"] == "mark" and not m.get("_answered"):
                    m["_answered"] = True
                    ws.feed({"event": "mark", "stream_sid": "docs-stream-1", "mark": m["mark"]})
            await asyncio.sleep(0.02)

    helper = asyncio.create_task(answer_marks())
    await asyncio.wait_for(wh.handle_exotel_stream(ws, settings), 15)  # type: ignore[arg-type]
    helper.cancel()

    assert ws.closed == 1000
    media = [m for m in ws.sent if m["event"] == "media"]
    assert media and all(len(base64.b64decode(m["media"]["payload"])) == 3200 for m in media)
    assert all(m["stream_sid"] == "docs-stream-1" for m in ws.sent)
    assert [m["mark"]["name"] for m in ws.sent if m["event"] == "mark"] == ["intro", "bye"]
    await db_session.refresh(attempt)
    assert attempt.end_reason == "agent_completed"
    assert await call_slots.in_use(get_redis(), size=1) == []


async def test_stream_rejects_unknown_call_and_wrong_format(
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
) -> None:
    ws = FakeWebSocket(_stream_messages("no-such-call"), _State())
    await wh.handle_exotel_stream(ws, settings)  # type: ignore[arg-type]
    assert ws.closed == 1008

    attempt = await _initiated(authed, enqueued, db_session, settings, "+91 90000 09042")
    ws = FakeWebSocket(_stream_messages(attempt.provider_call_id or "", rate="16000"), _State())
    await wh.handle_exotel_stream(ws, settings)  # type: ignore[arg-type]
    assert ws.closed == 1003
    await db_session.refresh(attempt)
    assert attempt.stream_id is None


async def test_stream_route_rejects_bad_token(client: AsyncClient, settings: Settings) -> None:
    from starlette.testclient import TestClient

    app: Any = client.app  # type: ignore[attr-defined]
    with TestClient(app) as tc:
        with (
            pytest.raises(WebSocketDisconnect) as exc,
            tc.websocket_connect("/api/v1/webhooks/exotel/stream/wrong"),
        ):
            pass
        assert exc.value.code == 1008
    assert stream_token(settings) != "wrong"


def test_inbound_queue_drops_oldest() -> None:
    q = InboundQueue(max_bytes=1000)
    for i in range(5):
        q.put(bytes([i]) * 400)
    assert q.dropped_bytes == 1200  # three oldest chunks dropped
    assert q._chunks[0][0] == 3


# --- Replays of payloads captured on real calls (2026-11-19) ----------------------------------


def _captured_stream(call_sid: str) -> list[dict[str, Any]]:
    seq: list[dict[str, Any]] = json.loads(
        (FIXTURES / "captured_stream_caller_hangup.json").read_text()
    )
    real_sid = seq[1]["start"]["call_sid"]
    silence = base64.b64encode(b"\x00\x00" * 160).decode()  # 320 bytes, as Exotel sends
    text = json.dumps(seq).replace(real_sid, call_sid)
    seq = json.loads(text)
    for m in seq:
        if m["event"] == "media":
            m["media"]["payload"] = silence
    return seq


async def test_captured_stream_and_callback_replay(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    attempt = await _initiated(authed, enqueued, db_session, settings, "+91 90000 09050")
    await get_redis().set(wh.POC_MODE_KEY.format(attempt_id=attempt.id), "listen")
    ws = FakeWebSocket(_captured_stream(attempt.provider_call_id or ""), _State())
    await wh.handle_exotel_stream(ws, settings)  # type: ignore[arg-type]
    await db_session.refresh(attempt)
    assert attempt.stream_id is not None and attempt.end_reason == "candidate_hangup"

    # Exotel posts the default callback form-encoded, with only these three fields
    body = json.loads((FIXTURES / "captured_status_completed.json").read_text())
    body["CallSid"] = attempt.provider_call_id
    url = f"/api/v1/webhooks/exotel/status/{webhook_token(settings)}"
    assert (await authed.post(url, data=body)).json()["outcome"] == "applied"
    assert (await authed.post(f"/cb/{webhook_token(settings)}", data=body)).json()[
        "outcome"
    ] == "duplicate"
    await db_session.refresh(attempt)
    assert (attempt.call_status, attempt.provider_status) == ("completed", "completed")
    assert attempt.duration_seconds is not None  # from our own start/end times


async def test_captured_no_answer_callback(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    attempt = await _initiated(authed, enqueued, db_session, settings, "+91 90000 09051")
    body = json.loads((FIXTURES / "captured_status_no_answer.json").read_text())
    body["CallSid"] = attempt.provider_call_id
    await authed.post(f"/cb/{webhook_token(settings)}", data=body)
    await db_session.refresh(attempt)
    assert (attempt.call_status, attempt.end_reason) == ("no_answer", "no_answer")
    assert await call_slots.in_use(get_redis(), size=1) == []


async def test_stream_matches_by_custom_parameter_key(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    # After an initiate timeout we have no Sid; Exotel passes CustomField as a parameter *key*
    aid = await _queued_attempt(authed, enqueued, "+91 90000 09052")
    provider = FakeProvider()
    provider.next_error = TelephonyTimeoutError("slow")
    await call_worker.initiate_call({"settings": settings, "telephony": provider}, aid)
    await get_redis().set(wh.POC_MODE_KEY.format(attempt_id=aid), "listen")
    seq = _captured_stream("sid-from-exotel")
    seq[1]["start"]["custom_parameters"] = {aid.replace("-", ""): ""}
    await wh.handle_exotel_stream(FakeWebSocket(seq, _State()), settings)  # type: ignore[arg-type]
    attempt = await db_session.get(CallAttempt, uuid.UUID(aid))
    assert attempt is not None
    await db_session.refresh(attempt)
    assert attempt.provider_call_id == "sid-from-exotel" and attempt.stream_id is not None


# --- Phase 6: the screening conversation over the stream -------------------------------------


async def test_stream_runs_the_screening_conversation(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real stream (fake phone, STT, LLM and voice): greeting → answer → the agent closes and
    hangs up; transcript, result and end_reason are stored, the summary job is queued."""
    from app.services import screening_store, transcript_service
    from app.tests.unit.agent.stub_llm import ScriptedLLM, turn
    from app.tests.unit.voice.session_harness import FakeSTT, FakeTTS

    @contextlib.asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    for module in (transcript_service, screening_store):
        monkeypatch.setattr(module, "get_sessionmaker", lambda: factory)
    stt, llm = FakeSTT(), ScriptedLLM([turn(identity_confirmed=False)])
    monkeypatch.setattr(wh, "create_stt_provider", lambda *_a, **_k: stt)
    monkeypatch.setattr(wh, "create_llm_provider", lambda _s: llm)
    finalized: list[str] = []

    async def enqueue_finalize(attempt_id: str) -> None:
        finalized.append(attempt_id)

    monkeypatch.setattr(wh, "enqueue_finalize_call", enqueue_finalize)
    fast = settings.model_copy(update={"greeting_wait_ms": 50, "telephony_frame_bytes": 640})

    class State:
        tts = FakeTTS(ms_per_word=20)

    attempt = await _initiated(authed, enqueued, db_session, settings, "+91 90000 09060")
    ws = FakeWebSocket(_stream_messages(attempt.provider_call_id or "")[:2], State(), hold=True)

    async def phone() -> None:
        said = False
        while ws.closed is None:
            for m in list(ws.sent):
                if m["event"] == "mark" and not m.get("_answered"):
                    m["_answered"] = True
                    ws.feed({"event": "mark", "stream_sid": "docs-stream-1", "mark": m["mark"]})
                    if not said:  # the greeting has played: the candidate answers
                        said = True
                        await asyncio.sleep(0.05)
                        stt.say("No, you have the wrong number.")
            await asyncio.sleep(0.02)

    helper = asyncio.create_task(phone())
    await asyncio.wait_for(wh.handle_exotel_stream(ws, fast), 15)  # type: ignore[arg-type]
    helper.cancel()

    assert ws.closed == 1000  # the agent hung up
    assert {m["stream_sid"] for m in ws.sent} == {"docs-stream-1"}
    await db_session.refresh(attempt)
    assert attempt.end_reason == "wrong_person" and attempt.failure_reason is None
    assert finalized == [str(attempt.id)]
    assert str(attempt.id) not in wh.SESSIONS
    assert State.tts.forgotten == [str(attempt.id)]
    conv = (
        await db_session.execute(
            select(Conversation).where(Conversation.call_attempt_id == attempt.id)
        )
    ).scalar_one()
    assert [e["speaker"] for e in conv.transcript] == ["assistant", "candidate", "assistant"]
    assert conv.transcript[1]["text"] == "No, you have the wrong number."
    assert conv.extracted_data["result"]["end_reason"] == "wrong_person"
    assert conv.extracted_data["end_reason"] == "wrong_person"
    assert "live" in conv.extracted_data  # saved turn by turn during the call
    # The candidate record is written by finalization (the queued finalize_call job)
    from app.services import finalization_service

    monkeypatch.setattr(finalization_service, "get_sessionmaker", lambda: factory)
    await finalization_service.finalize_attempt(attempt.id, settings=settings, llm=None)
    candidate = await db_session.get(Candidate, attempt.candidate_id)
    assert candidate is not None
    await db_session.refresh(candidate)
    assert candidate.screening_status == "wrong_person"
    assert await call_slots.in_use(get_redis(), size=1) == []


async def test_stream_without_a_voice_is_a_technical_failure(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    attempt = await _initiated(authed, enqueued, db_session, settings, "+91 90000 09061")
    ws = FakeWebSocket(_stream_messages(attempt.provider_call_id or ""), _State())  # tts None
    await wh.handle_exotel_stream(ws, settings)  # type: ignore[arg-type]
    assert ws.closed == 1011
    await db_session.refresh(attempt)
    assert (attempt.end_reason, attempt.failure_reason) == (
        "technical_failure",
        "voice_unavailable",
    )


async def test_start_refused_while_the_voice_is_loading(
    authed: AsyncClient, active_job: dict[str, Any], enqueued: list[str], settings: Settings
) -> None:
    from app.providers.tts.base import ProviderStatus

    class Loading:
        def status(self) -> ProviderStatus:
            return ProviderStatus("deepgram", False, "loading")

    app: Any = authed.app  # type: ignore[attr-defined]
    cid = await _candidate(authed, "+91 90000 09062")
    original = (app.state.tts, settings.tts_preload)
    app.state.tts = Loading()
    object.__setattr__(settings, "tts_preload", True)
    try:
        (result,) = await _start(authed, cid)
    finally:
        app.state.tts = original[0]
        object.__setattr__(settings, "tts_preload", original[1])
    assert result["error"]["code"] == "voice_unavailable" and enqueued == []
