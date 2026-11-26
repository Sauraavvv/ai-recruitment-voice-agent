"""ARQ worker configuration (the standalone worker service).

Run with: arq app.workers.settings.WorkerSettings
Jobs and schedules live in workers/jobs.py: initiate_call (Phase 5), finalize_call (Phase 6/7),
evaluate_round (phase-11 step 6c); crons: reconcilers, and the retry dispatcher (Phase 9).
With RUN_WORKER_IN_API the same jobs run inside the API process instead (app/main.py).
"""

from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.config import AppEnv, get_settings
from app.database.connection import dispose_engine, init_engine
from app.utils.log import configure_logging, get_logger
from app.utils.queue import QUEUE_NAME
from app.utils.redis import close_redis, init_redis
from app.workers.jobs import CRON_JOBS, FUNCTIONS, heartbeat

logger = get_logger(__name__)
_settings = get_settings()


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
    functions: ClassVar[list[Any]] = FUNCTIONS
    cron_jobs: ClassVar[list[Any]] = CRON_JOBS
    on_startup = on_startup
    on_shutdown = on_shutdown
    queue_name = QUEUE_NAME
