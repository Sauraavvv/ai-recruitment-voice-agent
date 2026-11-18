"""ARQ worker configuration.

Run with: arq app.workers.settings.WorkerSettings
Job functions are added in later phases (calls, sync, retries).
"""

from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from app.config import AppEnv, get_settings
from app.utils.log import configure_logging, get_logger
from app.utils.redis import WORKER_HEARTBEAT_KEY, WORKER_HEARTBEAT_TTL_SECONDS

logger = get_logger(__name__)
_settings = get_settings()


async def heartbeat(ctx: dict[str, Any]) -> None:
    """Lets /health/ready confirm a worker is alive."""
    await ctx["redis"].set(WORKER_HEARTBEAT_KEY, "1", ex=WORKER_HEARTBEAT_TTL_SECONDS)


async def on_startup(ctx: dict[str, Any]) -> None:
    configure_logging(_settings.log_level, json_output=_settings.app_env is AppEnv.PRODUCTION)
    await heartbeat(ctx)
    logger.info("worker_startup", env=_settings.app_env.value)


async def on_shutdown(_ctx: dict[str, Any]) -> None:
    logger.info("worker_shutdown")


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(_settings.redis_url.get_secret_value())
    functions: ClassVar[list[Any]] = []
    cron_jobs: ClassVar[list[Any]] = [cron(heartbeat, second={0, 30}, run_at_startup=False)]
    on_startup = on_startup
    on_shutdown = on_shutdown
    queue_name = "rcai:queue"
