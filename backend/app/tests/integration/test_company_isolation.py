"""No company sees or changes another company's candidates or calls (migration 0017).

Company A has a requirement candidate with a finished call and transcript, and a candidate of
the original job flow. Company B (signed up separately) gets "not found" for every one of
them, empty lists and a zero dashboard, and can use the same phone number itself.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CallAttempt, Candidate, Conversation
from app.tests.conftest import TEST_PASSWORD
from app.tests.integration.test_requirement_screening import _confirm, _import, _requirement

PHONE = "9876543210"


async def _company_a(api: AsyncClient, db: AsyncSession) -> dict[str, Any]:
    requirement = await _requirement(api)
    await _confirm(
        api, (await _import(api, requirement["id"], f"Name,Phone\nRavi,{PHONE}\n".encode()))["id"]
    )
    job = await api.post("/api/v1/jobs", json={"job_title": "Developer", "company_name": "A Co"})
    assert job.status_code == 201, job.text
    legacy = await api.post(
        "/api/v1/candidates",
        json={
            "name": "Old Flow",
            "phone": f"+91{PHONE}",
            "applied_role": "Developer",
            "consent_attested": True,
        },
    )
    assert legacy.status_code == 201, legacy.text
    ravi = await db.scalar(select(Candidate).where(Candidate.name == "Ravi"))
    assert ravi is not None
    attempt = CallAttempt(
        candidate_id=ravi.id,
        attempt_number=1,
        attempt_type="manual",
        provider="exotel",
        call_status="completed",
        end_time=datetime.now(UTC),
        retry_evaluated_at=datetime.now(UTC),
    )
    db.add(attempt)
    await db.flush()
    db.add(
        Conversation(
            call_attempt_id=attempt.id,
            transcript=[{"seq": 1, "speaker": "candidate", "text": "My salary is private."}],
        )
    )
    await db.commit()
    return {
        "requirement": requirement,
        "ravi": str(ravi.id),
        "legacy": legacy.json()["data"]["id"],
        "attempt": str(attempt.id),
    }


async def _sign_up_company_b(api: AsyncClient) -> None:
    await api.post("/api/v1/auth/logout")
    body = {
        "organization_name": "Company B",
        "name": "B Owner",
        "email": f"owner-{uuid.uuid4().hex[:8]}@b.example",
        "password": TEST_PASSWORD,
    }
    response = await api.post("/api/v1/auth/signup", json=body)
    assert response.status_code == 201, response.text


async def test_another_company_sees_and_changes_nothing(
    admin: AsyncClient, db_session: AsyncSession
) -> None:
    a = await _company_a(admin, db_session)
    # Company A sees its own
    listed = (await admin.get("/api/v1/candidates")).json()["data"]
    assert {r["id"] for r in listed} == {a["ravi"], a["legacy"]}
    assert (await admin.get(f"/api/v1/calls/{a['attempt']}/transcript")).status_code == 200

    await _sign_up_company_b(admin)
    b = admin

    # Lists: nothing of A's
    assert (await b.get("/api/v1/candidates")).json()["data"] == []
    assert (await b.get("/api/v1/calls")).json()["data"] == []
    for purpose in ("screening", "telephonic"):
        calls = await b.get("/api/v1/calls", params={"purpose": purpose})
        assert calls.json()["data"] == []
    calls = await b.get("/api/v1/calls", params={"candidate_id": a["ravi"]})
    assert calls.json()["data"] == []

    # One candidate: not found, never changed
    for cid in (a["ravi"], a["legacy"]):
        assert (await b.get(f"/api/v1/candidates/{cid}")).status_code == 404
        assert (await b.get(f"/api/v1/candidates/{cid}/overview")).status_code == 404
        patch = await b.patch(f"/api/v1/candidates/{cid}", json={"name": "Hacked"})
        assert patch.status_code == 404
        assert (await b.delete(f"/api/v1/candidates/{cid}")).status_code == 404
        resolve = await b.post(
            f"/api/v1/candidates/{cid}/conflicts/current_company/resolve", json={"choice": "keep"}
        )
        assert resolve.status_code == 404
    for cid in (a["ravi"], a["legacy"]):
        candidate = await db_session.get(Candidate, uuid.UUID(cid), populate_existing=True)
        assert candidate is not None and candidate.deleted_at is None
        assert candidate.name != "Hacked"

    # One call: not found; no retry, cancel or hang-up
    aid = a["attempt"]
    for path in (f"/api/v1/calls/{aid}", f"/api/v1/calls/{aid}/transcript"):
        assert (await b.get(path)).status_code == 404, path
    for action in ("retry", "cancel", "hangup"):
        response = await b.post(f"/api/v1/calls/{aid}/{action}")
        assert response.status_code == 404, action

    # Starting calls for A's candidates: each "not found", nothing queued
    started = await b.post("/api/v1/calls/start", json={"candidate_ids": [a["ravi"], a["legacy"]]})
    assert started.status_code == 202, started.text
    assert {r["error"]["code"] for r in started.json()["data"]} == {"candidate_not_found"}
    attempts = (
        await db_session.execute(
            select(CallAttempt).where(CallAttempt.candidate_id == uuid.UUID(a["ravi"]))
        )
    ).scalars()
    assert len(list(attempts)) == 1

    # Dashboard: zeros and empty lists
    summary = (await b.get("/api/v1/dashboard/summary")).json()["data"]
    assert summary["kpis"]["candidates_total"] == 0
    assert summary["latest_conversation"] is None
    stats = (await b.get("/api/v1/dashboard/stats")).json()["data"]
    assert (stats["total_candidates"], stats["calls_completed"]) == (0, 0)
    assert (await b.get("/api/v1/dashboard/activity")).json()["data"] == []
    assert (await b.get("/api/v1/dashboard/attention")).json()["data"] == []
    quick = (await b.get("/api/v1/dashboard/quick-start")).json()["data"]
    assert (quick["candidates"], quick["total"]) == ([], 0)

    # A's client is not B's to filter by
    response = await b.get(
        "/api/v1/candidates", params={"client_id": a["requirement"]["client_id"]}
    )
    assert response.status_code == 404

    # B may have the same phone number in its own original-flow list
    job = await b.post("/api/v1/jobs", json={"job_title": "Developer", "company_name": "B Co"})
    assert job.status_code == 201, job.text
    own = await b.post(
        "/api/v1/candidates",
        json={
            "name": "B's Candidate",
            "phone": f"+91{PHONE}",
            "applied_role": "Developer",
            "consent_attested": True,
        },
    )
    assert own.status_code == 201, own.text
    assert [r["name"] for r in (await b.get("/api/v1/candidates")).json()["data"]] == [
        "B's Candidate"
    ]
