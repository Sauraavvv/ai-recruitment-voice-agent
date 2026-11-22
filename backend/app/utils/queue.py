"""ARQ job queue client for the API process (the worker has its own)."""

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

QUEUE_NAME = "rcai:queue"

_pool: ArqRedis | None = None


async def init_queue(redis_url: str) -> ArqRedis:
    global _pool
    _pool = await create_pool(RedisSettings.from_dsn(redis_url), default_queue_name=QUEUE_NAME)
    return _pool


async def close_queue() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
    _pool = None


def get_queue() -> ArqRedis:
    if _pool is None:
        raise RuntimeError("Job queue not initialized")
    return _pool


async def enqueue_initiate_call(attempt_id: str, *, ignore_window: bool = False) -> None:
    """One job per attempt: the job id de-duplicates double clicks and re-sends.

    `ignore_window` is for the PoC test-call script only (calls to the testers' own phones).
    """
    await get_queue().enqueue_job(
        "initiate_call", attempt_id, ignore_window, _job_id=f"call:{attempt_id}"
    )


async def enqueue_finalize_call(attempt_id: str) -> None:
    """Post-call work for one attempt (summary now, Phase 7 extraction and Sheets)."""
    await get_queue().enqueue_job("finalize_call", attempt_id, _job_id=f"finalize:{attempt_id}")


async def enqueue_evaluate_round(attempt_id: str, token: str | None) -> None:
    """The AI evaluation of a telephonic round call (phase-11 step 6c). The token is the time
    of the "Re-evaluate" it answers; the job id stops a double click."""
    from app.services.telephonic_evaluation import enqueue

    await enqueue(get_queue(), attempt_id, token)
