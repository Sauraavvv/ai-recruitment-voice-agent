"""RUN_WORKER_IN_API: the background worker runs inside the API process (Render free tier)."""

import asyncio

from app.main import create_app
from app.tests.conftest import make_settings
from app.utils.redis import WORKER_HEARTBEAT_KEY, get_redis


async def test_the_api_runs_the_worker_and_stops_it_cleanly(
    migrated_database: str,
) -> None:
    app = create_app(make_settings(database_url=migrated_database, run_worker_in_api=True))
    async with app.router.lifespan_context(app):
        redis = get_redis()
        await redis.delete(WORKER_HEARTBEAT_KEY)
        # the worker's startup beats once; wait for it (it starts as a task of this process)
        for _ in range(50):
            if await redis.get(WORKER_HEARTBEAT_KEY):
                break
            await asyncio.sleep(0.1)
        assert await redis.get(WORKER_HEARTBEAT_KEY)
        workers = [t for t in asyncio.all_tasks() if t.get_name() == "worker"]
        assert len(workers) == 1 and not workers[0].done()
    # shut down with the API: no worker task left behind
    assert not [t for t in asyncio.all_tasks() if t.get_name() == "worker" and not t.done()]


async def test_off_by_default(migrated_database: str) -> None:
    app = create_app(make_settings(database_url=migrated_database))
    async with app.router.lifespan_context(app):
        assert not [t for t in asyncio.all_tasks() if t.get_name() == "worker"]
