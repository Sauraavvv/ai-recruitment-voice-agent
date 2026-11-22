"""AI evaluation of telephonic round answers (phase-11 step 6c).

evaluate_round           job: queued after a round call is finalized, or by "Re-evaluate".
                         One try (`services.telephonic_evaluation` stores a failure; the
                         reconciler retries it).
reconcile_evaluations    cron every 10 minutes: finalized round calls (last 14 days) never
                         evaluated, or whose run failed (up to 3 times) or was lost.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from app.config import Settings, get_settings
from app.database.connection import get_sessionmaker
from app.providers.llm import create_question_llm
from app.services import telephonic_evaluation
from app.utils.log import get_logger

logger = get_logger(__name__)


async def evaluate_round(ctx: dict[str, Any], attempt_id: str, token: str | None = None) -> str:
    settings: Settings = ctx.get("settings") or get_settings()
    llm = create_question_llm(settings) if settings.groq_keys else None
    try:
        outcome = await telephonic_evaluation.run(
            uuid.UUID(attempt_id), token=token, llm=llm, settings=settings
        )
    finally:
        if llm is not None:
            await llm.aclose()
    logger.info("evaluate_round_done", call_attempt_id=attempt_id, outcome=outcome)
    return outcome


async def reconcile_evaluations(ctx: dict[str, Any], *, now: datetime | None = None) -> int:
    settings: Settings = ctx.get("settings") or get_settings()
    if not settings.groq_keys:
        return 0
    async with get_sessionmaker()() as session:
        due = await telephonic_evaluation.due(session, now or datetime.now(UTC))
    pool = ctx.get("redis")
    for attempt_id, token in due:
        await telephonic_evaluation.enqueue(pool, attempt_id, token)
    if due:
        logger.info("round_evaluations_requeued", count=len(due))
    return len(due)
