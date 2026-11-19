"""The calling window (phase-09 §5): the days and hours in APP_TIMEZONE when candidates may be
called. Times are stored in UTC; the window is evaluated in the local timezone.

`contains` answers "may we dial now?" (end hour exclusive). Scheduling is stricter: a retry or a
callback is never scheduled later than `end - LAST_SLOT_MARGIN`, so the dispatcher (every 5
minutes) and a wait for a free line still fall inside the window.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from app.config import Settings

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
LAST_SLOT_MARGIN = timedelta(minutes=30)
SEARCH_DAYS = 15  # more than a week: any allowed day is found

Half = Literal["morning", "afternoon"]


@dataclass(frozen=True)
class CallingWindow:
    days: frozenset[int]  # weekday numbers, Monday = 0
    start_hour: int
    end_hour: int  # exclusive; 24 = midnight
    tz: ZoneInfo

    @classmethod
    def from_settings(cls, settings: Settings) -> "CallingWindow":
        names = {d.strip().lower()[:3] for d in settings.calling_days.split(",") if d.strip()}
        return cls(
            days=frozenset(i for i, n in enumerate(DAY_NAMES) if n in names),
            start_hour=settings.calling_hour_start,
            end_hour=settings.calling_hour_end,
            tz=ZoneInfo(settings.app_timezone),
        )

    # --- times of day ---------------------------------------------------------------------

    @property
    def start(self) -> time:
        return time(self.start_hour)

    @property
    def latest(self) -> time:
        """The latest time a call may be scheduled for."""
        end = datetime.combine(date.min, time(0)) + timedelta(hours=self.end_hour)
        latest = max(end - LAST_SLOT_MARGIN, datetime.combine(date.min, self.start))
        return latest.time()

    @property
    def midpoint(self) -> time:
        """Where the afternoon half starts (10:00-19:00 → 14:30)."""
        minutes = (self.start_hour + self.end_hour) * 30
        return time(minutes // 60 % 24, minutes % 60)

    def local(self, when: datetime) -> datetime:
        return when.astimezone(self.tz)

    def half(self, when: datetime) -> Half:
        return "morning" if self.local(when).time() < self.midpoint else "afternoon"

    # --- questions ------------------------------------------------------------------------

    def contains(self, when: datetime) -> bool:
        local = self.local(when)
        return local.weekday() in self.days and self.start_hour <= local.hour < self.end_hour

    def slot_from(self, day: date, at: time) -> datetime:
        """The first schedulable time on `day` at or after `at`, else on a later allowed day.
        Moving to a later day because `day` isn't a calling day keeps the time of day; moving
        because `at` is too late in the day starts at the window's opening."""
        if not self.days:
            raise ValueError("calling window has no days")
        wanted = at
        for offset in range(SEARCH_DAYS):
            d = day + timedelta(days=offset)
            if d.weekday() not in self.days:
                continue
            clamped = max(wanted, self.start)
            if clamped <= self.latest:
                return datetime.combine(d, clamped, tzinfo=self.tz).astimezone(UTC)
            wanted = self.start
        raise ValueError("no calling slot found")  # unreachable with at least one day

    def next_open(self, when: datetime) -> datetime:
        """`when` if calls may be placed then, else the next time the window opens."""
        if self.contains(when):
            return when
        local = self.local(when)
        if local.weekday() in self.days and local.time() < self.start:
            return datetime.combine(local.date(), self.start, tzinfo=self.tz).astimezone(UTC)
        return self.slot_from(local.date() + timedelta(days=1), self.start)

    def schedulable(self, when: datetime) -> datetime:
        """`when` if it's a time we'd schedule a call for, else the nearest later slot."""
        local = self.local(when)
        if local.weekday() in self.days and self.start <= local.time() <= self.latest:
            return when
        return self.slot_from(local.date(), local.time())

    def describe(self) -> str:
        names = [DAY_NAMES[i].capitalize() for i in sorted(self.days)]
        return f"{', '.join(names)} {self.start_hour:02d}:00-{self.end_hour:02d}:00 {self.tz.key}"
