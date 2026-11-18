"""P1-AC6: every /api/v1 route except login requires a session."""

from typing import Any

import pytest
from httpx import AsyncClient

from app.config import AppEnv
from app.main import create_app
from app.tests.conftest import TEST_PASSWORD, make_settings

PUBLIC_ROUTES = {("POST", "/api/v1/auth/login")}
SAMPLE_ID = "00000000-0000-0000-0000-000000000001"


def _protected_routes() -> list[tuple[str, str]]:
    schema = create_app(make_settings(app_env=AppEnv.TEST)).openapi()
    routes = []
    for path, operations in schema["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for method in operations:
            if (method.upper(), path) not in PUBLIC_ROUTES:
                routes.append((method.upper(), path))
    return sorted(routes)


PROTECTED = _protected_routes()


def test_route_list_is_not_empty() -> None:
    assert len(PROTECTED) >= 15


@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_requires_login(api: AsyncClient, method: str, path: str) -> None:
    url = path
    for name in ("candidate_id", "job_id", "import_id"):
        url = url.replace("{" + name + "}", SAMPLE_ID)
    response = await api.request(method, url)
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "not_authenticated"


async def test_login_me_logout(api: AsyncClient, user: Any) -> None:
    response = await api.post(
        "/api/v1/auth/login", json={"email": user.email.upper(), "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "rcai_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert response.json()["data"]["email"] == user.email

    me = await api.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["name"] == "Test Recruiter"

    assert (await api.post("/api/v1/auth/logout")).status_code == 200
    assert (await api.get("/api/v1/auth/me")).status_code == 401


async def test_forged_session_cookie_rejected(api: AsyncClient) -> None:
    api.cookies.set("rcai_session", "made-up-token")
    assert (await api.get("/api/v1/auth/me")).status_code == 401


async def test_wrong_password_and_unknown_email_look_the_same(api: AsyncClient, user: Any) -> None:
    wrong = await api.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "wrong-password"}
    )
    unknown = await api.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "x"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"]
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


async def test_login_rate_limited(api: AsyncClient, user: Any) -> None:
    body = {"email": user.email, "password": "wrong-password"}
    for _ in range(5):
        assert (await api.post("/api/v1/auth/login", json=body)).status_code == 401
    limited = await api.post("/api/v1/auth/login", json=body)
    assert limited.status_code == 429
    # Even the right password is refused until the window passes.
    body["password"] = TEST_PASSWORD
    assert (await api.post("/api/v1/auth/login", json=body)).status_code == 429


async def test_mutations_require_frontend_origin(authed: AsyncClient) -> None:
    payload = {"job_title": "X", "company_name": "Y"}
    foreign = await authed.post(
        "/api/v1/jobs", json=payload, headers={"Origin": "https://evil.example"}
    )
    assert foreign.status_code == 403
    assert foreign.json()["error"]["code"] == "csrf_failed"

    missing = await authed.post("/api/v1/jobs", json=payload, headers={"Origin": ""})
    assert missing.status_code == 403

    via_referer = await authed.post(
        "/api/v1/jobs",
        json=payload,
        headers={"Origin": "", "Referer": "http://localhost:3000/settings/job"},
    )
    assert via_referer.status_code == 201
    # Reads don't need an Origin header.
    assert (await authed.get("/api/v1/jobs", headers={"Origin": ""})).status_code == 200
