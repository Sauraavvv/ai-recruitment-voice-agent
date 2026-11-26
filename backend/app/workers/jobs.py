"""The worker's jobs and schedules, shared by the standalone worker (workers/settings.py, run
with arq) and the worker inside the API process (RUN_WORKER_IN_API, app/main.py).

Nothing here reads the settings at import time.
"""

from typing import Any

from arq import cron, func

from app.database.connection import get_sessionmaker
from app.utils.log import get_logger
from app.utils.redis import WORKER_HEARTBEAT_KEY, WORKER_HEARTBEAT_TTL_SECONDS
from app.workers.call_worker import (
    MAX_SLOT_WAITS,
    finalize_call,
    initiate_call,
    reconcile_calls,
    reconcile_finalize,
)
from app.workers.evaluation_worker import evaluate_round, reconcile_evaluations
from app.workers.retry_worker import dispatch_retries

logger = get_logger(__name__)


async def heartbeat(ctx: dict[str, Any]) -> None:
    """Lets /health/ready confirm a worker is alive."""
    await ctx["redis"].set(WORKER_HEARTBEAT_KEY, "1", ex=WORKER_HEARTBEAT_TTL_SECONDS)


async def expire_import_previews(ctx: dict[str, Any]) -> None:
    """Expire upload previews older than 24 h and delete their stored rows."""
    from app.services.import_service import expire_stale_previews

    async with get_sessionmaker()() as session:
        expired = await expire_stale_previews(session)
    if expired:
        logger.info("import_previews_expired", count=expired)


FUNCTIONS: list[Any] = [
    func(initiate_call, max_tries=MAX_SLOT_WAITS + 1),
    func(finalize_call, max_tries=3),
    # Step 6c: one try (a failure is stored and the reconciler retries); no result kept, so
    # "Re-evaluate" can queue it again
    func(evaluate_round, max_tries=1, keep_result=0, timeout=600),
]

CRON_JOBS: list[Any] = [
    cron(heartbeat, second={0, 30}, run_at_startup=False),
    cron(expire_import_previews, minute={7}, second={0}, run_at_startup=True),
    # Stuck-call reconciler: every 2 minutes and once at startup (phase-05 P5-T4)
    cron(reconcile_calls, minute=set(range(0, 60, 2)), second={15}, run_at_startup=True),
    # Phase 7: unfinished finalizations, every 10 minutes
    cron(reconcile_finalize, minute=set(range(1, 60, 10)), second={30}, run_at_startup=True),
    # Phase 9: due retries and callbacks, missed retry decisions, lost call jobs
    cron(dispatch_retries, minute=set(range(0, 60, 5)), second={50}, run_at_startup=True),
    # Step 6c: missing, failed or lost evaluations of round calls
    cron(reconcile_evaluations, minute=set(range(5, 60, 10)), second={20}),
]
