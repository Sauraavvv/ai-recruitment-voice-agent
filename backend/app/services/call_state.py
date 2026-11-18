"""Call attempt state machine (plan.md Module F, phase-05 P5-T4).

    pending → queued → initiating → ringing → in_progress → completed
    any non-terminal → failed | no_answer | busy | cancelled

Terminal states are final. Out-of-order provider events (e.g. `ringing` after `completed`)
are recorded by the caller but change nothing here. The scheduling states of Phase 9
(retry_scheduled, callback_requested, exhausted) are not telephony outcomes and aren't reached
from this module.
"""

from datetime import UTC, datetime
from typing import Any

from app.database.models import CallAttempt, CallStatus

TERMINAL = frozenset(
    {
        CallStatus.COMPLETED,
        CallStatus.FAILED,
        CallStatus.NO_ANSWER,
        CallStatus.BUSY,
        CallStatus.CANCELLED,
    }
)
_FAILURES = frozenset(
    {CallStatus.FAILED, CallStatus.NO_ANSWER, CallStatus.BUSY, CallStatus.CANCELLED}
)

# Forward moves. A missed callback may skip steps (e.g. initiating → in_progress, or
# initiating → completed when the `answered` event never came).
_FORWARD: dict[CallStatus, frozenset[CallStatus]] = {
    CallStatus.PENDING: frozenset({CallStatus.QUEUED}),
    CallStatus.QUEUED: frozenset({CallStatus.INITIATING}),
    CallStatus.INITIATING: frozenset(
        {CallStatus.RINGING, CallStatus.IN_PROGRESS, CallStatus.COMPLETED}
    ),
    CallStatus.RINGING: frozenset({CallStatus.IN_PROGRESS, CallStatus.COMPLETED}),
    CallStatus.IN_PROGRESS: frozenset({CallStatus.COMPLETED}),
}


def is_terminal(status: str) -> bool:
    return status in TERMINAL


def can_transition(current: str, new: str) -> bool:
    cur, nxt = CallStatus(current), CallStatus(new)
    if cur in TERMINAL or cur == nxt:
        return False
    if nxt in _FAILURES:
        # A call that was answered can't become "no answer" or "busy" afterwards.
        return not (
            cur == CallStatus.IN_PROGRESS and nxt in {CallStatus.NO_ANSWER, CallStatus.BUSY}
        )
    return nxt in _FORWARD.get(cur, frozenset())


def transition(
    attempt: CallAttempt, new: str, *, now: datetime | None = None, **fields: Any
) -> bool:
    """Move `attempt` to `new` if allowed and set `fields`. Returns False (no change) otherwise.

    Sets start_time on entering in_progress and end_time on entering a terminal state, unless the
    caller passes them.
    """
    if not can_transition(attempt.call_status, new):
        return False
    now = now or datetime.now(UTC)
    attempt.call_status = new
    if new == CallStatus.IN_PROGRESS and attempt.start_time is None:
        attempt.start_time = fields.pop("start_time", None) or now
    if new in TERMINAL:
        attempt.end_time = fields.pop("end_time", None) or attempt.end_time or now
    for name, value in fields.items():
        if value is not None:
            setattr(attempt, name, value)
    return True


def update_details(attempt: CallAttempt, **fields: Any) -> None:
    """Fill details (duration, recording, provider status) without a state change. Non-None
    values only, so a late or partial event can't erase what an earlier one stored."""
    for name, value in fields.items():
        if value is not None:
            setattr(attempt, name, value)
