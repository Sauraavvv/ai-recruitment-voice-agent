"""Sheets outbox and drain against the database and Redis, with a fake sheet (phase-07 P7-T7 to
P7-T10, P7-AC4 to AC6). The real-API version is test_sheets_live.py (`-m sheets`)."""

import contextlib
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import CallAttempt, Candidate, Conversation, SyncLog
from app.services import finalization_service, screening_store, sync_service
from app.services.sheet_mapping import to_sheet_row
from app.services.sheets_service import SheetsError
from app.tests.conftest import make_settings
from app.tests.integration.test_finalization import full_result
from app.tests.unit.fake_sheet import FakeSheetWriter
from app.utils.redis import get_redis

CONFIGURED = {"google_service_account_json": "/run/secrets/none.json", "google_sheet_id": "s1"}


@pytest.fixture
def settings() -> Settings:
    """The app under test has Sheets configured (the fake sheet stands in for Google)."""
    return make_settings(**CONFIGURED, frontend_url="https://hirecall.test")


@pytest.fixture
async def env(
    api: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[dict[str, Any]]:
    @contextlib.asynccontextmanager
    async def factory() -> AsyncIterator[AsyncSession]:
        yield db_session

    for module in (screening_store, finalization_service):
        monkeypatch.setattr(module, "get_sessionmaker", lambda: factory)
    requested: list[str] = []

    async def request_sync(settings: Any, pool: Any = None) -> bool:
        requested.append("sync")  # never reaches the shared Redis queue
        return bool(settings.sheets_configured)

    monkeypatch.setattr(sync_service, "request_sync", request_sync)
    monkeypatch.setattr(sync_service, "jittered", lambda delay: delay)  # exact waits in asserts
    redis = get_redis()
    for key in (sync_service.STATUS_KEY, sync_service.CHECK_CACHE_KEY, sync_service.LOCK_KEY):
        await redis.delete(key)
    yield {"factory": factory, "requested": requested, "sheet": FakeSheetWriter()}
    for key in (sync_service.STATUS_KEY, sync_service.CHECK_CACHE_KEY, sync_service.LOCK_KEY):
        await redis.delete(key)


async def drain(env: dict[str, Any], settings: Settings, at: datetime | None = None) -> Any:
    clock: Callable[[], datetime] = (lambda: at) if at else (lambda: datetime.now(UTC))
    return await sync_service.drain(env["factory"], env["sheet"], get_redis(), settings, now=clock)


async def create(authed: AsyncClient, phone: str, name: str = "Asha Rao") -> uuid.UUID:
    response = await authed.post(
        "/api/v1/candidates",
        json={"name": name, "phone": phone, "applied_role": "Dev", "consent_attested": True},
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["data"]["id"])


async def logs(db: AsyncSession, cid: uuid.UUID) -> list[SyncLog]:
    rows = await db.execute(
        select(SyncLog).where(SyncLog.candidate_id == cid).order_by(SyncLog.created_at)
    )
    out = list(rows.scalars().all())
    for row in out:
        await db.refresh(row)
    return out


async def test_new_candidate_is_appended_then_updated_in_place(
    authed: AsyncClient,
    active_job: dict[str, Any],
    env: dict[str, Any],
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    cid = await create(authed, "+91 90000 09101")
    first = await logs(db_session, cid)
    assert [r.sync_status for r in first] == ["pending"]  # same transaction as the insert
    assert env["requested"] == ["sync"]

    result = await drain(env, settings)
    assert (result.outcome, result.synced) == ("done", 1)
    sheet = env["sheet"].client
    assert sheet.row_for(str(cid))[1] == "Asha Rao"
    assert [r.sync_status for r in await logs(db_session, cid)] == ["success"]

    response = await authed.patch(f"/api/v1/candidates/{cid}", json={"name": "Asha R."})
    assert response.status_code == 200
    await drain(env, settings)
    assert len(sheet.data()) == 1 and sheet.row_for(str(cid))[1] == "Asha R."
    assert (await drain(env, settings)).outcome == "idle"


async def test_manual_sync_five_times_gives_one_row(
    authed: AsyncClient,
    active_job: dict[str, Any],
    env: dict[str, Any],
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """P7-AC5."""
    cid = await create(authed, "+91 90000 09102")
    for _ in range(5):
        response = await authed.post(f"/api/v1/integrations/google-sheets/sync/{cid}")
        assert response.status_code == 202, response.text
        assert response.json()["data"]["sync_status"] == "pending"
        assert response.json()["data"]["queued"] is True
    for _ in range(5):  # five drains, as the five queued jobs would
        await drain(env, settings)
    sheet = env["sheet"].client
    assert len(sheet.data()) == 1
    rows = await logs(db_session, cid)
    assert len(rows) == 6 and {r.sync_status for r in rows} == {"success"}


async def test_sorted_sheet_still_updates_the_right_row(
    authed: AsyncClient,
    active_job: dict[str, Any],
    env: dict[str, Any],
    settings: Settings,
) -> None:
    ids = [await create(authed, f"+91 90000 0911{i}", name=f"P{i}") for i in range(3)]
    await drain(env, settings)
    sheet = env["sheet"].client
    sheet.sort_by(1, reverse=True)  # sorted by name, by hand
    await authed.patch(f"/api/v1/candidates/{ids[0]}", json={"name": "P0 renamed"})
    await drain(env, settings)
    assert sheet.row_for(str(ids[0]))[1] == "P0 renamed"
    assert len(sheet.data()) == 3


async def test_outage_keeps_the_database_and_recovers(
    authed: AsyncClient,
    active_job: dict[str, Any],
    env: dict[str, Any],
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """P7-AC6: temporary failure → database intact, failed log with backoff, recovery."""
    cid = await create(authed, "+91 90000 09103")
    sheet = env["sheet"].client
    sheet.fail_with = SheetsError("Google Sheets is busy (503)", transient=True, status=503)
    t0 = datetime.now(UTC)
    result = await drain(env, settings, at=t0)
    assert (result.outcome, result.failed) == ("error", 1)
    (row,) = await logs(db_session, cid)
    assert row.sync_status == "failed" and row.attempts == 1 and "503" in (row.error_message or "")
    assert row.next_attempt_at == t0 + timedelta(minutes=1)
    candidate = await db_session.get(Candidate, cid)
    assert candidate is not None and candidate.name == "Asha Rao"  # the database is intact
    status = await sync_service.get_status(get_redis())
    assert status["state"] == "degraded"

    assert (await drain(env, settings, at=t0 + timedelta(seconds=30))).outcome == "idle"
    async with env["factory"]() as session:
        assert await sync_service.stale_count(session, t0 + timedelta(minutes=2)) == 1

    sheet.fail_with = None  # Google is back; the reconciler's drain runs
    result = await drain(env, settings, at=t0 + timedelta(minutes=2))
    assert result.outcome == "done"
    (row,) = await logs(db_session, cid)
    assert row.sync_status == "success" and row.attempts == 2 and row.error_message is None
    assert sheet.row_for(str(cid))[1] == "Asha Rao"
    assert (await sync_service.get_status(get_redis()))["state"] == "ok"


async def test_backoff_ladder_then_gives_up(
    authed: AsyncClient,
    active_job: dict[str, Any],
    env: dict[str, Any],
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    cid = await create(authed, "+91 90000 09104")
    env["sheet"].client.fail_with = SheetsError("timeout", transient=True)
    at = datetime.now(UTC)
    waits = []
    for _ in range(6):
        await drain(env, settings, at=at)
        (row,) = await logs(db_session, cid)
        if row.next_attempt_at is None:
            break
        waits.append(row.next_attempt_at - at)
        at = row.next_attempt_at
    assert waits == [
        timedelta(minutes=1),
        timedelta(minutes=5),
        timedelta(minutes=15),
        timedelta(hours=1),
        timedelta(hours=6),
    ]
    assert row.sync_status == "failed" and row.attempts == 6 and row.next_attempt_at is None
    # A manual sync tries again
    env["sheet"].client.fail_with = None
    await authed.post(f"/api/v1/integrations/google-sheets/sync/{cid}")
    await drain(env, settings, at=at)
    assert {r.sync_status for r in await logs(db_session, cid)} == {"success"}


async def test_permission_error_fails_at_once_and_recovers_when_fixed(
    authed: AsyncClient,
    active_job: dict[str, Any],
    env: dict[str, Any],
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    cid = await create(authed, "+91 90000 09105")
    env["sheet"].client.fail_with = SheetsError("No permission", transient=False, status=403)
    t0 = datetime.now(UTC)
    await drain(env, settings, at=t0)
    (row,) = await logs(db_session, cid)
    assert row.sync_status == "failed" and row.next_attempt_at == t0 + timedelta(minutes=30)
    status = await sync_service.get_status(get_redis())
    assert status["state"] == "error" and status["message"] == "No permission"

    env["sheet"].client.fail_with = None  # access restored
    await drain(env, settings, at=t0 + timedelta(minutes=31))
    assert [r.sync_status for r in await logs(db_session, cid)] == ["success"]


async def test_not_configured_leaves_rows_pending(
    authed: AsyncClient, active_job: dict[str, Any], env: dict[str, Any], db_session: AsyncSession
) -> None:
    cid = await create(authed, "+91 90000 09106")
    result = await drain(env, make_settings())
    assert result.outcome == "not_configured"
    assert [r.sync_status for r in await logs(db_session, cid)] == ["pending"]


async def test_finalized_call_row_matches_the_database(
    authed: AsyncClient,
    active_job: dict[str, Any],
    env: dict[str, Any],
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """P7-AC4 (automated): the synced row equals the mapping of the database state."""
    cid = await create(authed, "+91 90000 09107")
    attempt = CallAttempt(
        candidate_id=cid,
        attempt_number=1,
        provider="exotel",
        call_status="completed",
        start_time=datetime(2026, 11, 19, 6, 0, tzinfo=UTC),
    )
    db_session.add(attempt)
    await db_session.commit()
    await screening_store.store_outcome(
        attempt_id=attempt.id, candidate_id=cid, result=full_result()
    )
    await finalization_service.finalize_attempt(attempt.id, settings=settings, llm=None)
    await drain(env, settings)

    candidate = await db_session.get(Candidate, cid)
    assert candidate is not None
    await db_session.refresh(candidate)
    await db_session.refresh(attempt)
    conv = (
        await db_session.execute(
            select(Conversation).where(Conversation.call_attempt_id == attempt.id)
        )
    ).scalar_one()
    expected = to_sheet_row(
        candidate, attempt, conv, 1, frontend_url=settings.frontend_url, tz=ZoneInfo("Asia/Kolkata")
    )
    row = env["sheet"].client.row_for(str(cid))
    assert row == expected
    by = dict(zip(env["sheet"].client.rows[0], row, strict=True))
    assert by["Screening Status"] == "Completed" and by["Current CTC (LPA)"] == 12
    assert by["Call Summary"] == conv.summary and by["Last Call Date"] == "2026-11-19 11:30"
    assert by["Transcript Reference"] == f"https://hirecall.test/candidates/{cid}"


async def test_status_endpoint(
    authed: AsyncClient,
    active_job: dict[str, Any],
    env: dict[str, Any],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.sheets_service import SheetCheck, SheetsService

    async def check(self: SheetsService) -> SheetCheck:
        return SheetCheck(True, "ok", None, "sync@test.iam.gserviceaccount.com")

    monkeypatch.setattr(SheetsService, "check_unlocked", check)
    await create(authed, "+91 90000 09108")
    body = (await authed.get("/api/v1/integrations/google-sheets/status")).json()["data"]
    assert body["configured"] and body["reachable"] and body["header"] == "ok"
    assert body["pending_candidates"] >= 1 and body["state"] == "unknown"
    assert body["service_account_email"] == "sync@test.iam.gserviceaccount.com"

    await drain(env, settings)
    body = (await authed.get("/api/v1/integrations/google-sheets/status")).json()["data"]
    assert body["state"] == "ok" and body["last_success_at"] and body["pending_candidates"] == 0


async def test_status_and_manual_sync_when_not_configured(
    authed: AsyncClient, active_job: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    app: Any = authed.app  # type: ignore[attr-defined]
    from app.config import get_settings

    unconfigured = make_settings()
    app.dependency_overrides[get_settings] = lambda: unconfigured
    body = (await authed.get("/api/v1/integrations/google-sheets/status")).json()["data"]
    assert body["configured"] is False and body["state"] == "not_configured"
    cid = await create(authed, "+91 90000 09109")
    response = await authed.post(f"/api/v1/integrations/google-sheets/sync/{cid}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "sheets_not_configured"
