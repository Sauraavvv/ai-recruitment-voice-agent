"""Phase 8 dashboard: stat tiles against a dataset with known counts (P8-AC1), zeros on an empty
database (P8-AC5), activity, every "needs attention" reason, quick start, conflict resolution,
and the summary a candidate shows."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import CallAttempt, Candidate, Conversation, SyncLog
from app.services import dashboard_service, sync_service
from app.tests.conftest import make_settings
from app.tests.integration.test_telephony import EXOTEL

ZERO_KEYS = (
    "total_candidates",
    "calls_completed",
    "calls_pending",
    "calls_in_progress",
    "unanswered_calls",
    "failed_calls",
    "interested_candidates",
    "screening_completed",
    "scheduled_retries",
)


@pytest.fixture
def settings() -> Settings:
    return make_settings(**EXOTEL)


@pytest.fixture(autouse=True)
def _no_sheet_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(settings: Any, pool: Any = None) -> bool:
        return False

    monkeypatch.setattr(sync_service, "request_sync", fake)


async def _candidate(authed: AsyncClient, phone: str, name: str | None = None) -> uuid.UUID:
    response = await authed.post(
        "/api/v1/candidates",
        json={
            "name": name or f"Person {phone[-3:]}",
            "phone": phone,
            "applied_role": "Dev",
            "consent_attested": True,
        },
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["data"]["id"])


def _attempt(cid: uuid.UUID, n: int, status: str, **extra: Any) -> CallAttempt:
    return CallAttempt(
        candidate_id=cid, attempt_number=n, provider="exotel", call_status=status, **extra
    )


async def test_empty_database_shows_zeros(authed: AsyncClient) -> None:
    for range_ in ("all", "today", "7d"):
        data = (await authed.get("/api/v1/dashboard/stats", params={"range": range_})).json()
        assert {k: data["data"][k] for k in ZERO_KEYS} == dict.fromkeys(ZERO_KEYS, 0)
        assert set(data["data"]["definitions"]) == set(ZERO_KEYS)
    assert (await authed.get("/api/v1/dashboard/activity")).json()["data"] == []
    assert (await authed.get("/api/v1/dashboard/attention")).json()["data"] == []


async def test_stats_match_a_known_dataset(
    authed: AsyncClient, active_job: dict[str, Any], db_session: AsyncSession
) -> None:
    ids = [await _candidate(authed, f"+91 90000 07{i:03d}") for i in range(9)]
    a, b, c, d, e, f, g, h, deleted = ids
    old = datetime.now(UTC) - timedelta(days=10)
    db_session.add_all(
        [
            _attempt(a, 1, "completed"),
            _attempt(b, 1, "no_answer", created_at=old),  # unanswered, outside 7d
            _attempt(b, 2, "completed"),  # b's latest is completed → not unanswered
            _attempt(c, 1, "busy"),  # unanswered
            _attempt(d, 1, "failed"),  # failed
            _attempt(e, 1, "queued"),  # pending
            _attempt(f, 1, "ringing"),  # in progress
            _attempt(g, 1, "no_answer", created_at=old),  # unanswered, only in "all"
            _attempt(g, 2, "retry_scheduled"),  # scheduled; g's latest dialed call: no answer
            _attempt(h, 1, "callback_requested"),  # scheduled
            _attempt(deleted, 1, "failed"),  # deleted candidate: not in candidate metrics
        ]
    )
    for cid, status, interested in (
        (a, "completed", True),
        (b, "completed", False),
        (c, "partially_completed", True),
    ):
        cand = await db_session.get(Candidate, cid)
        assert cand is not None
        cand.screening_status, cand.interested = status, interested
    gone = await db_session.get(Candidate, deleted)
    assert gone is not None
    gone.deleted_at, gone.interested = datetime.now(UTC), True
    await db_session.flush()

    stats = (await authed.get("/api/v1/dashboard/stats")).json()["data"]
    assert {k: stats[k] for k in ZERO_KEYS} == {
        "total_candidates": 8,
        "calls_completed": 2,
        "calls_pending": 1,
        "calls_in_progress": 1,
        "unanswered_calls": 2,  # c and g (Phase 9: a scheduled retry doesn't hide it); b answered
        "failed_calls": 1,  # d (the deleted candidate doesn't count)
        "interested_candidates": 2,
        "screening_completed": 2,
        "scheduled_retries": 2,
    }
    week = (await authed.get("/api/v1/dashboard/stats", params={"range": "7d"})).json()["data"]
    assert (week["calls_completed"], week["unanswered_calls"], week["failed_calls"]) == (2, 1, 1)
    bad = await authed.get("/api/v1/dashboard/stats", params={"range": "year"})
    assert bad.status_code == 422

    # P8-AC1: the same numbers straight from SQL
    sql_completed = await db_session.scalar(
        select(func.count()).select_from(CallAttempt).where(CallAttempt.call_status == "completed")
    )
    sql_total = await db_session.scalar(
        select(func.count()).select_from(Candidate).where(Candidate.deleted_at.is_(None))
    )
    assert (sql_completed, sql_total) == (stats["calls_completed"], stats["total_candidates"])


async def test_activity_is_newest_change_first(
    authed: AsyncClient, active_job: dict[str, Any], db_session: AsyncSession
) -> None:
    a = await _candidate(authed, "+91 90000 07101", "Asha")
    b = await _candidate(authed, "+91 90000 07102", "Ravi")
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _attempt(a, 1, "completed", updated_at=now - timedelta(minutes=5)),
            _attempt(b, 1, "in_progress", updated_at=now),
        ]
    )
    await db_session.flush()
    items = (await authed.get("/api/v1/dashboard/activity")).json()["data"]
    assert [(i["candidate_name"], i["call_status"]) for i in items] == [
        ("Ravi", "in_progress"),
        ("Asha", "completed"),
    ]


def _conversation(
    attempt: CallAttempt, *, final: dict[str, Any] | None = None, **result: Any
) -> Conversation:
    data: dict[str, Any] = {"result": {"callback": {}, **result}}
    if final is not None:
        data["final"] = final
    return Conversation(
        call_attempt_id=attempt.id,
        transcript=[{"seq": 1, "speaker": "assistant", "text": "Hi"}],
        extracted_data=data,
        finalized_at=datetime.now(UTC) if final is not None else None,
    )


async def test_attention_reasons(
    authed: AsyncClient, active_job: dict[str, Any], db_session: AsyncSession
) -> None:
    names = [
        "Callback Soon",
        "Callback Vague",
        "Partial",
        "Conflict",
        "Tech Fail",
        "Sheet Fail",
        "Question",
        "Wrong Person",
        "Exhausted",
        "Nothing",
    ]
    ids = {n: await _candidate(authed, f"+91 90000 072{i:02d}", n) for i, n in enumerate(names)}
    now = datetime.now(UTC)

    soon = _attempt(ids["Callback Soon"], 1, "completed")
    vague = _attempt(ids["Callback Vague"], 1, "completed")
    question = _attempt(ids["Question"], 1, "completed", end_reason="escalated")
    fail = _attempt(ids["Tech Fail"], 1, "failed", end_reason="technical_failure")
    db_session.add_all(
        [
            soon,
            vague,
            question,
            fail,
            _attempt(ids["Exhausted"], 1, "exhausted"),
            _attempt(ids["Nothing"], 1, "completed"),
        ]
    )
    await db_session.flush()
    db_session.add_all(
        [
            _conversation(
                soon,
                callback={
                    "requested": True,
                    "time_iso": (now + timedelta(hours=3)).isoformat(),
                    "time_text": "in three hours",
                },
            ),
            _conversation(
                vague,
                callback={"requested": True, "time_text": "later", "needs_recruiter": True},
            ),
            _conversation(question, escalation_reason="asked about relocation bonus"),
        ]
    )
    for name, status in (("Partial", "partially_completed"), ("Wrong Person", "wrong_person")):
        cand = await db_session.get(Candidate, ids[name])
        assert cand is not None
        cand.screening_status = status
    conflicted = await db_session.get(Candidate, ids["Conflict"])
    assert conflicted is not None
    conflicted.notice_period = "30 days"
    conflicted.screening_field_meta = {
        "notice_period": {
            "value": "30 days",
            "raw_text": "thirty days",
            "seq": 5,
            "conflict": {"final_value": "60 days", "quote": "sixty days", "seq": 9},
        },
        "current_company": {"value": "Acme", "conflict": None},
    }
    db_session.add(
        SyncLog(
            candidate_id=ids["Sheet Fail"],
            provider="google_sheets",
            sync_status="failed",
            error_message="No permission to edit the spreadsheet.",
        )
    )
    await db_session.flush()

    items = (await authed.get("/api/v1/dashboard/attention")).json()["data"]
    got = {(i["candidate_name"], i["reason"]) for i in items}
    assert got == {
        ("Callback Soon", "callback_due"),
        ("Callback Vague", "vague_callback"),
        ("Partial", "partially_completed"),
        ("Conflict", "data_conflict"),
        ("Tech Fail", "technical_failure"),
        ("Sheet Fail", "sheets_sync_failed"),
        ("Question", "unanswered_question"),
        ("Wrong Person", "wrong_person"),
        ("Exhausted", "attempts_exhausted"),
    }
    assert items[0]["reason"] == "callback_due"  # most urgent first
    by_reason = {i["reason"]: i for i in items}
    assert by_reason["unanswered_question"]["detail"] == "asked about relocation bonus"
    assert by_reason["vague_callback"]["detail"] == "later"
    conflict = by_reason["data_conflict"]["conflict"]
    assert (
        conflict
        | {
            "field": "notice_period",
            "stored_value": "30 days",
            "stored_quote": "thirty days",
            "other_value": "60 days",
            "other_quote": "sixty days",
            "other_seq": 9,
        }
        == conflict
    )

    # an opted-out candidate's callback and partial screening need nobody's attention
    partial = await db_session.get(Candidate, ids["Partial"])
    assert partial is not None
    partial.opted_out = True
    await db_session.flush()
    items = (await authed.get("/api/v1/dashboard/attention")).json()["data"]
    assert "Partial" not in {i["candidate_name"] for i in items}


async def _with_conflict(db_session: AsyncSession, cid: uuid.UUID) -> CallAttempt:
    attempt = _attempt(cid, 1, "completed")
    db_session.add(attempt)
    await db_session.flush()
    conv = _conversation(
        attempt,
        final={
            "fields": {"notice_period": {"value": "30 days"}},
            "conflicts": {"notice_period": {"final_value": "60 days", "quote": "sixty days"}},
        },
    )
    db_session.add(conv)
    cand = await db_session.get(Candidate, cid)
    assert cand is not None
    cand.notice_period = "30 days"
    cand.screening_field_meta = {
        "notice_period": {
            "value": "30 days",
            "raw_text": "thirty days",
            "seq": 5,
            "call_attempt_id": str(attempt.id),
            "conflict": {"final_value": "60 days", "quote": "sixty days", "seq": 9},
        }
    }
    await db_session.flush()
    return attempt


@pytest.mark.parametrize(("choice", "expected"), [("keep", "30 days"), ("use", "60 days")])
async def test_resolve_conflict(
    authed: AsyncClient,
    active_job: dict[str, Any],
    db_session: AsyncSession,
    choice: str,
    expected: str,
) -> None:
    cid = await _candidate(authed, "+91 90000 07301", "Conflict")
    attempt = await _with_conflict(db_session, cid)
    overview = (await authed.get(f"/api/v1/candidates/{cid}/overview")).json()["data"]
    assert [c["field"] for c in overview["conflicts"]] == ["notice_period"]
    before = await db_session.scalar(
        select(func.count()).select_from(SyncLog).where(SyncLog.candidate_id == cid)
    )

    response = await authed.post(
        f"/api/v1/candidates/{cid}/conflicts/notice_period/resolve", json={"choice": choice}
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["notice_period"] == expected
    meta = data["screening_field_meta"]["notice_period"]
    assert meta["conflict"] is None
    assert meta["conflict_resolution"]["choice"] == choice
    if choice == "use":
        assert (meta["raw_text"], meta["source"]) == ("sixty days", "recruiter")
        assert meta["previous"][-1]["value"] == "30 days"

    # an outbox row for the sheet, the call's record updated, gone from "needs attention"
    after = await db_session.scalar(
        select(func.count()).select_from(SyncLog).where(SyncLog.candidate_id == cid)
    )
    assert after == (before or 0) + 1
    conv = (
        await db_session.execute(
            select(Conversation).where(Conversation.call_attempt_id == attempt.id)
        )
    ).scalar_one()
    await db_session.refresh(conv)
    assert conv.extracted_data["final"]["conflicts"]["notice_period"]["resolved"]["choice"] == (
        choice
    )
    items = (await authed.get("/api/v1/dashboard/attention")).json()["data"]
    assert not [i for i in items if i["reason"] == "data_conflict"]
    again = await authed.post(
        f"/api/v1/candidates/{cid}/conflicts/notice_period/resolve", json={"choice": choice}
    )
    assert again.status_code == 409


async def test_summary_is_latest_call_with_data(
    authed: AsyncClient,
    active_job: dict[str, Any],
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    cid = await _candidate(authed, "+91 90000 07401", "Summary Person")
    first = _attempt(cid, 1, "completed")
    second = _attempt(cid, 2, "completed")
    db_session.add_all([first, second])
    await db_session.flush()
    now = datetime.now(UTC)
    with_data = _conversation(
        first, final={"fields": {"current_company": {"value": "Acme"}}, "missing_fields": []}
    )
    with_data.summary, with_data.finalized_at = "Works at Acme.", now - timedelta(minutes=10)
    empty = _conversation(second, final={"fields": {"current_company": {"value": None}}})
    empty.summary, empty.finalized_at = "Nothing was provided.", now
    db_session.add_all([with_data, empty])
    await db_session.flush()

    overview = (await authed.get(f"/api/v1/candidates/{cid}/overview")).json()["data"]
    assert overview["summary"]["text"] == "Works at Acme."
    assert overview["summary"]["attempt_number"] == 1
    assert overview["summary"]["newer_call_without_data"] is True
    assert overview["sheet_sync"]["status"] == "pending"  # created → outbox row

    # the sheet's Call Summary column uses the same rule
    rows = await sync_service.build_rows(db_session, [cid], settings)
    from app.services.sheet_mapping import HEADERS

    assert rows[str(cid)][HEADERS.index("Call Summary")] == "Works at Acme."

    # no call with data at all → the latest one
    with_data.extracted_data = {"final": {"fields": {}}}
    await db_session.flush()
    overview = (await authed.get(f"/api/v1/candidates/{cid}/overview")).json()["data"]
    assert overview["summary"]["text"] == "Nothing was provided."


async def test_quick_start_lists_eligible_never_called(
    authed: AsyncClient, active_job: dict[str, Any], db_session: AsyncSession
) -> None:
    fresh = await _candidate(authed, "+91 90000 07501", "Fresh")
    called = await _candidate(authed, "+91 90000 07502", "Called")
    opted = await _candidate(authed, "+91 90000 07503", "Opted")
    db_session.add(_attempt(called, 1, "completed"))
    cand = await db_session.get(Candidate, opted)
    assert cand is not None
    cand.opted_out = True
    await db_session.flush()

    data = (await authed.get("/api/v1/dashboard/quick-start")).json()["data"]
    assert [c["candidate_id"] for c in data["candidates"]] == [str(fresh)]
    assert (data["total"], data["limit"], data["blocked_reason"]) == (1, 20, None)
    assert data["calling_now"] is True

    await authed.patch("/api/v1/settings", json={"calling_enabled": False})
    paused = (await authed.get("/api/v1/dashboard/quick-start")).json()["data"]
    assert paused["candidates"] == [] and paused["blocked_reason"] == "calling_paused"
    assert paused["calling_now"] is False


async def test_dashboard_service_ranges() -> None:
    now = datetime(2026, 11, 19, 20, 0, tzinfo=UTC)  # 01:30 on the 20th in India
    today = dashboard_service.range_start("today", tz="Asia/Kolkata", now=now)
    assert today is not None and today.isoformat() == "2026-11-20T00:00:00+05:30"
    assert dashboard_service.range_start("all", tz="Asia/Kolkata", now=now) is None
