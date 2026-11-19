"""Phase 9 rules without a database: the calling window, retry and callback times on a frozen
clock (2/3/4 days, window edges, the UTC/IST date boundary), the outcome table, the decision,
the scheduling moves of the state machine and the resume openers (P9-AC2, P9-AC3, P9-AC5)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.agent.prompts import CandidateContext, JobConfig, introduction
from app.config import AppEnv, ConfigError
from app.database.models import CallAttempt, Candidate
from app.services import call_state
from app.services.retry_service import (
    Counts,
    Outcome,
    RetryRules,
    call_kind,
    callback_time,
    classify,
    decide,
    known_answers,
    retry_time,
)
from app.tests.conftest import make_settings
from app.utils.calling_window import CallingWindow
from app.utils.clock import FrozenClock

IST = ZoneInfo("Asia/Kolkata")
# 2026-11-19 is a Thursday; 21 = Saturday, 22 = Sunday (not a calling day), 23 = Monday
SETTINGS = make_settings()  # Mon-Sat 10:00-19:00 Asia/Kolkata, 3 attempts, 2 days
WINDOW = CallingWindow.from_settings(SETTINGS)


def ist(day: int, hour: int, minute: int = 0, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=IST)


def rules(**overrides: Any) -> RetryRules:
    return RetryRules.from_settings(SETTINGS.model_copy(update=overrides))


# --- Calling window -------------------------------------------------------------------------


def test_window_basics() -> None:
    assert WINDOW.describe() == "Mon, Tue, Wed, Thu, Fri, Sat 10:00-19:00 Asia/Kolkata"
    assert (WINDOW.midpoint.hour, WINDOW.midpoint.minute) == (14, 30)
    assert (WINDOW.latest.hour, WINDOW.latest.minute) == (18, 30)
    assert WINDOW.contains(ist(19, 10))
    assert WINDOW.contains(ist(19, 18, 59))
    assert not WINDOW.contains(ist(19, 19))  # end hour is exclusive
    assert not WINDOW.contains(ist(19, 9, 59))
    assert not WINDOW.contains(ist(22, 12))  # Sunday


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (ist(19, 12), ist(19, 12)),  # open now
        (ist(19, 8), ist(19, 10)),  # before opening: same day
        (ist(19, 19, 30), ist(20, 10)),  # after closing: next day
        (ist(21, 19, 30), ist(23, 10)),  # Saturday evening → Monday (Sunday excluded)
        (ist(22, 11), ist(23, 10)),  # Sunday → Monday
        # UTC/IST date boundary: Thursday 20:00 UTC is Friday 01:30 IST → Friday 10:00 IST
        (datetime(2026, 11, 19, 20, 0, tzinfo=UTC), ist(20, 10)),
    ],
)
def test_next_open(now: datetime, expected: datetime) -> None:
    assert WINDOW.next_open(now) == expected


def test_slot_from_keeps_time_of_day_across_closed_days() -> None:
    sunday = ist(22, 0).date()
    assert WINDOW.slot_from(sunday, ist(22, 11).time()) == ist(23, 11)
    thursday = ist(19, 0).date()
    assert WINDOW.slot_from(thursday, ist(19, 18, 45).time()) == ist(20, 10)  # too late
    saturday = ist(21, 0).date()
    assert WINDOW.slot_from(saturday, ist(21, 18, 45).time()) == ist(23, 10)


def test_window_with_every_day_and_all_hours() -> None:
    window = CallingWindow.from_settings(
        make_settings(
            calling_days="mon,tue,wed,thu,fri,sat,sun", calling_hour_start=0, calling_hour_end=24
        )
    )
    assert window.contains(ist(22, 3))
    assert (window.latest.hour, window.latest.minute) == (23, 30)
    assert window.next_open(ist(22, 3)) == ist(22, 3)


# --- Retry time (P9-AC2) ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days", "ended", "expected"),
    [
        (2, ist(19, 11), ist(21, 11)),  # Thu → Sat, same time
        (3, ist(19, 11), ist(23, 11)),  # Thu → Sun (closed) → Mon, same time
        (4, ist(19, 11), ist(23, 11)),  # Thu → Mon
        (2, ist(19, 18, 50), ist(23, 10)),  # Sat 18:50 is after the last slot → Mon opening
        (2, ist(20, 18, 20), ist(23, 18, 20)),  # Fri → Sun (closed) → Mon, same time
    ],
)
def test_retry_after_the_configured_days(days: int, ended: datetime, expected: datetime) -> None:
    got = retry_time(ended, rules(retry_interval_days=days, retry_alternate_slots=False), None)
    assert got == expected
    assert WINDOW.local(got).date() >= WINDOW.local(ended).date() + timedelta(days=days)
    assert WINDOW.contains(got)


def test_retry_alternates_morning_and_afternoon() -> None:
    r = rules(retry_alternate_slots=True)
    assert retry_time(ist(19, 11), r, "morning") == ist(21, 14, 30)
    assert retry_time(ist(19, 16), r, "afternoon") == ist(21, 10)


def test_staging_minutes() -> None:
    r = rules(retry_interval_unit="minutes", retry_interval_days=2)
    assert r.interval == timedelta(minutes=2)
    assert retry_time(ist(19, 18, 55), r, "afternoon") == ist(19, 18, 57)
    assert retry_time(ist(19, 18, 59), r, "afternoon") == ist(20, 10)  # window closed


def test_minutes_refused_in_production() -> None:
    with pytest.raises(ConfigError, match="RETRY_INTERVAL_UNIT"):
        make_settings(
            app_env=AppEnv.PRODUCTION,
            app_secret_key="Zq3x" * 12,
            public_backend_url="https://example.org",
            retry_interval_unit="minutes",
        )


def test_frozen_clock() -> None:
    clock = FrozenClock(ist(19, 11))
    assert clock.now() == ist(19, 11)
    clock.advance(timedelta(days=2))
    assert clock.now() == ist(21, 11)
    with pytest.raises(ValueError):
        FrozenClock(datetime(2026, 11, 19))


# --- Callback time (P9-AC5) -------------------------------------------------------------------


def test_callback_inside_the_window_is_kept() -> None:
    at, note = callback_time(ist(20, 17), ist(19, 15), WINDOW)  # "tomorrow at 5 PM"
    assert (at, note) == (ist(20, 17), None)


def test_callback_outside_the_window_is_moved_with_a_note() -> None:
    at, note = callback_time(ist(19, 21), ist(19, 15), WINDOW)
    assert at == ist(20, 10)
    assert note is not None and "Thu 19 Nov 21:00" in note and "Fri 20 Nov 10:00" in note
    at, _ = callback_time(ist(22, 12), ist(19, 15), WINDOW)  # Sunday → Monday, same time
    assert at == ist(23, 12)


def test_callback_in_the_past_or_too_far() -> None:
    at, note = callback_time(ist(19, 11), ist(19, 15), WINDOW)
    assert at == ist(19, 15) and note and "had passed" in note
    assert callback_time(ist(19, 11) + timedelta(days=20), ist(19, 11), WINDOW) == (None, None)


# --- Outcome table (phase-09 §6) --------------------------------------------------------------


def attempt(status: str, **values: Any) -> CallAttempt:
    a = CallAttempt(
        candidate_id=uuid.uuid4(),
        attempt_number=1,
        attempt_type="initial",
        provider="exotel",
        call_status=status,
        retry_count=0,
    )
    for k, v in values.items():
        setattr(a, k, v)
    return a


def result(**values: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "end_reason": "completed",
        "screening_status": "completed",
        "collected_data": {},
        "callback": {"requested": False},
        "opted_out": False,
        "declined_opportunity": False,
    }
    return base | values


@pytest.mark.parametrize(
    ("status", "attrs", "res", "kind"),
    [
        ("no_answer", {}, None, "no_answer"),
        ("busy", {}, None, "busy"),
        ("failed", {"end_reason": "provider_failed"}, None, "temporary_failure"),
        ("failed", {"end_reason": "invalid_number"}, None, "invalid_number"),
        ("cancelled", {}, None, "cancelled"),
        ("completed", {"end_reason": "technical_failure"}, None, "temporary_failure"),
        ("completed", {}, result(), "completed"),
        ("completed", {}, result(end_reason="declined", screening_status="declined"), "declined"),
        ("completed", {}, result(opted_out=True, end_reason="opted_out"), "opted_out"),
        ("completed", {}, result(end_reason="wrong_person"), "wrong_person"),
        (
            "completed",
            {},
            result(
                end_reason="hangup",
                screening_status="partially_completed",
                collected_data={"current_ctc": 12},
            ),
            "partial",
        ),
        (
            "completed",
            {},
            result(end_reason="error", screening_status="not_started"),
            "temporary_failure",
        ),
        (
            "completed",
            {},
            result(end_reason="no_response", screening_status="not_started"),
            "no_response",
        ),
        (
            "completed",
            {"duration_seconds": 8},
            result(end_reason="hangup", screening_status="not_started"),
            "temporary_failure",  # dropped in the first 15 s
        ),
        (
            "completed",
            {"duration_seconds": 40},
            result(end_reason="hangup", screening_status="not_started"),
            "not_started",
        ),
        (
            "completed",
            {},
            result(
                end_reason="callback",
                screening_status="callback_requested",
                callback={"requested": True, "time_iso": "2026-11-20T17:00:00+05:30"},
            ),
            "callback",
        ),
        (
            "completed",
            {},
            result(
                end_reason="callback",
                screening_status="callback_requested",
                callback={"requested": True, "time_text": "later", "needs_recruiter": True},
            ),
            "vague_callback",
        ),
        (
            "completed",
            {},
            result(end_reason="escalated", screening_status="not_started"),
            "escalated",
        ),
    ],
)
def test_classify(status: str, attrs: dict[str, Any], res: Any, kind: str) -> None:
    got = classify(attempt(status, **attrs), res, None)
    assert got.kind == kind
    if kind == "callback":
        assert got.callback_at == ist(20, 17)


def test_final_status_wins_over_the_live_one() -> None:
    res = result(screening_status="partially_completed", end_reason="hangup")
    assert classify(attempt("completed"), res, {"screening_status": "completed"}).kind == (
        "completed"
    )


# --- Decision ---------------------------------------------------------------------------------

NOW = ist(19, 11, 5)


def test_retry_until_the_last_attempt_then_exhausted() -> None:
    r = rules()
    first = decide(
        Outcome("no_answer"), Counts(1, 0), r, ended_at=ist(19, 11), now=NOW, previous="morning"
    )
    assert (first.action, first.code, first.at) == ("retry", "retry_scheduled", ist(21, 14, 30))
    second = decide(Outcome("busy"), Counts(2, 0), r, ended_at=ist(19, 11), now=NOW, previous=None)
    assert second.action == "retry"
    last = decide(
        Outcome("no_answer"), Counts(3, 0), r, ended_at=ist(19, 11), now=NOW, previous=None
    )
    assert (last.action, last.code) == ("exhausted", "exhausted")


def test_no_retry_outcomes() -> None:
    r = rules()
    for kind in (
        "completed",
        "declined",
        "opted_out",
        "wrong_person",
        "partial",
        "cancelled",
        "invalid_number",
        "vague_callback",
        "escalated",
        "not_started",
    ):
        d = decide(Outcome(kind), Counts(1, 0), r, ended_at=NOW, now=NOW, previous=None)
        assert (d.action, d.code) == ("none", f"no_retry:{kind}")


def test_retries_disabled_still_schedule_callbacks() -> None:
    r = rules(retry_enabled=False)
    off = decide(Outcome("no_answer"), Counts(1, 0), r, ended_at=NOW, now=NOW, previous=None)
    assert off.code == "no_retry:retry_disabled"
    cb = decide(
        Outcome("callback", callback_at=ist(20, 17)),
        Counts(1, 0),
        r,
        ended_at=NOW,
        now=NOW,
        previous=None,
    )
    assert (cb.action, cb.at) == ("callback", ist(20, 17))


def test_callbacks_are_capped_and_dont_count_as_attempts() -> None:
    r = rules(max_callbacks=2)
    ok = decide(
        Outcome("callback", callback_at=ist(20, 17)),
        Counts(3, 1),
        r,
        ended_at=NOW,
        now=NOW,
        previous=None,
    )
    assert ok.action == "callback"  # 3 dialed attempts don't block a callback
    capped = decide(
        Outcome("callback", callback_at=ist(20, 17)),
        Counts(1, 2),
        r,
        ended_at=NOW,
        now=NOW,
        previous=None,
    )
    assert capped.code == "no_retry:callback_limit"


def test_retry_is_never_in_the_past() -> None:
    late = ist(25, 12)  # evaluated days after the call (worker was down)
    d = decide(
        Outcome("no_answer"), Counts(1, 0), rules(), ended_at=ist(19, 11), now=late, previous=None
    )
    assert d.at == late


# --- State machine (scheduling moves) ---------------------------------------------------------


def test_scheduling_transitions() -> None:
    assert call_state.can_transition("retry_scheduled", "queued")
    assert call_state.can_transition("callback_requested", "queued")
    assert call_state.can_transition("queued", "retry_scheduled")
    assert call_state.can_transition("retry_scheduled", "cancelled")
    assert not call_state.can_transition("retry_scheduled", "no_answer")
    assert not call_state.can_transition("retry_scheduled", "initiating")
    assert call_state.is_terminal("exhausted")
    a = attempt("no_answer")
    assert call_state.mark_exhausted(a) and a.call_status == "exhausted"
    assert not call_state.can_transition("exhausted", "completed")
    assert not call_state.mark_exhausted(attempt("in_progress"))


# --- Resuming (P9-T6) -------------------------------------------------------------------------


def test_known_answers_only_from_calls() -> None:
    cand = Candidate(
        name="Rahul Verma",
        phone="+919000000001",
        screening_field_meta={
            "current_ctc": {
                "value": 12,
                "status": "confirmed",
                "call_attempt_id": "a1",
                "raw_text": "twelve lakhs",
            },
            "notice_period": {"value": None, "status": "declined", "call_attempt_id": "a1"},
            "expected_ctc": {"value": None, "status": "missing", "call_attempt_id": "a1"},
            "current_company": {"value": "Acme"},  # typed by a recruiter: still asked
        },
    )
    prior = known_answers(cand)
    assert set(prior) == {"current_ctc", "notice_period"}
    assert prior["current_ctc"]["status"] == "confirmed"
    assert call_kind("retry", prior) == "resume"
    assert call_kind("callback", prior) == "callback"
    assert call_kind("retry", {"notice_period": prior["notice_period"]}) == "first"


def test_openers_say_ai_and_ask() -> None:
    job = JobConfig.from_dict({"job_title": "Backend Developer", "company_name": "Acme"})
    callback = introduction(CandidateContext("Rahul Verma", call_kind="callback"), job)
    assert callback == (
        "Hi Rahul, I'm an AI recruitment assistant calling on behalf of Acme. You asked us to "
        "call back about the Backend Developer role. Is now a good time?"
    )
    resume = introduction(CandidateContext("Rahul Verma", call_kind="resume"), job)
    assert "AI" in resume and "few questions left" in resume and resume.endswith("?")
    first = introduction(CandidateContext("Rahul Verma"), job)
    assert "five-minute" in first
