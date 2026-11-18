"""Health endpoint tests.

The readiness test against real services needs Postgres and Redis running (`make up`);
it is skipped automatically when they aren't reachable.
"""

from httpx import AsyncClient

from app.api.health import get_readiness_checks
from app.database.connection import check_database
from app.utils.redis import check_redis


async def _ok() -> None:
    return None


async def _fail() -> None:
    raise ConnectionError("simulated outage")


async def test_liveness_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"data": {"status": "ok", "version": "0.0.0"}}
    assert response.headers["x-request-id"]


async def test_readiness_all_healthy(client: AsyncClient) -> None:
    client.app.dependency_overrides[get_readiness_checks] = lambda: {  # type: ignore[attr-defined]
        "database": _ok,
        "redis": _ok,
        "worker": _ok,
    }
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {
        "data": {
            "status": "ok",
            "components": {"database": "ok", "redis": "ok", "worker": "ok"},
        }
    }


async def test_readiness_reports_failed_component(client: AsyncClient) -> None:
    client.app.dependency_overrides[get_readiness_checks] = lambda: {  # type: ignore[attr-defined]
        "database": _fail,
        "redis": _ok,
        "worker": _ok,
    }
    response = await client.get("/health/ready")
    assert response.status_code == 503
    data = response.json()["data"]
    assert data["status"] == "error"
    assert data["components"] == {"database": "error", "redis": "ok", "worker": "ok"}
    assert data["errors"] == {"database": "ConnectionError"}
    assert "simulated outage" not in response.text  # no internal details leaked


async def test_readiness_against_real_services(client: AsyncClient) -> None:
    import pytest

    try:
        await check_database(timeout=1)
        await check_redis(timeout=1)
    except Exception:
        pytest.skip("Postgres/Redis not running; start them with `make up`")

    client.app.dependency_overrides[get_readiness_checks] = lambda: {  # type: ignore[attr-defined]
        "database": check_database,
        "redis": check_redis,
    }
    response = await client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["data"]["components"] == {"database": "ok", "redis": "ok"}


async def test_unknown_route_uses_error_envelope(client: AsyncClient) -> None:
    response = await client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"] == response.headers["x-request-id"]
