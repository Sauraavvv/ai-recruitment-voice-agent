"""Phase 8 call controls and settings: retry, cancel, dry run, eligibility on list rows, the
global pause (P8-AC7), settings validation, provider status without secrets (P8-AC6) and the
roles."""

import contextlib
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import CallAttempt, Conversation, User
from app.services import provider_status_service, settings_service
from app.tests.conftest import TEST_PASSWORD, make_settings
from app.tests.integration.test_telephony import EXOTEL, FakeProvider
from app.utils.redis import get_redis
from app.workers import call_worker

SECRETS = {
    "openai_api_key": "sk-test-SECRET-openai-0001",
    "openai_model": "gpt-test",
    "deepgram_api_key": "dg-SECRET-deepgram-0002",
    "exotel_api_key": "exo-SECRET-key-0003",
    "exotel_api_token": "exo-SECRET-token-0004",
}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(
        **{**EXOTEL, **SECRETS},
        telephony_capture_dir=str(tmp_path / "calls"),
    )


@pytest.fixture(autouse=True)
async def _clean_redis(client: AsyncClient) -> AsyncIterator[None]:
    redis = get_redis()
    patterns = ("rcai:call:slot:*", "rcai:provider-status:*")
    for pattern in patterns:
        for key in await redis.keys(pattern):
            await redis.delete(key)
    yield
    for pattern in patterns:
        for key in await redis.keys(pattern):
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

    for module in (call_worker, settings_service):
        monkeypatch.setattr(module, "get_sessionmaker", lambda: factory)


async def _candidate(authed: AsyncClient, phone: str, **extra: Any) -> str:
    response = await authed.post(
        "/api/v1/candidates",
        json={
            "name": "Tester Person",
            "phone": phone,
            "applied_role": "Backend Developer",
            "consent_attested": True,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["data"]["id"])


async def _start(authed: AsyncClient, *ids: str, dry_run: bool = False) -> list[dict[str, Any]]:
    response = await authed.post(
        "/api/v1/calls/start", json={"candidate_ids": list(ids), "dry_run": dry_run}
    )
    assert response.status_code == 202, response.text
    data: list[dict[str, Any]] = response.json()["data"]
    return data


async def _finish(db_session: AsyncSession, attempt_id: str, status: str = "no_answer") -> None:
    attempt = await db_session.get(CallAttempt, uuid.UUID(attempt_id))
    assert attempt is not None
    attempt.call_status = status
    await db_session.flush()


async def _pause(authed: AsyncClient) -> None:
    response = await authed.patch("/api/v1/settings", json={"calling_enabled": False})
    assert response.status_code == 200, response.text


# --- Retry, cancel, dry run -------------------------------------------------------------------


async def test_dry_run_queues_nothing(
    authed: AsyncClient, active_job: dict[str, Any], enqueued: list[str]
) -> None:
    ok_id = await _candidate(authed, "+91 90000 08001")
    opted = await _candidate(authed, "+91 90000 08002")
    await authed.patch(f"/api/v1/candidates/{opted}", json={"opted_out": True})
    results = await _start(authed, ok_id, opted, dry_run=True)
    assert [r["ok"] for r in results] == [True, False]
    assert results[0]["call_attempt_id"] is None
    assert results[1]["error"]["code"] == "opted_out"
    assert enqueued == []
    assert (await authed.get("/api/v1/calls")).json()["meta"]["total"] == 0


async def test_retry_creates_manual_attempt_only_when_eligible(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
) -> None:
    cid = await _candidate(authed, "+91 90000 08003")
    (first,) = await _start(authed, cid)
    # still live → refused with the reason
    response = await authed.post(f"/api/v1/calls/{first['call_attempt_id']}/retry")
    assert response.json()["data"]["error"]["code"] == "call_already_active"

    await _finish(db_session, first["call_attempt_id"])
    response = await authed.post(f"/api/v1/calls/{first['call_attempt_id']}/retry")
    assert response.status_code == 202
    data = response.json()["data"]
    assert data["ok"] is True
    retry = (await authed.get(f"/api/v1/calls/{data['call_attempt_id']}")).json()["data"]
    assert (retry["attempt_number"], retry["attempt_type"], retry["call_status"]) == (
        2,
        "manual",
        "queued",
    )
    assert enqueued == [first["call_attempt_id"], data["call_attempt_id"]]

    # opted out → refused
    await _finish(db_session, data["call_attempt_id"])
    await authed.patch(f"/api/v1/candidates/{cid}", json={"opted_out": True})
    again = await authed.post(f"/api/v1/calls/{data['call_attempt_id']}/retry")
    assert again.json()["data"]["error"]["code"] == "opted_out"


async def test_cancel_allowed_only_before_dialing(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
) -> None:
    cid = await _candidate(authed, "+91 90000 08004")
    (first,) = await _start(authed, cid)
    response = await authed.post(f"/api/v1/calls/{first['call_attempt_id']}/cancel")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert (data["call_status"], data["end_reason"]) == ("cancelled", "cancelled")
    assert data["failure_reason"].startswith("cancelled_by_recruiter:")

    (second,) = await _start(authed, cid)  # the slot is free again
    await _finish(db_session, second["call_attempt_id"], "in_progress")
    refused = await authed.post(f"/api/v1/calls/{second['call_attempt_id']}/cancel")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "call_not_cancellable"


async def test_hangup_needs_a_live_session(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
) -> None:
    from app.voice.session_registry import REGISTRY

    cid = await _candidate(authed, "+91 90000 08005")
    (first,) = await _start(authed, cid)
    aid = first["call_attempt_id"]
    assert (await authed.post(f"/api/v1/calls/{aid}/hangup")).status_code == 409  # queued
    await _finish(db_session, aid, "in_progress")
    assert (await authed.post(f"/api/v1/calls/{aid}/hangup")).status_code == 404  # no session

    class Session:
        ended = 0

        def end_by_recruiter(self) -> bool:
            self.ended += 1
            return True

    fake = Session()
    REGISTRY.register(aid, fake)
    try:
        response = await authed.post(f"/api/v1/calls/{aid}/hangup")
    finally:
        REGISTRY.unregister(aid)
    assert response.status_code == 200
    assert response.json()["data"]["ending"] is True and fake.ended == 1


async def test_calls_list_filters_and_transcript(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
) -> None:
    a = await _candidate(authed, "+91 90000 08006", name="Asha Verma")
    b = await _candidate(authed, "+91 90000 08007", name="Ravi Kumar")
    (ca,) = await _start(authed, a)
    (cb,) = await _start(authed, b)
    await _finish(db_session, ca["call_attempt_id"], "completed")
    db_session.add(
        Conversation(
            call_attempt_id=uuid.UUID(ca["call_attempt_id"]),
            transcript=[
                {"seq": 1, "speaker": "assistant", "text": "Hello?", "timestamp": None},
                {"seq": 2, "speaker": "candidate", "text": "Yes", "interrupted": False},
                {"seq": 3, "speaker": "assistant", "text": "", "timestamp": None},
                {
                    "seq": 4,
                    "speaker": "assistant",
                    "text": "Long question",
                    "interrupted": True,
                    "heard_text": "Long",
                },
            ],
            summary="Asha said yes.",
        )
    )
    await db_session.flush()

    listed = (
        await authed.get("/api/v1/calls", params={"call_status": ["completed", "busy"]})
    ).json()
    assert [r["candidate_name"] for r in listed["data"]] == ["Asha Verma"]
    assert listed["data"][0]["has_transcript"] is True
    by_name = (await authed.get("/api/v1/calls", params={"q": "ravi"})).json()
    assert [r["id"] for r in by_name["data"]] == [cb["call_attempt_id"]]

    transcript = (await authed.get(f"/api/v1/calls/{ca['call_attempt_id']}/transcript")).json()
    entries = transcript["data"]["entries"]
    assert [e["seq"] for e in entries] == [1, 2, 4]  # the empty line is dropped
    assert entries[2]["interrupted"] is True and entries[2]["heard_text"] == "Long"
    assert transcript["data"]["summary"] == "Asha said yes."
    empty = (await authed.get(f"/api/v1/calls/{cb['call_attempt_id']}/transcript")).json()
    assert empty["data"]["entries"] == []


async def test_candidate_rows_carry_eligibility_and_last_call(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
) -> None:
    fresh = await _candidate(authed, "+91 90000 08008")
    called = await _candidate(authed, "+91 90000 08009")
    opted = await _candidate(authed, "+91 90000 08010")
    await authed.patch(f"/api/v1/candidates/{opted}", json={"opted_out": True})
    (attempt,) = await _start(authed, called)

    rows = {r["id"]: r for r in (await authed.get("/api/v1/candidates")).json()["data"]}
    assert rows[fresh]["eligibility"] == {"can_call": True, "reason": None, "message": None}
    assert rows[fresh]["last_call"] is None
    assert rows[called]["eligibility"]["reason"] == "call_already_active"
    assert rows[called]["last_call"]["call_status"] == "queued"
    assert rows[opted]["eligibility"]["reason"] == "opted_out"
    assert rows[opted]["eligibility"]["message"] == "Candidate opted out of calls"

    never = (await authed.get("/api/v1/candidates", params={"call_status": "not_called"})).json()
    assert {r["id"] for r in never["data"]} == {fresh, opted}
    queued = (await authed.get("/api/v1/candidates", params={"call_status": "queued"})).json()
    assert [r["id"] for r in queued["data"]] == [called]
    bad = await authed.get("/api/v1/candidates", params={"call_status": "nonsense"})
    assert bad.status_code == 422
    assert attempt["ok"]


# --- Global pause (P8-AC7) --------------------------------------------------------------------


async def test_pause_blocks_start_retry_and_the_worker(
    authed: AsyncClient,
    active_job: dict[str, Any],
    enqueued: list[str],
    db_session: AsyncSession,
    sessions: None,
    settings: Settings,
) -> None:
    cid = await _candidate(authed, "+91 90000 08011")
    other = await _candidate(authed, "+91 90000 08012")
    (queued,) = await _start(authed, cid)  # queued before the pause
    (done,) = await _start(authed, other)
    await _finish(db_session, done["call_attempt_id"])

    await _pause(authed)
    (refused,) = await _start(authed, other)
    assert refused["error"] == {
        "code": "calling_paused",
        "message": "Calling is paused on the Settings page",
    }
    retry = (await authed.post(f"/api/v1/calls/{done['call_attempt_id']}/retry")).json()
    assert retry["data"]["error"]["code"] == "calling_paused"
    rows = {r["id"]: r for r in (await authed.get("/api/v1/candidates")).json()["data"]}
    assert rows[other]["eligibility"]["reason"] == "calling_paused"

    # the worker doesn't dial the attempt queued before the pause
    provider = FakeProvider()
    out = await call_worker.initiate_call(
        {"settings": settings, "telephony": provider}, queued["call_attempt_id"]
    )
    assert out == "cancelled" and provider.placed == []
    attempt = await db_session.get(CallAttempt, uuid.UUID(queued["call_attempt_id"]))
    assert attempt is not None
    assert attempt.failure_reason == "ineligible:calling_paused"

    # resume → calls go out again
    await authed.patch("/api/v1/settings", json={"calling_enabled": True})
    (again,) = await _start(authed, other)
    assert again["ok"] is True


async def test_calling_window_from_settings_applies(
    authed: AsyncClient, active_job: dict[str, Any], enqueued: list[str]
) -> None:
    cid = await _candidate(authed, "+91 90000 08013")
    # a window that's never open today: one day other than today, one hour
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    today = datetime.now(UTC).astimezone(ZoneInfo("Asia/Kolkata")).weekday()
    day = settings_service.DAYS[(today + 3) % 7]
    response = await authed.patch(
        "/api/v1/settings", json={"calling": {"days": [day], "start_hour": 10, "end_hour": 11}}
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["calling_now"] is False
    (result,) = await _start(authed, cid)
    assert result["error"]["code"] == "outside_calling_window"


# --- Settings ---------------------------------------------------------------------------------


async def test_settings_defaults_and_validation(authed: AsyncClient, active_job: Any) -> None:
    data = (await authed.get("/api/v1/settings")).json()["data"]
    assert data["general"]["calling_enabled"] is True
    assert data["general"]["calling"]["days"] == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    assert data["limits"] == {
        "max_concurrent_calls": 1,
        "timezone": "Asia/Kolkata",
        "calling_enabled_env": True,
        "voice_engine_env": "pipeline",
        "realtime_model": "gpt-realtime-2.1-mini",
    }
    assert data["introduction"]["built_in"] is True
    assert "AI recruitment assistant" in data["introduction"]["text"]
    assert "Test Co" in data["introduction"]["text"]

    bad = [
        {"calling": {"days": ["mon"], "start_hour": 18, "end_hour": 9}},
        {"calling": {"days": ["someday"], "start_hour": 9, "end_hour": 18}},
        {"retry": {"max_attempts": 3, "interval_days": 1}},
        {"max_concurrent_calls": 0},
        {"agent_introduction": "Hi {first_name}, calling from {company}. Free now?"},  # no "AI"
        {"agent_introduction": "Hi {name}, I'm an AI assistant. Free now?"},  # unknown key
        {"agent_introduction": "Hi {first_name}, I'm an AI assistant."},  # no question
        {"unknown_section": 1},
    ]
    for body in bad:
        response = await authed.patch("/api/v1/settings", json=body)
        assert response.status_code == 422, body


async def test_settings_update_template_and_concurrency_cap(
    authed: AsyncClient, active_job: Any, db_session: AsyncSession
) -> None:
    response = await authed.patch(
        "/api/v1/settings",
        json={
            "organization_name": "  Talent   Partners ",
            "agent_introduction": (
                "Hi {first_name}, I'm an AI assistant from {organization} calling about the "
                "{job_title} role at {company}. Is now a good time?"
            ),
            "max_concurrent_calls": 5,
            "retry": {"max_attempts": 4, "interval_days": 3},
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["general"]["organization_name"] == "Talent Partners"
    assert data["introduction"]["text"] == (
        "Hi Asha, I'm an AI assistant from Talent Partners calling about the Backend Developer "
        "role at Test Co. Is now a good time?"
    )
    from app.config import get_settings  # noqa: F401  (the app's settings are the fixture's)

    env = make_settings()
    effective = await settings_service.effective(db_session, env)
    assert effective.max_concurrent_calls == 1  # capped by MAX_CONCURRENT_CALLS
    assert (effective.max_call_attempts, effective.retry_interval_days) == (4, 3)

    # clearing the template → back to the built-in line; other sections unchanged
    cleared = await authed.patch("/api/v1/settings", json={"agent_introduction": None})
    body = cleared.json()["data"]
    assert body["introduction"]["built_in"] is True
    assert body["general"]["retry"] == {
        "max_attempts": 4,
        "interval_days": 3,
        "enabled": True,  # Phase 9 fields: defaults when not sent
        "max_callbacks": 2,
        "alternate_slots": True,
    }


async def test_intro_template_reaches_the_call(db_session: AsyncSession, active_job: Any) -> None:
    from app.agent.prompts import CandidateContext, introduction
    from app.database.models import Job
    from app.voice.websocket_handler import job_config

    env = make_settings()
    await settings_service.update_general(
        db_session,
        env,
        settings_service.GeneralUpdate(
            agent_introduction="Namaste {first_name}! This is an AI assistant for {company}. "
            "Can we talk?"
        ),
        user_id=uuid.uuid4(),
    )
    job = await db_session.get(Job, uuid.UUID(active_job["id"]))
    assert job is not None
    effective = await settings_service.effective(db_session, env)
    line = introduction(CandidateContext(name="Ravi Kumar"), job_config(job, effective))
    assert line == "Namaste Ravi! This is an AI assistant for Test Co. Can we talk?"
    default = introduction(CandidateContext(name="Ravi Kumar"), job_config(job))
    assert default.startswith("Hi Ravi, I'm an AI recruitment assistant")


async def test_status_never_contains_secrets(
    authed: AsyncClient, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    seen: list[str] = []

    async def fake_get(url: str, transport: Any, **kwargs: Any) -> httpx.Response:
        seen.append(url)
        code = 401 if "deepgram" in url else 200
        # a provider echoing the key back must not leak it either
        return httpx.Response(code, json={"echo": SECRETS["deepgram_api_key"]})

    monkeypatch.setattr(provider_status_service, "_get", fake_get)

    response = await authed.get("/api/v1/settings/status", params={"refresh": "true"})
    assert response.status_code == 200, response.text
    text = response.text
    for secret in SECRETS.values():
        if "SECRET" in secret:
            assert secret not in text
    for value in ("exo-SECRET", "sk-test-SECRET", "dg-SECRET"):
        assert value not in text
    providers = {p["name"]: p for p in response.json()["data"]["providers"]}
    assert providers["openai"]["reachable"] is True
    assert providers["deepgram"] == providers["deepgram"] | {
        "reachable": False,
        "message": "The key was refused (401)",
    }
    assert providers["exotel"]["reachable"] is True
    assert providers["tts"]["reachable"] is False  # no voice loaded in tests
    assert len(seen) == 3

    # cached: a second call makes no requests
    await authed.get("/api/v1/settings/status")
    assert len(seen) == 3
    # and every other settings response is clean too
    body = (await authed.get("/api/v1/settings")).text
    assert not any(s in body for s in SECRETS.values() if "SECRET" in s)


async def test_public_connections_summary(
    api: AsyncClient, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    """/health/connections needs no login and shows a state only: no provider names, models,
    phone numbers, messages or keys, and no way to force a fresh check."""
    async for key in get_redis().scan_iter("rcai:provider-status:*"):
        await get_redis().delete(key)
    seen: list[str] = []

    async def fake_get(url: str, transport: Any, **kwargs: Any) -> httpx.Response:
        seen.append(url)
        return httpx.Response(401 if "deepgram" in url else 200, json={})

    monkeypatch.setattr(provider_status_service, "_get", fake_get)

    response = await api.get("/health/connections")
    assert response.status_code == 200, response.text
    states = {c["name"]: (c["label"], c["state"]) for c in response.json()["data"]}
    assert states == {
        "agent": ("AI agent", "ok"),
        "speech": ("Speech recognition", "problem"),
        "telephony": ("Telephony", "ok"),
        "voice": ("AI voice", "problem"),
    }
    text = response.text.lower()
    for word in ("openai", "deepgram", "exotel", "kitten", "gpt-test", "refused", "secret"):
        assert word not in text
    assert str(EXOTEL["exotel_caller_id"]) not in response.text
    assert len(seen) == 3
    # cached, and `refresh` is ignored here
    await api.get("/health/connections", params={"refresh": "true"})
    assert len(seen) == 3


# --- Roles ------------------------------------------------------------------------------------


async def test_super_admin_role(api: AsyncClient, db_session: AsyncSession) -> None:
    from app.database.models import Organization
    from app.services.auth_service import hash_password

    admin = User(
        organization=Organization(name="Test Org"),
        email=f"admin-{uuid.uuid4().hex[:8]}@example.com",
        name="Admin",
        password_hash=hash_password(TEST_PASSWORD),
        role="super_admin",
    )
    db_session.add(admin)
    await db_session.flush()
    response = await api.post(
        "/api/v1/auth/login", json={"email": admin.email, "password": TEST_PASSWORD}
    )
    assert response.json()["data"]["role"] == "super_admin"
