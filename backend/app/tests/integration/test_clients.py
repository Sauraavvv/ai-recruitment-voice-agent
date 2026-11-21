"""Clients: the organization's super admins add, edit and see them; recruiters don't (yet)."""

from typing import Any

from httpx import AsyncClient

from app.tests.conftest import TEST_PASSWORD, client_body

EASY = client_body(
    "  Easy Recruitz 365 ",
    website="easyrecruitz365.example",
    email="HR@EasyRecruitz.example",
    address="Office 4, Baner Road",
    contact_designation="HR Manager",
    notes="Bulk sales hiring",
)


async def _signup(api: AsyncClient, email: str, org: str = "Acme") -> dict[str, Any]:
    body = {"organization_name": org, "name": "Owner", "email": email, "password": TEST_PASSWORD}
    response = await api.post("/api/v1/auth/signup", json=body)
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def _login(api: AsyncClient, email: str, password: str = TEST_PASSWORD) -> None:
    await api.post("/api/v1/auth/logout")
    response = await api.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


async def _add_member(api: AsyncClient, email: str, role: str = "recruiter") -> None:
    body = {"name": "Member", "email": email, "password": TEST_PASSWORD, "role": role}
    assert (await api.post("/api/v1/team", json=body)).status_code == 201


async def test_add_view_edit_client(admin: AsyncClient) -> None:
    created = await admin.post("/api/v1/clients", json=EASY)
    assert created.status_code == 201, created.text
    client = created.json()["data"]
    expected = {
        "name": "Easy Recruitz 365",
        "industry": "BPO / KPO",
        "website": "https://easyrecruitz365.example",
        "email": "hr@easyrecruitz.example",
        "address": "Office 4, Baner Road",
        "city": "Pune",
        "state": "Maharashtra",
        "contact_name": "Neha Joshi",
        "contact_designation": "HR Manager",
        "contact_phone": "+919876543210",
        "is_confidential": False,
        "status": "active",
    }
    assert client | expected == client

    url = f"/api/v1/clients/{client['id']}"
    assert (await admin.get(url)).json()["data"]["name"] == "Easy Recruitz 365"

    edited = await admin.patch(
        url,
        json={"status": "on_hold", "is_confidential": True, "address": "", "state": "Goa"},
    )
    assert edited.status_code == 200, edited.text
    data = edited.json()["data"]
    assert (data["status"], data["is_confidential"], data["address"], data["state"]) == (
        "on_hold",
        True,
        "",
        "Goa",
    )


async def test_required_fields_and_validation(admin: AsyncClient) -> None:
    for field in ("industry", "email", "city", "state", "contact_name", "contact_phone"):
        body = {k: v for k, v in client_body().items() if k != field}
        response = await admin.post("/api/v1/clients", json=body)
        assert response.status_code == 422, (field, response.text)

    for change in (
        {"name": " "},
        {"industry": "Mining"},
        {"state": "Pune"},
        {"city": " "},
        {"contact_phone": "12"},
        {"email": "nope"},
        {"website": "not a site"},
        {"status": "deleted"},
        {"created_by_id": "x"},
    ):
        response = await admin.post("/api/v1/clients", json=client_body("New") | change)
        assert response.status_code == 422, (change, response.text)

    # required fields can't be emptied on edit
    client = (await admin.post("/api/v1/clients", json=client_body("Kept"))).json()["data"]
    for change in ({"email": ""}, {"contact_name": " "}, {"city": ""}):
        response = await admin.patch(f"/api/v1/clients/{client['id']}", json=change)
        assert response.status_code == 422, (change, response.text)


async def test_list_search_and_order(admin: AsyncClient) -> None:
    for name, city, status in (
        ("Zeta Corp", "Delhi", "closed"),
        ("Alpha Tech", "Pune", "active"),
        ("Beta Foods", "Mumbai", "on_hold"),
    ):
        body = client_body(name, city=city, status=status)
        assert (await admin.post("/api/v1/clients", json=body)).status_code == 201

    names = [c["name"] for c in (await admin.get("/api/v1/clients")).json()["data"]]
    assert names == ["Alpha Tech", "Beta Foods", "Zeta Corp"]  # closed last
    pune = (await admin.get("/api/v1/clients", params={"q": "pune"})).json()["data"]
    assert [c["name"] for c in pune] == ["Alpha Tech"]
    held = (await admin.get("/api/v1/clients", params={"status": "on_hold"})).json()["data"]
    assert [c["name"] for c in held] == ["Beta Foods"]


async def test_duplicate_name(admin: AsyncClient) -> None:
    assert (await admin.post("/api/v1/clients", json=client_body("Easy"))).status_code == 201
    other = (await admin.post("/api/v1/clients", json=client_body("Other"))).json()["data"]
    dup = await admin.post("/api/v1/clients", json=client_body(" EASY "))
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "client_name_taken"
    rename = await admin.patch(f"/api/v1/clients/{other['id']}", json={"name": "easy"})
    assert rename.status_code == 409


async def test_recruiters_cant_add_or_see_clients(authed: AsyncClient) -> None:
    created = await authed.post("/api/v1/clients", json=EASY)
    assert created.status_code == 403
    assert created.json()["error"]["code"] == "admin_required"
    assert (await authed.get("/api/v1/clients")).json()["data"] == []


async def test_super_admins_share_their_companys_clients(api: AsyncClient) -> None:
    await _signup(api, "owner@acme.example")
    await _add_member(api, "second@acme.example", role="super_admin")
    await _add_member(api, "ravi@acme.example")
    client = (await api.post("/api/v1/clients", json=EASY)).json()["data"]
    url = f"/api/v1/clients/{client['id']}"

    # another super admin of the company sees and edits it; the name is taken company-wide
    await _login(api, "second@acme.example")
    assert [c["id"] for c in (await api.get("/api/v1/clients")).json()["data"]] == [client["id"]]
    assert (await api.patch(url, json={"city": "Mumbai"})).status_code == 200
    assert (await api.post("/api/v1/clients", json=EASY)).status_code == 409

    # a recruiter of the company sees nothing and can't edit
    await _login(api, "ravi@acme.example")
    assert (await api.get("/api/v1/clients")).json()["data"] == []
    assert (await api.get(url)).status_code == 404
    assert (await api.patch(url, json={"city": "X"})).status_code == 403

    # another company doesn't see it, and may use the same name
    await api.post("/api/v1/auth/logout")
    await _signup(api, "boss@other.example", org="Other")
    assert (await api.get("/api/v1/clients")).json()["data"] == []
    assert (await api.get(url)).status_code == 404
    assert (await api.patch(url, json={"city": "X"})).status_code == 404
    assert (await api.post("/api/v1/clients", json=EASY)).status_code == 201
