"""ARQ worker configuration.

Run with: arq app.workers.settings.WorkerSettings
Jobs: initiate_call (Phase 5), finalize_call (Phase 6/7), sync_sheets (Phase 7).
Crons: reconcilers, and the retry dispatcher (Phase 9) every 5 minutes.
"""

from typing import Any, ClassVar

from arq import cron, func
from arq.connections import RedisSettings

from app.config import AppEnv, get_settings
from app.database.connection import dispose_engine, get_sessionmaker, init_engine
from app.utils.log import configure_logging, get_logger
from app.utils.redis import (
    WORKER_HEARTBEAT_KEY,
    WORKER_HEARTBEAT_TTL_SECONDS,
    close_redis,
    init_redis,
)
from app.workers.call_worker import (
    MAX_SLOT_WAITS,
    finalize_call,
    initiate_call,
    reconcile_calls,
    reconcile_finalize,
)
from app.workers.retry_worker import dispatch_retries
from app.workers.sync_worker import reconcile_sync, sync_sheets

logger = get_logger(__name__)
_settings = get_settings()


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


async def on_startup(ctx: dict[str, Any]) -> None:
    configure_logging(_settings.log_level, json_output=_settings.app_env is AppEnv.PRODUCTION)
    init_engine(_settings.database_url.get_secret_value())
    init_redis(_settings.redis_url.get_secret_value())
    ctx["settings"] = _settings
    await heartbeat(ctx)
    logger.info(
        "worker_startup", env=_settings.app_env.value, telephony=_settings.exotel_configured
    )


async def on_shutdown(ctx: dict[str, Any]) -> None:
    telephony = ctx.get("telephony")
    if telephony is not None:
        await telephony.close()
    await close_redis()
    await dispose_engine()
    logger.info("worker_shutdown")


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(_settings.redis_url.get_secret_value())
    functions: ClassVar[list[Any]] = [
        func(initiate_call, max_tries=MAX_SLOT_WAITS + 1),
        func(finalize_call, max_tries=3),
        # Retries are ours (backoff in sync_logs), not ARQ's; no result kept, so any number of
        # drains can be queued
        func(sync_sheets, max_tries=1, keep_result=0),
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(heartbeat, second={0, 30}, run_at_startup=False),
        cron(expire_import_previews, minute={7}, second={0}, run_at_startup=True),
        # Stuck-call reconciler: every 2 minutes and once at startup (phase-05 P5-T4)
        cron(reconcile_calls, minute=set(range(0, 60, 2)), second={15}, run_at_startup=True),
        # Phase 7: unfinished finalizations and the Sheets outbox, every 10 minutes
        cron(reconcile_finalize, minute=set(range(1, 60, 10)), second={30}, run_at_startup=True),
        cron(reconcile_sync, minute=set(range(3, 60, 10)), second={45}, run_at_startup=True),
        # Phase 9: due retries and callbacks, missed retry decisions, lost call jobs
        cron(dispatch_retries, minute=set(range(0, 60, 5)), second={50}, run_at_startup=True),
    ]
    on_startup = on_startup
    on_shutdown = on_shutdown
    queue_name = "rcai:queue"
