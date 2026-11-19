"""Retry dispatcher cron (phase-09 P9-T2), every 5 minutes:

1. evaluate ended attempts nobody evaluated (lost webhook, worker down, no finalization)
2. dispatch due retries and callbacks (re-check → queued → `initiate_call`)
3. enqueue again queued attempts whose job may have been lost (same job id: no duplicate)
"""

from typing import Any

from app.config import Settings, get_settings
from app.database.connection import get_sessionmaker
from app.services import retry_service, settings_service, sync_service
from app.utils.clock import SYSTEM_CLOCK, Clock
from app.utils.log import get_logger

logger = get_logger(__name__)


def _enqueue(ctx: dict[str, Any]) -> retry_service.Enqueue:
    pool = ctx["redis"]

    async def enqueue(attempt_id: str) -> None:
        await pool.enqueue_job("initiate_call", attempt_id, False, _job_id=f"call:{attempt_id}")

    return enqueue


async def dispatch_retries(ctx: dict[str, Any]) -> dict[str, int]:
    base: Settings = ctx.get("settings") or get_settings()
    clock: Clock = ctx.get("clock") or SYSTEM_CLOCK
    settings = await settings_service.effective_new_session(base)
    enqueue = _enqueue(ctx)
    async with get_sessionmaker()() as session:
        evaluated = await retry_service.evaluate_pending(session, settings, clock=clock)
        result = await retry_service.dispatch_due(session, settings, enqueue, clock=clock)
        requeued = await retry_service.requeue_stale(session, enqueue, clock=clock)
    if evaluated or result.changed:
        await sync_service.request_sync(settings, ctx.get("redis"))
    return {
        "evaluated": evaluated,
        "queued": len(result.queued),
        "moved": result.moved,
        "held": result.held,
        "cancelled": result.cancelled,
        "requeued": requeued,
    }
