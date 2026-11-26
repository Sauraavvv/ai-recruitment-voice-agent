"""FastAPI application factory.

Run with: uvicorn app.main:create_app --factory
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.middleware import RequestContextMiddleware
from app.api.responses import register_error_handlers
from app.api.v1 import api_router
from app.api.v1.webhooks import callback_router
from app.api.v1.webhooks import router as webhooks_router
from app.config import AppEnv, Settings, get_settings
from app.database.connection import dispose_engine, init_engine
from app.providers.tts import create_tts_provider
from app.providers.tts.base import TTSConfigError, TTSError, TTSProvider
from app.utils.log import configure_logging, get_logger
from app.utils.queue import close_queue, init_queue
from app.utils.redis import close_redis, init_redis

if TYPE_CHECKING:
    from arq.worker import Worker

logger = get_logger(__name__)


async def _load_tts(tts: TTSProvider) -> None:
    """Load the voice in the background: the API is usable meanwhile, and a failure is reported
    by tts.status() (calls are refused without a voice, Phase 5) instead of crashing the app."""
    with contextlib.suppress(TTSError):
        await tts.initialize()


async def _start_worker(settings: Settings) -> "tuple[Worker, asyncio.Task[None]]":
    """RUN_WORKER_IN_API: the background worker (jobs and crons) as a task of this process,
    sharing its database engine and Redis (for hosts with a single free service)."""
    from arq.connections import RedisSettings
    from arq.worker import Worker

    from app.utils.queue import QUEUE_NAME
    from app.workers.jobs import CRON_JOBS, FUNCTIONS, heartbeat

    async def on_startup(ctx: dict[str, Any]) -> None:
        ctx["settings"] = settings  # the API already set up logging, the database and Redis
        await heartbeat(ctx)
        logger.info("worker_startup", in_api=True, telephony=settings.exotel_configured)

    async def on_shutdown(ctx: dict[str, Any]) -> None:
        telephony = ctx.get("telephony")  # only what the worker opened; the API closes the rest
        if telephony is not None:
            await telephony.close()
        logger.info("worker_shutdown", in_api=True)

    worker = Worker(
        functions=FUNCTIONS,
        cron_jobs=CRON_JOBS,
        redis_settings=RedisSettings.from_dsn(settings.redis_url.get_secret_value()),
        queue_name=QUEUE_NAME,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        handle_signals=False,  # uvicorn handles the signals
    )
    task = asyncio.create_task(worker.async_run(), name="worker")
    logger.info("worker_in_api_started")
    return worker, task


async def _stop_worker(worker: "Worker", task: "asyncio.Task[None]") -> None:
    await worker.close()  # stops taking jobs, lets running ones finish
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.app_env is AppEnv.PRODUCTION)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        init_engine(settings.database_url.get_secret_value())
        init_redis(settings.redis_url.get_secret_value())
        await init_queue(settings.redis_url.get_secret_value())
        tts: TTSProvider | None = None
        tts_task: asyncio.Task[None] | None = None
        if settings.tts_preload:
            try:
                tts = create_tts_provider(settings)
            except TTSConfigError as exc:
                # No voice key: the app runs, and calls are refused ("voice not ready")
                logger.warning("tts_not_configured", reason=str(exc))
            else:
                tts_task = asyncio.create_task(_load_tts(tts), name="tts-load")
        _app.state.tts = tts
        worker = await _start_worker(settings) if settings.run_worker_in_api else None
        logger.info(
            "startup",
            env=settings.app_env.value,
            version=settings.app_version,
            providers_configured=settings.provider_configuration(),
        )
        try:
            yield
        finally:
            if worker is not None:
                await _stop_worker(*worker)
            if tts_task is not None:
                tts_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await tts_task
            if tts is not None:
                await tts.close()
            await close_queue()
            await close_redis()
            await dispose_engine()
            logger.info("shutdown")

    app = FastAPI(
        title="CallZest API",
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=None if settings.app_env is AppEnv.PRODUCTION else "/docs",
        redoc_url=None,
    )
    # Endpoints use the settings this app was built with, not a fresh read of the environment.
    app.dependency_overrides[get_settings] = lambda: settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)

    app.include_router(health_router)
    app.include_router(api_router)
    # Provider-facing: token in the URL instead of a session, no CSRF origin check
    app.include_router(webhooks_router)
    app.include_router(callback_router)
    return app
