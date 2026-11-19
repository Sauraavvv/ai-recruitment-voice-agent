"""Dashboard summary: every number checked against known rows."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CallAttempt, Candidate, Conversation


async def _candidate(authed: AsyncClient, phone: str, **extra: Any) -> uuid.UUID:
    response = await authed.post(
        "/api/v1/candidates",
        json={
            "name": f"C {phone[-2:]}",
            "phone": phone,
            "applied_role": "Dev",
            "consent_attested": True,
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["data"]["id"])


async def test_summary_counts(
    authed: AsyncClient, active_job: dict[str, Any], db_session: AsyncSession
) -> None:
    a = await _candidate(authed, "+91 90000 09101")
    b = await _candidate(authed, "+91 90000 09102")
    c = await _candidate(authed, "+91 90000 09103")
    await _candidate(authed, "+91 90000 09104")  # never called

    cand_a = await db_session.get(Candidate, a)
    assert cand_a is not None
    cand_a.screening_status, cand_a.interested = "completed", True
    cand_a.interview_availability, cand_a.notice_period = "Monday afternoon", "30 days"
    cand_b = await db_session.get(Candidate, b)
    assert cand_b is not None
    cand_b.screening_status, cand_b.interested = "completed", False

    now = datetime.now(UTC)
    answered = CallAttempt(
        candidate_id=a,
        attempt_number=1,
        provider="exotel",
        call_status="completed",
        stream_id="s1",
        duration_seconds=180,
        start_time=now - timedelta(minutes=5),
        end_time=now,
    )
    answered_b = CallAttempt(
        candidate_id=b,
        attempt_number=1,
        provider="exotel",
        call_status="completed",
        stream_id="s2",
        duration_seconds=60,
    )
    missed = CallAttempt(
        candidate_id=c, attempt_number=1, provider="exotel", call_status="no_answer"
    )
    live = CallAttempt(
        candidate_id=c,
        attempt_number=2,
        provider="exotel",
        call_status="in_progress",
        stream_id="s3",
        start_time=now,
    )
    db_session.add_all([answered, answered_b, missed, live])
    await db_session.flush()
    db_session.add(
        Conversation(
            call_attempt_id=answered.id,
            transcript=[{"speaker": "assistant", "text": f"line {i}"} for i in range(12)],
        )
    )
    await db_session.flush()

    response = await authed.get("/api/v1/dashboard/summary")
    assert response.status_code == 200, response.text
    data = response.json()["data"]

    k = data["kpis"]
    assert (k["candidates_total"], k["screened"], k["interested"]) == (4, 2, 1)
    assert k["interested_rate"] == 0.5
    assert (k["calls_total"], k["calls_connected"], k["calls_today"]) == (4, 3, 4)
    assert k["connect_rate"] == 0.75
    assert k["avg_call_seconds"] == 120  # (180 + 60) / 2; the live call has no duration yet
    assert data["funnel"] == {
        "candidates": 4,
        "called": 3,
        "connected": 3,
        "screened": 2,
        "interested": 1,
    }
    assert len(data["calls_by_day"]) == 14 and data["calls_by_day"][-1]["total"] == 4
    assert data["outcomes"] == {"completed": 2, "no_answer": 1, "in_progress": 1}
    assert [c["candidate_id"] for c in data["live_calls"]] == [str(c)]
    latest = data["latest_conversation"]
    assert latest["candidate_name"] == "C 01" and latest["turns"] == 12
    assert [t["text"] for t in latest["transcript"]] == [f"line {i}" for i in range(4, 12)]
    (slot,) = data["interview_availability"]
    assert (slot["availability"], slot["notice_period"]) == ("Monday afternoon", "30 days")


async def test_summary_empty(authed: AsyncClient) -> None:
    data = (await authed.get("/api/v1/dashboard/summary")).json()["data"]
    assert data["kpis"]["connect_rate"] is None and data["kpis"]["avg_call_seconds"] is None
    assert data["latest_conversation"] is None and data["live_calls"] == []


async def test_summary_requires_login(api: AsyncClient) -> None:
    assert (await api.get("/api/v1/dashboard/summary")).status_code == 401
