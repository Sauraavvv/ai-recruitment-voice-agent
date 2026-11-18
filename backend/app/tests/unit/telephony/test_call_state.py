import uuid
from datetime import UTC, datetime

import pytest

from app.database.models import CallAttempt, CallStatus
from app.services import call_state

S = CallStatus


def _attempt(status: CallStatus) -> CallAttempt:
    return CallAttempt(
        id=uuid.uuid4(),
        candidate_id=uuid.uuid4(),
        attempt_number=1,
        provider="exotel",
        call_status=status.value,
    )


@pytest.mark.parametrize(
    ("cur", "new"),
    [
        (S.PENDING, S.QUEUED),
        (S.QUEUED, S.INITIATING),
        (S.INITIATING, S.RINGING),
        (S.INITIATING, S.IN_PROGRESS),  # missed ringing
        (S.INITIATING, S.COMPLETED),  # missed answered
        (S.RINGING, S.IN_PROGRESS),
        (S.IN_PROGRESS, S.COMPLETED),
        (S.QUEUED, S.CANCELLED),
        (S.INITIATING, S.FAILED),
        (S.RINGING, S.NO_ANSWER),
        (S.RINGING, S.BUSY),
        (S.IN_PROGRESS, S.FAILED),
    ],
)
def test_allowed(cur: CallStatus, new: CallStatus) -> None:
    assert call_state.can_transition(cur, new)


@pytest.mark.parametrize(
    ("cur", "new"),
    [
        (S.COMPLETED, S.RINGING),  # out of order after terminal
        (S.COMPLETED, S.FAILED),
        (S.FAILED, S.COMPLETED),
        (S.BUSY, S.IN_PROGRESS),
        (S.IN_PROGRESS, S.RINGING),  # backwards
        (S.IN_PROGRESS, S.NO_ANSWER),  # answered can't be "no answer"
        (S.IN_PROGRESS, S.BUSY),
        (S.QUEUED, S.COMPLETED),  # never placed
        (S.RINGING, S.RINGING),
    ],
)
def test_refused(cur: CallStatus, new: CallStatus) -> None:
    assert not call_state.can_transition(cur, new)


def test_transition_sets_times_and_fields() -> None:
    attempt = _attempt(S.RINGING)
    t1 = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
    assert call_state.transition(attempt, S.IN_PROGRESS, now=t1)
    assert attempt.start_time == t1
    t2 = datetime(2026, 11, 18, 10, 5, tzinfo=UTC)
    assert call_state.transition(attempt, S.COMPLETED, now=t2, end_reason="candidate_hangup")
    assert (attempt.end_time, attempt.end_reason) == (t2, "candidate_hangup")
    # terminal is final, and a refused transition changes nothing
    assert not call_state.transition(attempt, S.FAILED, end_reason="technical_failure")
    assert attempt.call_status == S.COMPLETED and attempt.end_reason == "candidate_hangup"


def test_update_details_never_erases() -> None:
    attempt = _attempt(S.COMPLETED)
    call_state.update_details(attempt, duration_seconds=42, recording_url="https://r")
    call_state.update_details(attempt, duration_seconds=None, recording_url=None)
    assert (attempt.duration_seconds, attempt.recording_url) == (42, "https://r")
