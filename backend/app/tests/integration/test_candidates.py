from typing import Any

from httpx import AsyncClient

NEW = {
    "name": "Test Candidate",
    "phone": "+91 90000 09001",
    "applied_role": "Backend Developer",
    "email": "test.candidate@example.com",
    "consent_attested": True,
}


async def _create(client: AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/candidates", json={**NEW, **overrides})
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def test_create_normalizes_and_links_active_job(
    authed: AsyncClient, active_job: dict[str, Any]
) -> None:
    candidate = await _create(authed)
    assert candidate["phone"] == "+919000009001"
    assert candidate["job_id"] == active_job["id"]
    assert candidate["screening_status"] == "not_started"
    assert candidate["consent_source"] == "manual"
    assert candidate["consent_at"] is not None


async def test_create_requires_consent_and_valid_fields(
    authed: AsyncClient, active_job: dict[str, Any]
) -> None:
    no_consent = await authed.post("/api/v1/candidates", json={**NEW, "consent_attested": False})
    assert no_consent.status_code == 422
    assert no_consent.json()["error"]["code"] == "consent_required"

    bad = await authed.post(
        "/api/v1/candidates", json={**NEW, "phone": "12", "email": "nope", "name": ""}
    )
    assert bad.status_code == 422
    fields = {tuple(d["loc"])[-1] for d in bad.json()["error"]["details"]}
    assert fields == {"phone", "email", "name"}


async def test_create_without_active_job(authed: AsyncClient) -> None:
    response = await authed.post("/api/v1/candidates", json=NEW)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "no_active_job"


async def test_duplicate_phone_is_409_with_existing_id(
    authed: AsyncClient, active_job: dict[str, Any]
) -> None:
    first = await _create(authed)
    response = await authed.post("/api/v1/candidates", json={**NEW, "phone": "09000009001"})
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "duplicate_phone"
    assert error["details"]["existing_candidate_id"] == first["id"]


async def test_list_search_filter_paginate(authed: AsyncClient, active_job: dict[str, Any]) -> None:
    await _create(authed, name="Test Asha Rao", phone="9000009101", email=None)
    await _create(authed, name="Test Ravi Kumar", phone="9000009102", email="ravi@example.com")
    third = await _create(authed, name="Test Meena", phone="9000009103", email=None)
    await authed.patch(f"/api/v1/candidates/{third['id']}", json={"interested": True})

    async def names(**params: Any) -> list[str]:
        response = await authed.get("/api/v1/candidates", params=params)
        assert response.status_code == 200
        return [c["name"] for c in response.json()["data"]]

    assert await names(q="asha") == ["Test Asha Rao"]
    assert await names(q="RAVI@EXAMPLE") == ["Test Ravi Kumar"]
    assert await names(q="90000 09103") == ["Test Meena"]
    assert await names(q="100%_") == []  # LIKE wildcards are escaped
    assert await names(interested="true") == ["Test Meena"]
    assert await names(screening_status="not_started", sort="name") == [
        "Test Asha Rao",
        "Test Meena",
        "Test Ravi Kumar",
    ]
    assert await names(screening_status="completed") == []

    page = await authed.get("/api/v1/candidates", params={"page_size": 2, "page": 2})
    assert page.json()["meta"] == {"page": 2, "page_size": 2, "total": 3}
    assert len(page.json()["data"]) == 1
    too_big = await authed.get("/api/v1/candidates", params={"page_size": 101})
    assert too_big.status_code == 422


async def test_update_rules(authed: AsyncClient, active_job: dict[str, Any]) -> None:
    a = await _create(authed)
    b = await _create(authed, phone="9000009002", email=None)
    url = f"/api/v1/candidates/{a['id']}"

    updated = await authed.patch(
        url, json={"current_ctc": 12.5, "notice_period": "30 days", "email": None}
    )
    assert updated.status_code == 200
    data = updated.json()["data"]
    assert data["current_ctc"] == 12.5
    assert data["email"] is None
    assert data["updated_at"] >= a["updated_at"]

    # A changed phone is re-normalized and re-checked for duplicates.
    clash = await authed.patch(url, json={"phone": "+91-90000-09002"})
    assert clash.status_code == 409
    assert clash.json()["error"]["details"]["existing_candidate_id"] == b["id"]
    moved = await authed.patch(url, json={"phone": "090000 09003"})
    assert moved.json()["data"]["phone"] == "+919000009003"

    assert (await authed.patch(url, json={"name": None})).status_code == 422

    opted = await authed.patch(url, json={"opted_out": True})
    assert opted.json()["data"]["opted_out"] is True
    assert opted.json()["data"]["screening_status"] == "opted_out"
    back = await authed.patch(url, json={"opted_out": False})
    assert back.status_code == 409
    assert back.json()["error"]["code"] == "opt_out_irreversible"


async def test_soft_delete(authed: AsyncClient, active_job: dict[str, Any]) -> None:
    candidate = await _create(authed)
    url = f"/api/v1/candidates/{candidate['id']}"
    assert (await authed.delete(url)).status_code == 200
    assert (await authed.get(url)).status_code == 404
    assert (await authed.get("/api/v1/candidates")).json()["meta"]["total"] == 0

    # The phone stays reserved: re-adding reports the deleted record.
    again = await authed.post("/api/v1/candidates", json=NEW)
    assert again.status_code == 409
    assert again.json()["error"]["details"]["deleted"] is True
