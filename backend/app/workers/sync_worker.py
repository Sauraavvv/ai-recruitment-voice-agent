"""Google Sheets jobs (phase-07 P7-T9, P7-T10).

sync_sheets      drain the outbox (any number of these can be queued; one runs at a time under
                 the Sheets lock, the others find nothing due and stop)
reconcile_sync   cron every 10 minutes: pending rows older than 5 minutes or failed rows whose
                 retry time has passed → queue a drain
"""

from datetime import UTC, datetime
from typing import Any

from app.config import Settings, get_settings
from app.database.connection import get_sessionmaker
from app.services import settings_service, sync_service
from app.services.sheets_service import SheetsService
from app.utils.log import get_logger
from app.utils.redis import get_redis

logger = get_logger(__name__)


def _sheets(ctx: dict[str, Any], settings: Settings) -> SheetsService:
    service: SheetsService | None = ctx.get("sheets")
    if service is None:
        service = SheetsService(settings)
        ctx["sheets"] = service
    return service.configure(settings)


async def sync_sheets(ctx: dict[str, Any]) -> str:
    # The sheet may be set on the Settings page (app_settings) instead of .env
    settings = await settings_service.effective_new_session(ctx.get("settings") or get_settings())
    result = await sync_service.drain(
        get_sessionmaker(), _sheets(ctx, settings), get_redis(), settings
    )
    if result.outcome == "more":  # a big backlog: continue in a fresh job
        await sync_service.request_sync(settings, ctx.get("redis"))
    return f"{result.outcome}:{result.synced}/{result.failed}"


async def reconcile_sync(ctx: dict[str, Any], *, now: datetime | None = None) -> int:
    settings = await settings_service.effective_new_session(ctx.get("settings") or get_settings())
    if not settings.sheets_configured:
        return 0
    async with get_sessionmaker()() as session:
        stale = await sync_service.stale_count(session, now or datetime.now(UTC))
    if stale:
        logger.info("sheets_sync_requeued", rows=stale)
        await sync_service.request_sync(settings, ctx.get("redis"))
    return stale
