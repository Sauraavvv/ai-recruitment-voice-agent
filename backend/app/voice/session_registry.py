"""Live call sessions in this process, by call_attempt_id (phase-06 P6-T12).

One session per attempt; registering a second one for the same attempt is refused. The registry
holds references only: each session owns its queues, buffers, timers and provider streams and
releases them in its own cleanup.
"""

import asyncio
from typing import Any

from app.utils.log import get_logger

logger = get_logger(__name__)


class SessionExistsError(RuntimeError):
    pass


class SessionRegistry[T]:
    def __init__(self) -> None:
        self._sessions: dict[str, T] = {}
        self.peak = 0
        self.total = 0

    def register(self, attempt_id: str, session: T) -> None:
        if attempt_id in self._sessions:
            raise SessionExistsError(attempt_id)
        self._sessions[attempt_id] = session
        self.total += 1
        self.peak = max(self.peak, len(self._sessions))
        logger.info("session_registered", call_attempt_id=attempt_id, active=len(self._sessions))

    def unregister(self, attempt_id: str, session: T | None = None) -> None:
        current = self._sessions.get(attempt_id)
        if current is None or (session is not None and current is not session):
            return
        del self._sessions[attempt_id]
        logger.info("session_unregistered", call_attempt_id=attempt_id, active=len(self._sessions))

    def get(self, attempt_id: str) -> T | None:
        return self._sessions.get(attempt_id)

    def __contains__(self, attempt_id: object) -> bool:
        return attempt_id in self._sessions

    def __len__(self) -> int:
        return len(self._sessions)

    def ids(self) -> list[str]:
        return list(self._sessions)


REGISTRY: SessionRegistry[Any] = SessionRegistry()


def live_task_count() -> int:
    """Tasks alive in the event loop (leak checks before and after a session)."""
    return len(asyncio.all_tasks())
