import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import AppEnv, Settings, load_settings
from app.main import create_app

TEST_SECRET = "test-only-secret-key-0123456789abcdef"
TEST_ORIGIN = "http://localhost:3000"
TEST_PASSWORD = "correct-horse-battery"

# Integration tests use their own database so they never touch development data.
TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5433/recruitment_ai_test",
)
TEST_REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6380/0")


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": AppEnv.TEST,
        "app_secret_key": TEST_SECRET,
        "database_url": TEST_DATABASE_URL,
        "redis_url": TEST_REDIS_URL,
        "frontend_origin": TEST_ORIGIN,
        "tts_preload": False,
        # never pick up the developer's real key from the environment (Docker passes .env)
        "deepgram_api_key": None,
        "_env_file": None,
    }
    values.update(overrides)
    return load_settings(**values)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers={"Origin": TEST_ORIGIN}
        ) as http:
            http.app = app  # type: ignore[attr-defined]
            yield http


# --- Database ---------------------------------------------------------------------------------


async def ensure_database(url: str, *, recreate: bool = False) -> None:
    """Create the database named in `url` (via the `postgres` maintenance DB) if missing."""
    parsed = make_url(url)
    admin = create_async_engine(
        parsed.set(database="postgres"), poolclass=NullPool, isolation_level="AUTOCOMMIT"
    )
    try:
        async with admin.connect() as conn:
            name = parsed.database
            if recreate:
                await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await admin.dispose()


def run_alembic(url: str, *commands: tuple[str, str]) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini"))
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        for name, target in commands:
            if target:
                getattr(command, name)(config, target)
            else:
                getattr(command, name)(config)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[str]:
    """The test database, migrated to head once per run. Skips if Postgres isn't running."""
    try:
        asyncio.run(asyncio.wait_for(ensure_database(TEST_DATABASE_URL), timeout=5))
    except Exception:
        pytest.skip("Postgres not reachable; start it with `make up`")
    run_alembic(TEST_DATABASE_URL, ("upgrade", "head"))
    yield TEST_DATABASE_URL


@pytest.fixture
async def db_session(migrated_database: str) -> AsyncIterator[AsyncSession]:
    """A session inside an outer transaction that is rolled back after the test.

    Service-level commits become savepoint releases, so nothing persists between tests.
    """
    engine = create_async_engine(migrated_database, poolclass=NullPool)
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()
    await engine.dispose()


@pytest.fixture
async def api(client: AsyncClient, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """API client wired to the per-test transactional session. Not logged in."""
    from app.database.connection import get_session
    from app.utils.redis import get_redis

    async def _session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app: Any = client.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_session] = _session
    redis = get_redis()
    async for key in redis.scan_iter("rcai:ratelimit:login:*"):
        await redis.delete(key)
    yield client


@pytest.fixture
async def user(db_session: AsyncSession) -> Any:
    from app.database.models import User
    from app.services.auth_service import hash_password

    account = User(
        email=f"recruiter-{uuid.uuid4().hex[:8]}@example.com",
        name="Test Recruiter",
        password_hash=hash_password(TEST_PASSWORD),
    )
    db_session.add(account)
    await db_session.flush()
    return account


@pytest.fixture
async def authed(api: AsyncClient, user: Any) -> AsyncClient:
    """API client logged in as a recruiter (session cookie set)."""
    response = await api.post(
        "/api/v1/auth/login", json={"email": user.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return api


@pytest.fixture
async def active_job(authed: AsyncClient) -> dict[str, Any]:
    response = await authed.post(
        "/api/v1/jobs", json={"job_title": "Backend Developer", "company_name": "Test Co"}
    )
    assert response.status_code == 201, response.text
    job: dict[str, Any] = response.json()["data"]
    assert job["is_active"] is True
    return job
