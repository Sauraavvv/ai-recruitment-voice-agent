import os
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import AppEnv, Settings, load_settings
from app.main import create_app

TEST_SECRET = "test-only-secret-key-0123456789abcdef"


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": AppEnv.TEST,
        "app_secret_key": TEST_SECRET,
        "database_url": os.getenv(
            "TEST_DATABASE_URL",
            "postgresql+asyncpg://postgres:postgres@localhost:5433/recruitment_ai",
        ),
        "redis_url": os.getenv("TEST_REDIS_URL", "redis://localhost:6380/0"),
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
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            http.app = app  # type: ignore[attr-defined]
            yield http
