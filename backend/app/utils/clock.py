"""An injectable clock (phase-09 P9-T9). Everything that schedules or dispatches retries asks a
`Clock` for the time, so tests can freeze it and move it forward. Times are UTC-aware."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class FrozenClock:
    """A clock that only moves when told to (tests)."""

    current: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.current.tzinfo is None:
            raise ValueError("FrozenClock needs a timezone-aware datetime")

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> datetime:
        self.current += delta
        return self.current

    def set(self, when: datetime) -> None:
        self.current = when


SYSTEM_CLOCK = SystemClock()
