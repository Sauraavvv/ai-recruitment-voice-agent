"""Screening calls per requirement: uploads, duplicates per opening, access, eligibility and what
the agent is told."""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Candidate, Requirement
from app.services import screening_job
from app.tests.conftest import TEST_PASSWORD, client_body

# No job-role column: a requirement's upload takes the role from the requirement
CSV = b"Name,Phone\nRavi Kumar,9876543210\nPriya Shah,9876543211\nRavi again,98765 43210\n"


@pytest.fixture
async def authed(admin: AsyncClient) -> AsyncClient:
    """Clients and requirements are a super admin's: log in as one."""
    return admin


async def _requirement(api: AsyncClient, **fields: Any) -> dict[str, Any]:
    client = (await api.post("/api/v1/clients", json=client_body(f"Client {id(fields)}"))).json()
    body = {"title": "Sales Executive", "location": "Pune"} | fields
    response = await api.post(f"/api/v1/clients/{client['data']['id']}/requirements", json=body)
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def _import(api: AsyncClient, requirement_id: str, csv: bytes = CSV) -> dict[str, Any]:
    files = {"file": ("list.csv", csv, "text/csv")}
    preview = await api.post(
        "/api/v1/candidates/import", files=files, data={"requirement_id": requirement_id}
    )
    assert preview.status_code == 201, preview.text
    data: dict[str, Any] = preview.json()["data"]
    return data


async def _confirm(api: AsyncClient, import_id: str) -> dict[str, Any]:
    url = f"/api/v1/candidates/import/{import_id}/confirm"
    response = await api.post(url, json={"consent_attested": True})
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def _listed(api: AsyncClient, requirement_id: str) -> list[dict[str, Any]]:
    response = await api.get("/api/v1/candidates", params={"requirement_id": requirement_id})
    assert response.status_code == 200, response.text
    rows: list[dict[str, Any]] = response.json()["data"]
    return rows


async def test_upload_for_a_requirement(authed: AsyncClient) -> None:
    req = await _requirement(authed)
    preview = await _import(authed, req["id"])
    assert preview["requirement_id"] == req["id"] and preview["job_id"] is None
    role = next(f for f in preview["fields"] if f["key"] == "applied_role")
    assert role["required"] is False
    report = preview["report"]
    assert (report["valid_candidates"], report["duplicates_in_file"]) == (2, 1)

    done = await _confirm(authed, preview["id"])
    assert done["report"]["imported_candidates"] == 2
    rows = await _listed(authed, req["id"])
    assert sorted(r["name"] for r in rows) == ["Priya Shah", "Ravi Kumar"]
    assert {r["applied_role"] for r in rows} == {"Sales Executive"}
    assert {r["requirement_id"] for r in rows} == {req["id"]}

    # the same people again for this opening: duplicates, nothing changes
    again = await _import(authed, req["id"])
    assert again["report"]["duplicates_existing"] == 3  # incl. the repeated row


async def test_same_person_in_two_openings_and_the_job_flow(
    authed: AsyncClient, active_job: dict[str, Any]
) -> None:
    first, second = await _requirement(authed), await _requirement(authed, title="Telecaller")
    await _confirm(authed, (await _import(authed, first["id"]))["id"])
    preview = await _import(authed, second["id"])
    assert preview["report"]["valid_candidates"] == 2  # not duplicates of the other opening
    await _confirm(authed, preview["id"])
    assert len(await _listed(authed, second["id"])) == 2

    # the original job flow still has its own phone space
    added = await authed.post(
        "/api/v1/candidates",
        json={
            "name": "Ravi Kumar",
            "phone": "9876543210",
            "applied_role": "Developer",
            "consent_attested": True,
        },
    )
    assert added.status_code == 201, added.text
    assert added.json()["data"]["job_id"] == active_job["id"]
    assert added.json()["data"]["requirement_id"] is None


async def test_requirement_candidates_are_private(api: AsyncClient) -> None:
    owner = {
        "organization_name": "Acme",
        "name": "Owner",
        "email": "owner@acme.example",
        "password": TEST_PASSWORD,
    }
    assert (await api.post("/api/v1/auth/signup", json=owner)).status_code == 201
    member = {"name": "Ravi", "email": "ravi@acme.example", "password": TEST_PASSWORD}
    assert (await api.post("/api/v1/team", json=member)).status_code == 201
    req = await _requirement(api)
    preview = await _import(api, req["id"])
    await _confirm(api, preview["id"])

    await api.post("/api/v1/auth/logout")
    login = {"email": "ravi@acme.example", "password": TEST_PASSWORD}
    assert (await api.post("/api/v1/auth/login", json=login)).status_code == 200
    listed = await api.get("/api/v1/candidates", params={"requirement_id": req["id"]})
    assert listed.status_code == 404
    everyone = (await api.get("/api/v1/candidates")).json()["data"]
    assert not any(r["requirement_id"] == req["id"] for r in everyone)
    files = {"file": ("list.csv", CSV, "text/csv")}
    upload = await api.post(
        "/api/v1/candidates/import", files=files, data={"requirement_id": req["id"]}
    )
    assert upload.status_code == 404
    assert (await api.get(f"/api/v1/candidates/import/{preview['id']}")).status_code == 404


async def test_upload_for_both_targets_refused(
    authed: AsyncClient, active_job: dict[str, Any]
) -> None:
    req = await _requirement(authed)
    files = {"file": ("list.csv", CSV, "text/csv")}
    response = await authed.post(
        "/api/v1/candidates/import",
        files=files,
        data={"requirement_id": req["id"], "job_id": active_job["id"]},
    )
    assert response.status_code == 422


async def test_calls_stop_when_the_opening_or_client_closes(authed: AsyncClient) -> None:
    req = await _requirement(authed)
    await _confirm(authed, (await _import(authed, req["id"]))["id"])

    def reasons(rows: list[dict[str, Any]]) -> set[str | None]:
        return {r["eligibility"]["reason"] for r in rows}

    assert "job_inactive" not in reasons(await _listed(authed, req["id"]))
    await authed.patch(f"/api/v1/requirements/{req['id']}", json={"status": "on_hold"})
    assert reasons(await _listed(authed, req["id"])) == {"job_inactive"}

    await authed.patch(f"/api/v1/requirements/{req['id']}", json={"status": "open"})
    await authed.patch(f"/api/v1/clients/{req['client_id']}", json={"status": "closed"})
    assert reasons(await _listed(authed, req["id"])) == {"job_inactive"}


async def test_what_the_screening_call_uses(authed: AsyncClient, db_session: AsyncSession) -> None:
    req = await _requirement(
        authed,
        work_mode="hybrid",
        experience_min=1,
        experience_max=4.5,
        skills=["Field sales"],
        must_haves=["Own two-wheeler", "Speaks Marathi"],
        job_description="Secret client name inside",
    )
    requirement = await db_session.get(Requirement, req["id"])
    assert requirement is not None
    job = await screening_job.for_requirement(db_session, requirement)
    me = (await authed.get("/api/v1/auth/me")).json()["data"]

    assert job.company_name == me["organization"]["name"]  # the firm, never the client
    assert job.job_title == "Sales Executive"
    assert job.location == "Pune (hybrid)"
    assert job.required_experience == "1 to 4.5 years"
    assert job.job_description == ""  # the JD is for the telephonic round
    assert job.is_active is True
    keys = [q["key"] for q in job.screening_questions]
    assert keys[0] == "interested"
    assert keys[-2:] == ["must_have_1", "must_have_2"]
    must = job.screening_questions[-1]
    assert must["type"] == "boolean" and "Speaks Marathi" in must["prompt"]
    assert "client" in job.agent_instructions.lower()
    assert job not in db_session  # built on the fly, never saved

    # The page shows exactly what the call asks, in order, and where each question comes from
    shown = (await authed.get(f"/api/v1/requirements/{req['id']}/screening-questions")).json()
    rows = shown["data"]
    assert [r["key"] for r in rows] == keys
    assert [r["number"] for r in rows] == list(range(1, len(keys) + 1))
    assert {r["source"] for r in rows[:-2]} == {"default"}
    assert [(r["source"], r["must_have"]) for r in rows[-2:]] == [
        ("must_have", "Own two-wheeler"),
        ("must_have", "Speaks Marathi"),
    ]
    assert rows[-1]["prompt"] == must["prompt"]
    missing = await authed.get(f"/api/v1/requirements/{uuid.uuid4()}/screening-questions")
    assert missing.status_code == 404

    await _confirm(authed, (await _import(authed, req["id"]))["id"])
    candidate = await db_session.scalar(
        Candidate.__table__.select().where(Candidate.requirement_id == requirement.id).limit(1)
    )
    assert candidate is not None


async def test_requirement_list_counts(authed: AsyncClient, db_session: AsyncSession) -> None:
    req = await _requirement(authed)
    await _confirm(authed, (await _import(authed, req["id"]))["id"])
    url = f"/api/v1/clients/{req['client_id']}/requirements"

    row = (await authed.get(url)).json()["data"][0]
    assert (row["candidates"], row["called"], row["interested"]) == (2, 0, 0)

    rows = {r["name"]: r["id"] for r in await _listed(authed, req["id"])}
    ravi = await db_session.get(Candidate, uuid.UUID(rows["Ravi Kumar"]))
    priya = await db_session.get(Candidate, uuid.UUID(rows["Priya Shah"]))
    assert ravi is not None and priya is not None
    ravi.screening_status, ravi.interested = "completed", True
    priya.screening_status, priya.deleted_at = "declined", datetime.now(UTC)  # not counted
    await db_session.flush()

    row = (await authed.get(url)).json()["data"][0]
    assert (row["candidates"], row["called"], row["interested"]) == (1, 1, 1)
