"""P1-AC7: migrations are reversible (upgrade -> downgrade base -> upgrade on an empty DB)."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.tests.conftest import TEST_DATABASE_URL, ensure_database, run_alembic

MIGRATIONS_DB = make_url(TEST_DATABASE_URL).set(database="recruitment_ai_migrations_test")
URL = MIGRATIONS_DB.render_as_string(hide_password=False)
TABLES = {
    "alembic_version",
    "call_attempts",
    "candidates",
    "conversations",
    "import_batches",
    "jobs",
    "sync_logs",
    "users",
}


async def _tables() -> set[str]:
    engine = create_async_engine(URL, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            return {r[0] for r in rows}
    finally:
        await engine.dispose()


def test_upgrade_downgrade_upgrade() -> None:
    try:
        asyncio.run(asyncio.wait_for(ensure_database(URL, recreate=True), timeout=10))
    except Exception:
        pytest.skip("Postgres not reachable")

    run_alembic(URL, ("upgrade", "head"))
    assert asyncio.run(_tables()) == TABLES
    run_alembic(URL, ("downgrade", "base"))
    assert asyncio.run(_tables()) == {"alembic_version"}
    run_alembic(URL, ("upgrade", "head"))
    assert asyncio.run(_tables()) == TABLES
    # Models and migration agree (same as `alembic check`).
    run_alembic(URL, ("check", ""))
