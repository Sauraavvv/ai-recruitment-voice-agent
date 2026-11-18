"""Normalization (phase plan 5.8) and the evidence check (P2-T5)."""

import pytest

from app.agent.extraction import (
    consistency_flags,
    extract,
    normalize_ctc,
    normalize_experience,
    notice_days,
    quote_matches,
)
from app.agent.state import ScreeningState
from app.tests.unit.agent.stub_llm import JOB, turn


def state() -> ScreeningState:
    return ScreeningState.new(
        candidate_name="Rahul", job_title="Dev", questions=list(JOB.questions)
    )


@pytest.mark.parametrize(
    ("quote", "utterance", "ok"),
    [
        ("working at Infosys", "I'm in Gurgaon, working at Infosys right now.", True),
        ("Working at infosys!", "I'm in Gurgaon, working at Infosys right now.", True),
        ("5 years", "I have five years of experience", True),
        ("12,00,000", "it is 1200000 per year", True),
        ("I work at Wipro", "I'm in Gurgaon, working at Infosys right now.", False),
        ("Delhi", "I'm in Gurgaon", False),
        ("", "anything", False),
    ],
)
def test_quote_matches(quote: str, utterance: str, ok: bool) -> None:
    assert quote_matches(quote, utterance) is ok


@pytest.mark.parametrize(
    ("value", "expected"),
    [(5.5, 5.5), (0, 0.0), (50, 50.0), (51, None), (-1, None), (None, None), (3.333, 3.3)],
)
def test_normalize_experience(value: float | None, expected: float | None) -> None:
    assert normalize_experience(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (12, 12.0),
        (120, 120.0),  # 1.2 crore
        (9.6, 9.6),  # 80k per month
        (1_200_000, 12.0),  # rupees slipped through
        (0.2, None),
        (600, None),
        (None, None),
    ],
)
def test_normalize_ctc(value: float | None, expected: float | None) -> None:
    assert normalize_ctc(value) == expected


@pytest.mark.parametrize(
    ("text", "llm_days", "expected"),
    [
        ("30 days", None, 30),
        ("two months", None, 60),
        ("3 weeks", None, 21),
        ("immediate joiner", None, 0),
        ("serving notice, last day 15 Dec", None, None),
        ("90 days", 90, 90),
        ("whatever", 999, None),
    ],
)
def test_notice_days(text: str, llm_days: int | None, expected: int | None) -> None:
    assert notice_days(text, llm_days) == expected


def test_multiple_fields_with_evidence() -> None:
    s = state()
    out = extract(
        turn(
            fields={"current_location": "Gurgaon", "current_company": "Infosys"},
            evidence={"current_location": "Gurgaon", "current_company": "working at Infosys"},
        ),
        "Gurgaon, working at Infosys",
        s,
    )
    assert {u.key: u.value for u in out.updates} == {
        "current_location": "Gurgaon",
        "current_company": "Infosys",
    }


def test_value_without_matching_quote_is_dropped() -> None:
    out = extract(
        turn(fields={"current_ctc_lpa": 12}, evidence={"current_ctc_lpa": "12 lakhs"}),
        "I'd rather not say my salary",
        state(),
    )
    assert out.updates == []
    assert "current_ctc" in out.dropped


def test_value_with_no_quote_at_all_is_dropped() -> None:
    out = extract(turn(fields={"current_company": "TCS"}), "I work in IT", state())
    assert out.updates == [] and "current_company" in out.dropped


def test_out_of_range_is_invalid() -> None:
    out = extract(
        turn(fields={"total_experience_years": 70}, evidence={"total_experience": "70 years"}),
        "70 years",
        state(),
    )
    assert out.updates == [] and "total_experience" in out.invalid


def test_notice_days_go_into_meta() -> None:
    out = extract(
        turn(
            fields={"notice_period": "two months", "notice_period_days": None},
            evidence={"notice_period": "two months"},
        ),
        "It's two months",
        state(),
    )
    assert out.updates[0].meta == {"days": 60}


def test_ranges_declined_unknown_and_aliases() -> None:
    t = turn(
        ranges=[{"field": "expected_ctc_lpa", "low": 15, "high": 18, "quote": "15 to 18 lakhs"}],
        declined_fields=["current_ctc_lpa", "not_a_field"],
        unknown_fields=["relevant_experience"],
    )
    out = extract(t, "Expecting 15 to 18 lakhs, current I won't share", state())
    assert [(r.key, r.low, r.high) for r in out.ranges] == [("expected_ctc", 15.0, 18.0)]
    assert out.declined == ["current_ctc"]
    assert out.unknown == ["relevant_experience"]


def test_consistency_flags() -> None:
    s = state()
    s.merge("total_experience", 3.0, raw_text="3", turn=1)
    s.merge("relevant_experience", 5.0, raw_text="5", turn=1)
    s.merge("current_ctc", 5.0, raw_text="5", turn=1)
    s.merge("expected_ctc", 20.0, raw_text="20", turn=1)
    assert consistency_flags(s) == ["relevant_experience", "expected_ctc"]
