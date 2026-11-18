"""Concurrency slots for live calls: a Redis semaphore of size MAX_CONCURRENT_CALLS.

Each slot is a key `rcai:call:slot:{n}` holding the attempt id, with a TTL of the maximum call
length + 5 min as a safety net. Released on a terminal status, when the stream ends, or by TTL.
Acquiring and releasing are idempotent per attempt.
"""

from redis.asyncio import Redis

from app.utils.redis import KEY_PREFIX

SLOT_KEY = KEY_PREFIX + "call:slot:{n}"
SAFETY_MARGIN_S = 300

# Delete the key only if this attempt still holds it.
_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then return redis.call('DEL', KEYS[1]) end
return 0
"""


def _keys(size: int) -> list[str]:
    return [SLOT_KEY.format(n=n) for n in range(size)]


async def holder_slot(redis: Redis, attempt_id: str, size: int) -> str | None:
    for key in _keys(size):
        if await redis.get(key) == attempt_id:
            return key
    return None


async def acquire(redis: Redis, attempt_id: str, *, size: int, ttl_s: int) -> bool:
    if await holder_slot(redis, attempt_id, size):
        return True
    for key in _keys(size):
        if await redis.set(key, attempt_id, nx=True, ex=ttl_s + SAFETY_MARGIN_S):
            return True
    return False


async def release(redis: Redis, attempt_id: str, *, size: int) -> bool:
    released = False
    # Scan a few extra slots in case MAX_CONCURRENT_CALLS was lowered while calls were live.
    for key in _keys(max(size, 4)):
        released = bool(await redis.eval(_RELEASE, 1, key, attempt_id)) or released  # type: ignore[misc]
    return released


async def in_use(redis: Redis, *, size: int) -> list[str]:
    values = [await redis.get(key) for key in _keys(size)]
    return [v for v in values if v]
