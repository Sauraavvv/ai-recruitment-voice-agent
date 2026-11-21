"""P1-AC6: every /api/v1 route except login and sign-up requires a session."""

from typing import Any

import pytest
from httpx import AsyncClient

from app.config import AppEnv
from app.main import create_app
from app.tests.conftest import TEST_PASSWORD, make_settings

PUBLIC_ROUTES = {("POST", "/api/v1/auth/login"), ("POST", "/api/v1/auth/signup")}
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
    for name in ("candidate_id", "job_id", "import_id", "member_id", "client_id", "requirement_id"):
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


SIGNUP = {
    "organization_name": "  Acme Hiring  ",
    "name": "Asha Rao",
    "email": "Owner@Acme-Hiring.example",
    "password": " long enough password ",
}


async def test_signup_creates_organization_and_super_admin(api: AsyncClient) -> None:
    response = await api.post("/api/v1/auth/signup", json=SIGNUP)
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["role"] == "super_admin"
    assert data["email"] == "owner@acme-hiring.example"
    assert data["organization"]["name"] == "Acme Hiring"
    assert "rcai_session=" in response.headers["set-cookie"]

    # logged in straight away
    me = (await api.get("/api/v1/auth/me")).json()["data"]
    assert me["organization"] == data["organization"]

    # the password is kept as typed (spaces included)
    await api.post("/api/v1/auth/logout")
    login = await api.post(
        "/api/v1/auth/login", json={"email": data["email"], "password": SIGNUP["password"]}
    )
    assert login.status_code == 200


async def test_signup_rejects_taken_email(api: AsyncClient, user: Any) -> None:
    response = await api.post("/api/v1/auth/signup", json=SIGNUP | {"email": user.email.upper()})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


@pytest.mark.parametrize(
    "change",
    [
        {"password": "short"},
        {"email": "not-an-email"},
        {"organization_name": " "},
        {"name": ""},
        {"role": "super_admin"},  # unknown fields are refused
    ],
)
async def test_signup_validation(api: AsyncClient, change: dict[str, str]) -> None:
    response = await api.post("/api/v1/auth/signup", json=SIGNUP | change)
    assert response.status_code == 422, response.text


async def test_signup_rate_limited(api: AsyncClient) -> None:
    for i in range(5):
        body = SIGNUP | {"email": f"owner{i}@acme-hiring.example"}
        assert (await api.post("/api/v1/auth/signup", json=body)).status_code == 201
    limited = await api.post("/api/v1/auth/signup", json=SIGNUP)
    assert limited.status_code == 429


async def test_signup_off_in_production_unless_enabled() -> None:
    base = make_settings()
    production = base.model_copy(update={"app_env": AppEnv.PRODUCTION})
    assert not production.signup_allowed
    assert production.model_copy(update={"signup_enabled": True}).signup_allowed
    assert base.signup_allowed
    assert not base.model_copy(update={"signup_enabled": False}).signup_allowed
