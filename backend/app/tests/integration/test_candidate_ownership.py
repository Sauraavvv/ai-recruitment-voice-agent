"""A recruiter sees only the jobs they created and the candidates they uploaded; a super admin
sees every recruiter's.

Two recruiters each add a job for the same client and upload a list to it; the super admin
also uploads one person to Ravi's job. Each recruiter sees only their own job and their own
candidates in every place they show up (job lists and counts, candidate lists, one candidate,
calls, the telephonic round, the dashboard, calling). Ravi repeating the number the admin
uploaded is a duplicate without a link to a candidate he can't open. The super admin sees all.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CallAttempt, Candidate, Conversation
from app.tests.conftest import TEST_PASSWORD, client_body
from app.tests.integration.test_requirement_screening import _confirm, _import
from app.tests.integration.test_telephonic_calls import _approve

OWNER_LIST = b"Name,Phone\nSunil Rao,9876543219\n"
RAVI_LIST = b"Name,Phone\nRavi Kumar,9876543210\nPriya Shah,9876543211\nSunil Rao,9876543219\n"
NEHA_LIST = b"Name,Phone\nAmit Jain,9876543212\nKiran Das,9876543213\n"


async def _login(api: AsyncClient, email: str) -> None:
    await api.post("/api/v1/auth/logout")
    response = await api.post(
        "/api/v1/auth/login", json={"email": email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text


async def _names(api: AsyncClient, **params: str) -> list[str]:
    response = await api.get("/api/v1/candidates", params=params)
    assert response.status_code == 200, response.text
    return sorted(r["name"] for r in response.json()["data"])


async def _job(api: AsyncClient, client_id: str, title: str) -> str:
    body = {"title": title, "job_description": "Sell CRM software to small businesses."}
    response = await api.post(f"/api/v1/clients/{client_id}/requirements", json=body)
    assert response.status_code == 201, response.text
    return str(response.json()["data"]["id"])


async def _setup(api: AsyncClient, db: AsyncSession) -> dict[str, Any]:
    owner = {
        "organization_name": "Acme",
        "name": "Owner",
        "email": "owner@acme.example",
        "password": TEST_PASSWORD,
    }
    assert (await api.post("/api/v1/auth/signup", json=owner)).status_code == 201
    for name in ("Ravi", "Neha"):
        member = {"name": name, "email": f"{name.lower()}@acme.example", "password": TEST_PASSWORD}
        assert (await api.post("/api/v1/team", json=member)).status_code == 201
    client = await api.post("/api/v1/clients", json=client_body("Acme Client"))
    client_id = client.json()["data"]["id"]

    await _login(api, "ravi@acme.example")
    ravi_job = await _job(api, client_id, "Sales Executive")
    question_set = await _approve(api, ravi_job, "Tell me about the last product you sold.")

    # The super admin uploads one person to Ravi's job (admins see every job)
    await _login(api, "owner@acme.example")
    await _confirm(api, (await _import(api, ravi_job, OWNER_LIST))["id"])

    await _login(api, "ravi@acme.example")
    preview = await _import(api, ravi_job, RAVI_LIST)
    duplicate = next(r for r in preview["rows"] if r["values"]["name"] == "Sunil Rao")
    await _confirm(api, preview["id"])

    await _login(api, "neha@acme.example")
    neha_job = await _job(api, client_id, "Telecaller")
    await _confirm(api, (await _import(api, neha_job, NEHA_LIST))["id"])

    ids = {c.name: c for c in (await db.execute(select(Candidate))).scalars()}
    # Priya finished screening interested and had a telephonic round call
    priya = ids["Priya Shah"]
    priya.interested = True
    priya.screening_status = "completed"
    attempt = CallAttempt(
        candidate_id=priya.id,
        attempt_number=1,
        attempt_type="manual",
        provider="exotel",
        purpose="telephonic",
        question_set_id=uuid.UUID(question_set),
        call_status="completed",
        end_time=datetime.now(UTC),
        retry_evaluated_at=datetime.now(UTC),
    )
    db.add(attempt)
    await db.flush()
    db.add(Conversation(call_attempt_id=attempt.id, transcript=[]))
    await db.commit()
    return {
        "ravi_job": ravi_job,
        "neha_job": neha_job,
        "ids": ids,
        "duplicate": duplicate,
        "attempt": str(attempt.id),
    }


async def _jobs(api: AsyncClient) -> dict[str, int]:
    """Job title -> its candidate count, for the jobs this account sees."""
    rows = (await api.get("/api/v1/requirements")).json()["data"]
    return {j["title"]: j["candidates"] for j in rows}


async def test_each_recruiter_sees_only_their_own_jobs_and_uploads(
    api: AsyncClient, db_session: AsyncSession
) -> None:
    s = await _setup(api, db_session)
    ravi_job, neha_job, ids = s["ravi_job"], s["neha_job"], s["ids"]
    priya, ravi_kumar = str(ids["Priya Shah"].id), str(ids["Ravi Kumar"].id)

    # Each candidate records who uploaded them
    uploaders = {name: c.uploaded_by_id for name, c in ids.items()}
    assert uploaders["Ravi Kumar"] == uploaders["Priya Shah"] != uploaders["Amit Jain"]
    assert uploaders["Sunil Rao"] not in (uploaders["Ravi Kumar"], uploaders["Amit Jain"])
    assert None not in uploaders.values()

    # Ravi's repeat of the admin's upload: a duplicate, without a link to that candidate
    assert s["duplicate"]["status"] == "duplicate_existing"
    assert s["duplicate"]["existing_candidate_id"] is None
    assert "Someone else on your team" in s["duplicate"]["errors"][0]["message"]

    # Neha (logged in last): only her job and her two candidates, everywhere
    assert await _jobs(api) == {"Telecaller": 2}
    assert await _names(api) == ["Amit Jain", "Kiran Das"]
    assert (await api.get(f"/api/v1/requirements/{ravi_job}")).status_code == 404
    listed = await api.get("/api/v1/candidates", params={"requirement_id": ravi_job})
    assert listed.status_code == 404
    for cid in (priya, ravi_kumar):
        assert (await api.get(f"/api/v1/candidates/{cid}")).status_code == 404
        assert (await api.get(f"/api/v1/candidates/{cid}/overview")).status_code == 404
    summary = (await api.get("/api/v1/dashboard/summary")).json()["data"]
    assert summary["kpis"]["candidates_total"] == 2
    assert (await api.get("/api/v1/calls", params={"purpose": "telephonic"})).json()["data"] == []
    assert (await api.get(f"/api/v1/calls/{s['attempt']}/answers")).status_code == 404
    roster = await api.get(f"/api/v1/requirements/{ravi_job}/telephonic/candidates")
    assert roster.status_code == 404
    started = await api.post("/api/v1/calls/start", json={"candidate_ids": [ravi_kumar]})
    assert {r["error"]["code"] for r in started.json()["data"]} == {"candidate_not_found"}

    # Ravi: his job (without the admin's upload) and his candidate's telephonic round
    await _login(api, "ravi@acme.example")
    assert await _jobs(api) == {"Sales Executive": 2}
    assert await _names(api, requirement_id=ravi_job) == ["Priya Shah", "Ravi Kumar"]
    assert (await api.get(f"/api/v1/requirements/{neha_job}")).status_code == 404
    assert (await api.get(f"/api/v1/candidates/{priya}")).status_code == 200
    assert (await api.get(f"/api/v1/calls/{s['attempt']}/answers")).status_code == 200
    roster = (await api.get(f"/api/v1/requirements/{ravi_job}/telephonic/candidates")).json()
    assert [r["name"] for r in roster["data"]["rows"]] == ["Priya Shah"]

    # The super admin sees every recruiter's jobs and candidates
    await _login(api, "owner@acme.example")
    assert await _jobs(api) == {"Sales Executive": 3, "Telecaller": 2}
    assert await _names(api, requirement_id=ravi_job) == ["Priya Shah", "Ravi Kumar", "Sunil Rao"]
    summary = (await api.get("/api/v1/dashboard/summary")).json()["data"]
    assert summary["kpis"]["candidates_total"] == 5
    assert (await api.get(f"/api/v1/calls/{s['attempt']}/answers")).status_code == 200
    calls = (await api.get("/api/v1/calls", params={"purpose": "telephonic"})).json()["data"]
    assert [c["id"] for c in calls] == [s["attempt"]]
