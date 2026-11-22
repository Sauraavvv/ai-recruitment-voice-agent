"""P8-AC1: the dashboard's stat tiles against plain SQL, on the configured database.

    python -m app.scripts.dashboard_check        (make dashboard-check)

Read-only. Each metric is computed twice: by dashboard_service.stats (what /dashboard/stats
returns) and by a hand-written SQL query from the definitions in phase-08 §5.1. Exit 1 on any
difference.
"""

import asyncio
import sys

from sqlalchemy import text

from app.config import get_settings
from app.database.connection import dispose_engine, get_sessionmaker, init_engine
from app.services import dashboard_service

LATEST = """
    (SELECT DISTINCT ON (a.candidate_id) a.candidate_id, a.call_status, a.end_reason
       FROM call_attempts a JOIN candidates c ON c.id = a.candidate_id
      WHERE c.deleted_at IS NULL AND a.purpose = 'screening'
        AND a.call_status NOT IN ('retry_scheduled', 'callback_requested')
      ORDER BY a.candidate_id, a.attempt_number DESC) latest
"""
SQL = {
    "total_candidates": "SELECT count(*) FROM candidates WHERE deleted_at IS NULL",
    # Screening calls only: telephonic round calls never change the dashboard (phase-11 6b)
    "calls_completed": (
        "SELECT count(*) FROM call_attempts WHERE purpose = 'screening' "
        "AND call_status = 'completed'"
    ),
    "calls_pending": (
        "SELECT count(*) FROM call_attempts WHERE purpose = 'screening' "
        "AND call_status IN ('pending', 'queued', 'initiating')"
    ),
    "calls_in_progress": (
        "SELECT count(*) FROM call_attempts WHERE purpose = 'screening' "
        "AND call_status IN ('ringing', 'in_progress')"
    ),
    # constant SQL only (no input reaches these strings)
    "unanswered_calls": (
        f"SELECT count(*) FROM {LATEST} WHERE call_status IN ('no_answer', 'busy') "  # noqa: S608
        "OR (call_status = 'exhausted' AND end_reason IN ('no_answer', 'busy'))"
    ),
    "failed_calls": (
        f"SELECT count(*) FROM {LATEST} WHERE call_status = 'failed' "  # noqa: S608
        "OR (call_status = 'exhausted' "
        "AND (end_reason IS NULL OR end_reason NOT IN ('no_answer', 'busy')))"
    ),
    "interested_candidates": (
        "SELECT count(*) FROM candidates WHERE deleted_at IS NULL AND interested IS TRUE"
    ),
    "screening_completed": (
        "SELECT count(*) FROM candidates "
        "WHERE deleted_at IS NULL AND screening_status = 'completed'"
    ),
    "scheduled_retries": (
        "SELECT count(*) FROM call_attempts WHERE purpose = 'screening' "
        "AND call_status IN ('retry_scheduled', 'callback_requested')"
    ),
}


async def main() -> int:
    settings = get_settings()
    init_engine(settings.database_url.get_secret_value())
    problems = 0
    try:
        async with get_sessionmaker()() as session:
            stats = await dashboard_service.stats(session, tz=settings.app_timezone)
            for metric, query in SQL.items():
                expected = int((await session.execute(text(query))).scalar_one())
                got = stats[metric]
                ok = got == expected
                problems += not ok
                print(f"{'ok  ' if ok else 'DIFF'} {metric:<24} api={got:<6} sql={expected}")
    finally:
        await dispose_engine()
    print(f"{len(SQL)} metrics, {problems} differences")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
