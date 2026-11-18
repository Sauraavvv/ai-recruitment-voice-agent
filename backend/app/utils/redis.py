"""Shared async Redis client. All keys use the `rcai:` prefix."""

import asyncio

from redis.asyncio import Redis

KEY_PREFIX = "rcai:"
WORKER_HEARTBEAT_KEY = f"{KEY_PREFIX}worker:heartbeat"
WORKER_HEARTBEAT_TTL_SECONDS = 90

_client: Redis | None = None


def init_redis(redis_url: str) -> Redis:
    global _client
    _client = Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=5)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


def get_redis() -> Redis:
    if _client is None:
        raise RuntimeError("Redis client not initialized")
    return _client


async def check_redis(timeout: float = 2.0) -> None:
    await asyncio.wait_for(get_redis().ping(), timeout=timeout)


async def check_worker_heartbeat(timeout: float = 2.0) -> None:
    """Raise if the worker hasn't written its heartbeat within the TTL."""
    if not await asyncio.wait_for(get_redis().exists(WORKER_HEARTBEAT_KEY), timeout=timeout):
        raise RuntimeError("no worker heartbeat")
