"""FastAPI application factory.

Run with: uvicorn app.main:create_app --factory
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.middleware import RequestContextMiddleware
from app.api.responses import register_error_handlers
from app.api.v1 import api_router
from app.config import AppEnv, Settings, get_settings
from app.database.connection import dispose_engine, init_engine
from app.providers.tts import create_tts_provider
from app.providers.tts.base import TTSError, TTSProvider
from app.utils.log import configure_logging, get_logger
from app.utils.redis import close_redis, init_redis

logger = get_logger(__name__)


async def _load_tts(tts: TTSProvider) -> None:
    """Load the voice in the background: the API is usable meanwhile, and a failure is reported
    by tts.status() (calls are refused without a voice, Phase 5) instead of crashing the app."""
    with contextlib.suppress(TTSError):
        await tts.initialize()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.app_env is AppEnv.PRODUCTION)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        init_engine(settings.database_url.get_secret_value())
        init_redis(settings.redis_url.get_secret_value())
        tts: TTSProvider | None = None
        tts_task: asyncio.Task[None] | None = None
        if settings.tts_preload:
            tts = create_tts_provider(settings)
            tts_task = asyncio.create_task(_load_tts(tts), name="tts-load")
        _app.state.tts = tts
        logger.info(
            "startup",
            env=settings.app_env.value,
            version=settings.app_version,
            providers_configured=settings.provider_configuration(),
        )
        try:
            yield
        finally:
            if tts_task is not None:
                tts_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await tts_task
            if tts is not None:
                await tts.close()
            await close_redis()
            await dispose_engine()
            logger.info("shutdown")

    app = FastAPI(
        title="AI Recruitment Voice Agent API",
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
    return app
