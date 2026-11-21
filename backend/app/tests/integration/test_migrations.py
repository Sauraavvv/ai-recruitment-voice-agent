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
    "app_settings",
    "call_attempts",
    "candidates",
    "clients",
    "conversations",
    "import_batches",
    "jobs",
    "organizations",
    "requirements",
    "sync_logs",
    "users",
    "webhook_events",
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


async def _sql(*statements: str) -> list[tuple[object, ...]]:
    engine = create_async_engine(URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            result = None
            for statement in statements:
                result = await conn.execute(text(statement))
            return [tuple(r) for r in result] if result is not None and result.returns_rows else []
    finally:
        await engine.dispose()


def test_0008_puts_existing_users_in_one_organization() -> None:
    try:
        asyncio.run(asyncio.wait_for(ensure_database(URL, recreate=True), timeout=10))
    except Exception:
        pytest.skip("Postgres not reachable")

    run_alembic(URL, ("upgrade", "0007"))
    asyncio.run(
        _sql(
            "INSERT INTO app_settings (key, value) "
            """VALUES ('general', '{"organization_name": "Acme Hiring"}')""",
            "INSERT INTO users (email, name, password_hash, role) VALUES "
            "('a@example.com', 'A', 'x', 'admin'), ('r@example.com', 'R', 'x', 'recruiter')",
        )
    )
    run_alembic(URL, ("upgrade", "0008"))
    rows = asyncio.run(
        _sql(
            "SELECT u.email, u.role, o.name FROM users u "
            "JOIN organizations o ON o.id = u.organization_id ORDER BY u.email"
        )
    )
    assert rows == [
        ("a@example.com", "super_admin", "Acme Hiring"),
        ("r@example.com", "recruiter", "Acme Hiring"),
    ]
    assert asyncio.run(_sql("SELECT count(*) FROM organizations")) == [(1,)]

    run_alembic(URL, ("downgrade", "0007"))
    roles = asyncio.run(_sql("SELECT email, role FROM users ORDER BY email"))
    assert roles == [("a@example.com", "admin"), ("r@example.com", "recruiter")]


def test_0008_on_an_empty_database_creates_no_organization() -> None:
    try:
        asyncio.run(asyncio.wait_for(ensure_database(URL, recreate=True), timeout=10))
    except Exception:
        pytest.skip("Postgres not reachable")

    run_alembic(URL, ("upgrade", "head"))
    assert asyncio.run(_sql("SELECT count(*) FROM organizations")) == [(0,)]
