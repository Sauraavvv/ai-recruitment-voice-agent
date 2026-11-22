"""Filtering the candidates and calls lists by client (the Candidates, Screening calls and
Telephonic round pages). Another organization's client is not found."""

import uuid
from datetime import UTC, datetime
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import CallAttempt, Candidate
from app.tests.integration.test_requirement_screening import _confirm, _import, _requirement


async def _with_candidates(api: AsyncClient, csv: bytes) -> dict[str, Any]:
    requirement = await _requirement(api)
    await _confirm(api, (await _import(api, requirement["id"], csv))["id"])
    return requirement


def _attempt(candidate: Candidate, purpose: str) -> CallAttempt:
    return CallAttempt(
        candidate_id=candidate.id,
        attempt_number=1,
        attempt_type="manual",
        purpose=purpose,
        provider="exotel",
        call_status="completed",
        end_time=datetime.now(UTC),
        retry_evaluated_at=datetime.now(UTC),
    )


async def test_lists_filtered_by_client(admin: AsyncClient, db_session: AsyncSession) -> None:
    first = await _with_candidates(admin, b"Name,Phone\nRavi Kumar,9876543210\n")
    second = await _with_candidates(admin, b"Name,Phone\nPriya Shah,9876543211\n")
    people = {
        c.name: c
        for c in (await db_session.execute(select(Candidate))).scalars()
        if c.requirement_id
    }
    db_session.add(_attempt(people["Ravi Kumar"], "screening"))
    db_session.add(_attempt(people["Priya Shah"], "screening"))
    await db_session.commit()

    async def names(path: str, **params: Any) -> list[str]:
        response = await admin.get(path, params=params)
        assert response.status_code == 200, response.text
        rows = response.json()["data"]
        return sorted(r.get("candidate_name") or r["name"] for r in rows)

    assert await names("/api/v1/candidates") == ["Priya Shah", "Ravi Kumar"]
    assert await names("/api/v1/candidates", client_id=first["client_id"]) == ["Ravi Kumar"]
    assert await names("/api/v1/candidates", client_id=second["client_id"]) == ["Priya Shah"]
    assert await names("/api/v1/calls", client_id=first["client_id"]) == ["Ravi Kumar"]
    assert await names("/api/v1/calls", client_id=second["client_id"], purpose="screening") == [
        "Priya Shah"
    ]
    # No telephonic round call for that client yet
    assert await names("/api/v1/calls", client_id=second["client_id"], purpose="telephonic") == []

    # A client that isn't this organization's: not found
    for path in ("/api/v1/candidates", "/api/v1/calls"):
        response = await admin.get(path, params={"client_id": str(uuid.uuid4())})
        assert response.status_code == 404, path
