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
    "question_sets",
    "requirements",
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


def test_0015_existing_calls_are_screening_calls() -> None:
    try:
        asyncio.run(asyncio.wait_for(ensure_database(URL, recreate=True), timeout=10))
    except Exception:
        pytest.skip("Postgres not reachable")

    run_alembic(URL, ("upgrade", "0014"))
    asyncio.run(
        _sql(
            "INSERT INTO jobs (id, job_title, company_name) "
            "VALUES ('00000000-0000-0000-0000-000000000001', 'Dev', 'Acme')",
            "INSERT INTO candidates (id, job_id, name, phone, applied_role) VALUES "
            "('00000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', "
            "'A', '+919876543210', 'Dev')",
            "INSERT INTO call_attempts (candidate_id, attempt_number, provider) "
            "VALUES ('00000000-0000-0000-0000-000000000002', 1, 'exotel')",
        )
    )
    run_alembic(URL, ("upgrade", "0015"))
    rows = asyncio.run(_sql("SELECT purpose, question_set_id FROM call_attempts"))
    assert rows == [("screening", None)]

    # A telephonic call must name its question set
    with pytest.raises(Exception, match="ck_call_attempts_telephonic_question_set"):
        asyncio.run(
            _sql(
                "INSERT INTO call_attempts (candidate_id, attempt_number, provider, purpose) "
                "VALUES ('00000000-0000-0000-0000-000000000002', 2, 'exotel', 'telephonic')"
            )
        )
    run_alembic(URL, ("downgrade", "0014"))
    assert asyncio.run(_sql("SELECT count(*) FROM call_attempts")) == [(1,)]


# test_0017: the original company (older), one signed up later, and their rows
_0017_ROWS = (
    "INSERT INTO organizations (id, name, created_at) VALUES "
    "('00000000-0000-0000-0000-0000000000a1', 'Original', now() - interval '1 day'), "
    "('00000000-0000-0000-0000-0000000000b2', 'Signed up', now())",
    "INSERT INTO users (id, organization_id, email, name, password_hash, role) VALUES "
    "('00000000-0000-0000-0000-0000000000c3', '00000000-0000-0000-0000-0000000000b2', "
    "'b@b.example', 'B', 'x', 'super_admin')",
    "INSERT INTO clients (id, organization_id, name, created_by_id) VALUES "
    "('00000000-0000-0000-0000-0000000000d4', '00000000-0000-0000-0000-0000000000b2', "
    "'Client', '00000000-0000-0000-0000-0000000000c3')",
    "INSERT INTO requirements (id, organization_id, client_id, title, created_by_id) VALUES "
    "('00000000-0000-0000-0000-0000000000e5', '00000000-0000-0000-0000-0000000000b2', "
    "'00000000-0000-0000-0000-0000000000d4', 'Dev', '00000000-0000-0000-0000-0000000000c3')",
    "INSERT INTO jobs (id, job_title, company_name) "
    "VALUES ('00000000-0000-0000-0000-000000000001', 'Dev', 'Acme')",
    "INSERT INTO candidates (id, job_id, name, phone, applied_role) VALUES "
    "('00000000-0000-0000-0000-000000000002', '00000000-0000-0000-0000-000000000001', "
    "'Old flow', '+919876543210', 'Dev')",
    "INSERT INTO candidates (id, requirement_id, name, phone, applied_role) VALUES "
    "('00000000-0000-0000-0000-000000000003', '00000000-0000-0000-0000-0000000000e5', "
    "'Requirement', '+919876543210', 'Dev')",
)
_0017_SAME_PHONE = (
    "INSERT INTO candidates (job_id, organization_id, name, phone, applied_role) VALUES "
    "('00000000-0000-0000-0000-000000000001', '00000000-0000-0000-0000-0000000000{org}', "
    "'{name}', '+919876543210', 'Dev')"
)


def test_0017_every_candidate_gets_its_company() -> None:
    try:
        asyncio.run(asyncio.wait_for(ensure_database(URL, recreate=True), timeout=10))
    except Exception:
        pytest.skip("Postgres not reachable")

    run_alembic(URL, ("upgrade", "0016"))
    asyncio.run(_sql(*_0017_ROWS))
    run_alembic(URL, ("upgrade", "0017"))
    rows = asyncio.run(_sql("SELECT name, organization_id::text FROM candidates ORDER BY name"))
    assert rows == [
        ("Old flow", "00000000-0000-0000-0000-0000000000a1"),  # the original company
        ("Requirement", "00000000-0000-0000-0000-0000000000b2"),  # its requirement's
    ]
    # The original flow's phone rule is per company now
    asyncio.run(_sql(_0017_SAME_PHONE.format(org="b2", name="Same phone")))
    with pytest.raises(Exception, match="uq_candidates_organization_id_phone"):
        asyncio.run(_sql(_0017_SAME_PHONE.format(org="a1", name="Dup")))
    asyncio.run(_sql("DELETE FROM candidates WHERE name = 'Same phone'"))
    run_alembic(URL, ("downgrade", "0016"))
    assert asyncio.run(_sql("SELECT count(*) FROM candidates")) == [(2,)]


def test_0018_google_sheets_is_gone() -> None:
    try:
        asyncio.run(asyncio.wait_for(ensure_database(URL, recreate=True), timeout=10))
    except Exception:
        pytest.skip("Postgres not reachable")

    run_alembic(URL, ("upgrade", "0017"))
    asyncio.run(
        _sql(
            "INSERT INTO app_settings (key, value) VALUES "
            "('google_sheets', '{\"sheet_id\": \"x\"}'), ('general', '{}')"
        )
    )
    run_alembic(URL, ("upgrade", "0018"))
    assert asyncio.run(_sql("SELECT to_regclass('sync_logs')")) == [(None,)]
    assert asyncio.run(_sql("SELECT key FROM app_settings")) == [("general",)]
    run_alembic(URL, ("downgrade", "0017"))
    assert asyncio.run(_sql("SELECT count(*) FROM sync_logs")) == [(0,)]


def test_0019_the_shared_default_questions_go_to_the_oldest_company() -> None:
    try:
        asyncio.run(asyncio.wait_for(ensure_database(URL, recreate=True), timeout=10))
    except Exception:
        pytest.skip("Postgres not reachable")

    run_alembic(URL, ("upgrade", "0018"))
    asyncio.run(
        _sql(
            "INSERT INTO organizations (id, name, created_at) VALUES "
            "('00000000-0000-0000-0000-0000000000a1', 'Original', '2026-01-01'), "
            "('00000000-0000-0000-0000-0000000000b2', 'Signed up later', '2026-06-01')",
            "INSERT INTO app_settings (key, value) VALUES "
            "('default_questions', '[{\"key\": \"q_x\", \"prompt\": \"X?\"}]'), ('general', '{}')",
        )
    )
    run_alembic(URL, ("upgrade", "0019"))
    rows = asyncio.run(_sql("SELECT key FROM app_settings ORDER BY key"))
    assert rows == [("default_questions:00000000-0000-0000-0000-0000000000a1",), ("general",)]
    asyncio.run(
        _sql(
            "INSERT INTO app_settings (key, value) VALUES "
            "('default_questions:00000000-0000-0000-0000-0000000000b2', '[]')"
        )
    )
    run_alembic(URL, ("downgrade", "0018"))
    rows = asyncio.run(_sql("SELECT key FROM app_settings ORDER BY key"))
    assert rows == [("default_questions",), ("general",)]


def test_0020_uploaded_candidates_get_their_uploader() -> None:
    try:
        asyncio.run(asyncio.wait_for(ensure_database(URL, recreate=True), timeout=10))
    except Exception:
        pytest.skip("Postgres not reachable")

    run_alembic(URL, ("upgrade", "0019"))
    asyncio.run(
        _sql(
            *_0017_ROWS[:4],
            # a confirmed upload by user c3; its candidate's consent time is the confirm time
            "INSERT INTO import_batches (uploaded_by, requirement_id, filename, status, headers, "
            "column_mapping, report, confirmed_at) VALUES ('00000000-0000-0000-0000-0000000000c3', "
            "'00000000-0000-0000-0000-0000000000e5', 'list.csv', 'confirmed', '[]', '{}', '{}', "
            "'2026-11-01 10:00+00')",
            "INSERT INTO candidates (organization_id, requirement_id, name, phone, applied_role, "
            "consent_source, consent_at) VALUES "
            "('00000000-0000-0000-0000-0000000000b2', '00000000-0000-0000-0000-0000000000e5', "
            "'Uploaded', '+919876543210', 'Dev', 'recruiter_attested_import', "
            "'2026-11-01 10:00+00'), "
            "('00000000-0000-0000-0000-0000000000b2', '00000000-0000-0000-0000-0000000000e5', "
            "'Unknown', '+919876543211', 'Dev', 'recruiter_attested_import', "
            "'2026-11-02 10:00+00')",
        )
    )
    run_alembic(URL, ("upgrade", "0020"))
    rows = asyncio.run(_sql("SELECT name, uploaded_by_id::text FROM candidates ORDER BY name"))
    assert rows == [
        ("Unknown", None),  # no matching upload: only super admins see it
        ("Uploaded", "00000000-0000-0000-0000-0000000000c3"),
    ]
    run_alembic(URL, ("downgrade", "0019"))
    assert asyncio.run(_sql("SELECT count(*) FROM candidates")) == [(2,)]
