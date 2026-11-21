"""Team accounts: a super admin adds and manages the logins of their own organization."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.tests.conftest import TEST_PASSWORD

NEW = {"name": " Ravi Kumar ", "email": "Ravi@Example.com", "password": "ravi-password-1"}


async def _signup(api: AsyncClient, email: str, company: str = "Acme Hiring") -> dict[str, Any]:
    response = await api.post(
        "/api/v1/auth/signup",
        json={
            "organization_name": company,
            "name": "Owner",
            "email": email,
            "password": TEST_PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()["data"]
    return data


async def _login(api: AsyncClient, email: str, password: str) -> int:
    await api.post("/api/v1/auth/logout")
    response = await api.post("/api/v1/auth/login", json={"email": email, "password": password})
    return response.status_code


async def test_super_admin_adds_a_recruiter_who_can_log_in(api: AsyncClient) -> None:
    owner = await _signup(api, "owner@acme.example")

    added = await api.post("/api/v1/team", json=NEW)
    assert added.status_code == 201, added.text
    member = added.json()["data"]
    assert (member["name"], member["email"], member["role"], member["is_active"]) == (
        "Ravi Kumar",
        "ravi@example.com",
        "recruiter",
        True,
    )
    team = (await api.get("/api/v1/team")).json()["data"]
    assert [m["email"] for m in team] == [owner["email"], "ravi@example.com"]

    # the new login works and belongs to the same company
    assert await _login(api, "ravi@example.com", NEW["password"]) == 200
    me = (await api.get("/api/v1/auth/me")).json()["data"]
    assert me["organization"] == owner["organization"]
    # a recruiter can't manage the team
    refused = await api.get("/api/v1/team")
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "admin_required"
    assert (
        await api.post("/api/v1/team", json=NEW | {"email": "x@example.com"})
    ).status_code == 403


async def test_taken_email_and_validation(api: AsyncClient) -> None:
    await _signup(api, "owner@acme.example")
    taken = await api.post("/api/v1/team", json=NEW | {"email": "OWNER@acme.example"})
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "email_taken"
    for change in ({"password": "short"}, {"email": "nope"}, {"name": " "}, {"role": "boss"}):
        assert (await api.post("/api/v1/team", json=NEW | change)).status_code == 422


async def test_deactivate_role_and_password(api: AsyncClient) -> None:
    await _signup(api, "owner@acme.example")
    member = (await api.post("/api/v1/team", json=NEW)).json()["data"]
    url = f"/api/v1/team/{member['id']}"

    off = await api.patch(url, json={"is_active": False})
    assert off.status_code == 200 and off.json()["data"]["is_active"] is False
    assert await _login(api, "ravi@example.com", NEW["password"]) == 401

    assert await _login(api, "owner@acme.example", TEST_PASSWORD) == 200
    changed = await api.patch(
        url, json={"is_active": True, "role": "super_admin", "password": "new-password-22"}
    )
    assert changed.json()["data"]["role"] == "super_admin"
    assert await _login(api, "ravi@example.com", NEW["password"]) == 401
    assert await _login(api, "ravi@example.com", "new-password-22") == 200
    assert (await api.get("/api/v1/team")).status_code == 200  # now a super admin


async def test_super_admin_cant_lock_themselves_out(api: AsyncClient) -> None:
    owner = await _signup(api, "owner@acme.example")
    url = f"/api/v1/team/{owner['id']}"
    for change in ({"is_active": False}, {"role": "recruiter"}):
        refused = await api.patch(url, json=change)
        assert refused.status_code == 409
        assert refused.json()["error"]["code"] == "cannot_change_self"
    # renaming yourself, or sending your current role, is fine
    assert (await api.patch(url, json={"name": "Asha", "role": "super_admin"})).status_code == 200


async def test_other_companies_accounts_are_out_of_reach(
    api: AsyncClient, user: Any, db_session: AsyncSession
) -> None:
    # `user` belongs to another organization
    await _signup(api, "owner@acme.example")
    team = (await api.get("/api/v1/team")).json()["data"]
    assert user.email not in [m["email"] for m in team]
    response = await api.patch(f"/api/v1/team/{user.id}", json={"is_active": False})
    assert response.status_code == 404
    await db_session.refresh(user)
    assert user.is_active
