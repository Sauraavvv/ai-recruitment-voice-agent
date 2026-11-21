"""Requirements: openings under a client, visible to whoever sees the client."""

from typing import Any

import pytest
from httpx import AsyncClient

from app.tests.conftest import TEST_PASSWORD, client_body

SALES = {
    "title": " Sales Executive ",
    "location": "Pune",
    "work_mode": "onsite",
    "openings": 10,
    "experience_min": 1,
    "experience_max": 4.5,
    "ctc_min": 3,
    "ctc_max": 6,
    "notice_max_days": 30,
    "skills": ["Field sales", " field  SALES ", "", "Hindi"],
    "must_haves": ["Own two-wheeler", "Speaks Marathi"],
    "job_description": "Sell our products door to door.",
    "deadline": "2026-12-31",
}


@pytest.fixture
async def authed(admin: AsyncClient) -> AsyncClient:
    """Clients and requirements are a super admin's: log in as one."""
    return admin


async def _client(api: AsyncClient, name: str = "Easy Recruitz 365") -> dict[str, Any]:
    response = await api.post("/api/v1/clients", json=client_body(name))
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def test_add_list_view_edit(authed: AsyncClient) -> None:
    client = await _client(authed)
    base = f"/api/v1/clients/{client['id']}/requirements"

    created = await authed.post(base, json=SALES)
    assert created.status_code == 201, created.text
    req = created.json()["data"]
    assert (
        req
        | {
            "title": "Sales Executive",
            "client_id": client["id"],
            "skills": ["Field sales", "Hindi"],
            "experience_max": 4.5,
            "status": "open",
            "deadline": "2026-12-31",
        }
        == req
    )

    assert [r["id"] for r in (await authed.get(base)).json()["data"]] == [req["id"]]
    url = f"/api/v1/requirements/{req['id']}"
    assert (await authed.get(url)).json()["data"]["title"] == "Sales Executive"

    # partial edit; null clears optional numbers but not the title
    edited = await authed.patch(
        url, json={"status": "on_hold", "ctc_max": None, "title": None, "openings": 12}
    )
    assert edited.status_code == 200, edited.text
    data = edited.json()["data"]
    assert (data["status"], data["ctc_max"], data["ctc_min"], data["title"], data["openings"]) == (
        "on_hold",
        None,
        3,
        "Sales Executive",
        12,
    )

    # the client list counts open requirements
    await authed.post(base, json={"title": "Telecaller"})
    clients = (await authed.get("/api/v1/clients")).json()["data"]
    assert clients[0]["open_requirements"] == 1


async def test_order_open_first(authed: AsyncClient) -> None:
    client = await _client(authed)
    base = f"/api/v1/clients/{client['id']}/requirements"
    for title, status in (("A", "closed"), ("B", "open"), ("C", "on_hold"), ("D", "open")):
        assert (await authed.post(base, json={"title": title, "status": status})).status_code == 201
    rows = (await authed.get(base)).json()["data"]
    # (in one test transaction every row has the same created_at, so only the groups are fixed)
    assert [r["status"] for r in rows] == ["open", "open", "on_hold", "closed"]
    assert {r["title"] for r in rows[:2]} == {"B", "D"}


async def test_validation(authed: AsyncClient) -> None:
    client = await _client(authed)
    base = f"/api/v1/clients/{client['id']}/requirements"
    for change in (
        {"title": " "},
        {"openings": 0},
        {"experience_min": 5, "experience_max": 2},
        {"ctc_min": 10, "ctc_max": 5},
        {"experience_max": 80},
        {"work_mode": "moon"},
        {"must_haves": [f"item {i}" for i in range(16)]},
        {"skills": ["x" * 61]},
        {"status": "deleted"},
        {"client_id": client["id"]},
    ):
        response = await authed.post(base, json={"title": "Role"} | change)
        assert response.status_code == 422, (change, response.text)

    req = (await authed.post(base, json={"title": "Role", "ctc_min": 4})).json()["data"]
    # an edit that would put min above the saved max (or the other way) is refused
    bad = await authed.patch(f"/api/v1/requirements/{req['id']}", json={"ctc_max": 2})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_range"


async def test_hidden_with_the_client(api: AsyncClient) -> None:
    signup = {
        "organization_name": "Acme",
        "name": "Owner",
        "email": "owner@acme.example",
        "password": TEST_PASSWORD,
    }
    assert (await api.post("/api/v1/auth/signup", json=signup)).status_code == 201
    member = {"name": "Ravi", "email": "ravi@acme.example", "password": TEST_PASSWORD}
    assert (await api.post("/api/v1/team", json=member)).status_code == 201

    client = await _client(api)  # the owner's client
    req = (
        await api.post(f"/api/v1/clients/{client['id']}/requirements", json={"title": "Role"})
    ).json()["data"]

    await api.post("/api/v1/auth/logout")
    login = {"email": "ravi@acme.example", "password": TEST_PASSWORD}
    assert (await api.post("/api/v1/auth/login", json=login)).status_code == 200
    base = f"/api/v1/clients/{client['id']}/requirements"
    assert (await api.get(base)).status_code == 404
    assert (await api.post(base, json={"title": "Sneaky"})).status_code == 404
    url = f"/api/v1/requirements/{req['id']}"
    assert (await api.get(url)).status_code == 404
    assert (await api.patch(url, json={"title": "X"})).status_code == 404


async def test_all_jobs(api: AsyncClient) -> None:
    signup = {
        "organization_name": "Acme",
        "name": "Owner",
        "email": "owner@acme.example",
        "password": TEST_PASSWORD,
    }
    assert (await api.post("/api/v1/auth/signup", json=signup)).status_code == 201
    member = {"name": "Ravi", "email": "ravi@acme.example", "password": TEST_PASSWORD}
    assert (await api.post("/api/v1/team", json=member)).status_code == 201

    first, second = await _client(api, "Alpha"), await _client(api, "Beta")
    for client, title, status in ((first, "Sales", "closed"), (second, "Telecaller", "open")):
        body = {"title": title, "status": status}
        url = f"/api/v1/clients/{client['id']}/requirements"
        assert (await api.post(url, json=body)).status_code == 201

    jobs = (await api.get("/api/v1/requirements")).json()["data"]
    assert [(j["title"], j["client_name"]) for j in jobs] == [
        ("Telecaller", "Beta"),  # open first
        ("Sales", "Alpha"),
    ]
    assert jobs[0]["candidates"] == 0 and jobs[0]["client_status"] == "active"

    # a recruiter sees no clients, so no jobs; another company sees none of these
    await api.post("/api/v1/auth/logout")
    login = {"email": "ravi@acme.example", "password": TEST_PASSWORD}
    assert (await api.post("/api/v1/auth/login", json=login)).status_code == 200
    assert (await api.get("/api/v1/requirements")).json()["data"] == []
    await api.post("/api/v1/auth/logout")
    other = signup | {"organization_name": "Other", "email": "boss@other.example"}
    assert (await api.post("/api/v1/auth/signup", json=other)).status_code == 201
    assert (await api.get("/api/v1/requirements")).json()["data"] == []
