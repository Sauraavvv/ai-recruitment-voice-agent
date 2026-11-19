"""Final extraction: reconciliation table, evidence check, validation, screening status
(phase-07 P7-T1, P7-T2)."""

from typing import Any

import pytest

from app.agent.final_pass import (
    FinalField,
    FinalScreeningData,
    finalize,
    run_final_pass,
    screening_status,
)
from app.agent.state import EndReason, QuestionSpec
from app.database.models import ScreeningStatus
from app.providers.llm.base import LLMTimeoutError
from app.schemas.job import default_screening_questions
from app.tests.unit.agent.results import final_output, make_result
from app.tests.unit.agent.stub_llm import ScriptedLLM

QUESTIONS = [QuestionSpec.model_validate(q.model_dump()) for q in default_screening_questions()]

TRANSCRIPT = [
    {"seq": 1, "speaker": "assistant", "text": "Where are you based?"},
    {"seq": 2, "speaker": "candidate", "text": "I'm in Delhi"},
    {"seq": 3, "speaker": "assistant", "text": "So you work at Google?"},
    {"seq": 4, "speaker": "candidate", "text": "five years in total"},
    {"seq": 5, "speaker": "assistant", "text": "What is your current CTC?"},
    {"seq": 6, "speaker": "candidate", "text": "twelve lakhs"},
    {"seq": 7, "speaker": "assistant", "text": "Your notice period?"},
    {"seq": 8, "speaker": "candidate", "text": "I'd rather not say"},
    {"seq": 9, "speaker": "assistant", "text": "And your expected CTC?"},
    {
        "seq": 10,
        "speaker": "candidate",
        "text": "Sorry, my experience is six years actually. Expected is eighteen lakhs",
    },
    {"seq": 11, "speaker": "assistant", "text": "Thanks."},
    {"seq": 12, "speaker": "candidate", "text": "Oh and my CTC went up to fourteen lakhs"},
]
LIVE: dict[str, dict[str, Any]] = {
    "current_location": {"value": "Delhi", "status": "confirmed", "raw_text": "I'm in Delhi"},
    "total_experience": {"value": 5.0, "status": "answered", "raw_text": "five years in total"},
    "current_ctc": {"value": 12.0, "status": "confirmed", "raw_text": "twelve lakhs"},
    "notice_period": {"value": None, "status": "declined"},
    "expected_ctc": {"value": None, "status": "missing"},
}


def _final(output: Any, **result: Any) -> Any:
    values = {"fields": LIVE, "transcript": TRANSCRIPT} | result
    return finalize(make_result(**values), QUESTIONS, output)


def test_reconciliation_table() -> None:
    out = _final(
        final_output(
            {
                "current_location": "Delhi",  # same value → keep
                "total_experience_years": 6,  # ANSWERED, later evidence → take final
                "current_ctc_lpa": 14,  # CONFIRMED, different → keep live, conflict
                "notice_period": "30 days",  # DECLINED → stays declined
                "expected_ctc_lpa": 18,  # MISSING + evidence → accept
                "current_company": "Google",  # only in the assistant's words → reject
                "reason_for_change": "growth",  # no evidence at all → reject
            },
            [
                ("current_location", "I'm in Delhi", 2),
                ("total_experience_years", "my experience is six years actually", 10),
                ("current_ctc_lpa", "my CTC went up to fourteen lakhs", 12),
                ("notice_period", "I'd rather not say", 8),
                ("expected_ctc_lpa", "Expected is eighteen lakhs", 10),
                ("current_company", "you work at Google", 3),
            ],
        )
    )
    f = out.fields
    assert (f["current_location"].value, f["current_location"].source) == ("Delhi", "live")
    assert f["current_location"].conflict is None

    assert (f["total_experience"].value, f["total_experience"].source) == (6, "final_pass")
    assert f["total_experience"].previous[-1]["value"] == 5.0  # history kept
    assert f["total_experience"].seq == 10

    assert f["current_ctc"].value == 12.0 and f["current_ctc"].status == "confirmed"
    assert f["current_ctc"].conflict == {
        "final_value": 14.0,
        "quote": "my CTC went up to fourteen lakhs",
        "seq": 12,
        "reason": "confirmed during the call",
    }

    assert f["notice_period"].status == "declined" and f["notice_period"].value is None

    assert (f["expected_ctc"].value, f["expected_ctc"].source) == (18.0, "final_pass")
    assert f["expected_ctc"].status == "answered" and f["expected_ctc"].raw_text

    assert f["current_company"].value is None
    assert set(out.rejected) == {"current_company", "reason_for_change"}
    assert out.conflicts.keys() == {"current_ctc"}
    assert out.final_pass_ran


def test_answered_value_with_earlier_evidence_is_a_conflict() -> None:
    live = LIVE | {
        "total_experience": {"value": 6.0, "status": "answered", "raw_text": "six years"},
    }
    out = _final(
        final_output({"total_experience_years": 5}, [("total_experience", "five years", 4)]),
        fields=live,
    )
    rec = out.fields["total_experience"]
    assert rec.value == 6.0 and rec.source == "live"
    assert rec.conflict and rec.conflict["final_value"] == 5.0


def test_invalid_final_value_is_rejected() -> None:
    out = _final(
        final_output(
            {"expected_ctc_lpa": 9000}, [("expected_ctc_lpa", "Expected is eighteen lakhs", 10)]
        )
    )
    assert out.fields["expected_ctc"].value is None
    assert "invalid value" in out.rejected["expected_ctc"]


def test_custom_answers_need_evidence() -> None:
    questions = [*QUESTIONS, QuestionSpec(key="has_laptop", prompt="Do you have a laptop?")]
    transcript = [*TRANSCRIPT, {"seq": 11, "speaker": "candidate", "text": "yes I have a laptop"}]
    result = make_result(fields=LIVE, transcript=transcript)
    good = finalize(
        result,
        questions,
        final_output(custom=[("has_laptop", "Yes", "I have a laptop", 11)]),
    )
    assert good.fields["has_laptop"].value == "Yes"
    bad = finalize(result, questions, final_output(custom=[("has_laptop", "Yes", "sure", 11)]))
    assert bad.fields["has_laptop"].value is None and "has_laptop" in bad.rejected


def test_without_a_final_pass_the_live_state_is_used() -> None:
    out = _final(None)
    assert not out.final_pass_ran
    assert out.fields["total_experience"].value == 5.0
    assert out.fields["expected_ctc"].status == "missing"
    assert "expected_ctc" in out.missing


def test_interrupted_assistant_line_counts_only_what_was_heard() -> None:
    from app.agent.final_pass import transcript_lines

    lines = transcript_lines(
        [
            {
                "seq": 1,
                "speaker": "assistant",
                "text": "Hi, I'm calling",
                "interrupted": True,
                "heard_text": "Hi",
            }
        ]
    )
    assert lines[0].text == "Hi"


# --- Validation ---------------------------------------------------------------------------------


def test_bad_field_becomes_null_with_a_note_and_the_rest_saves() -> None:
    data = FinalScreeningData.model_validate(
        {
            "total_experience": 80,
            "current_ctc": 12.5,
            "current_location": "currently at",
            "interested": "maybe",
            "notice_period": "30 days",
        }
    )
    assert (
        data.total_experience is None
        and "experience out of range" in data.notes["total_experience"]
    )
    assert data.current_location is None and "current_location" in data.notes
    assert data.interested is None and "interested" in data.notes
    assert data.current_ctc == 12.5 and data.notice_period == "30 days"


def test_validation_note_is_reflected_in_the_fields() -> None:
    live = LIVE | {"total_experience": {"value": 75.0, "status": "confirmed", "raw_text": "x"}}
    out = _final(None, fields=live)
    rec = out.fields["total_experience"]
    assert rec.value is None and rec.status == "missing" and rec.note
    assert out.data.notes.keys() == {"total_experience"}


# --- Screening status --------------------------------------------------------------------------


def _all_answered() -> dict[str, FinalField]:
    return {q.key: FinalField(value="x", status="answered", source="live") for q in QUESTIONS}


@pytest.mark.parametrize(
    ("overrides", "fields", "expected"),
    [
        ({"opted_out": True}, "all", ScreeningStatus.OPTED_OUT),
        ({"end_reason": EndReason.DECLINED}, "some", ScreeningStatus.DECLINED),
        ({"declined_opportunity": True}, "some", ScreeningStatus.DECLINED),
        ({"end_reason": EndReason.WRONG_PERSON}, "none", ScreeningStatus.WRONG_PERSON),
        ({"end_reason": EndReason.CALLBACK}, "some", ScreeningStatus.CALLBACK_REQUESTED),
        (
            {"end_reason": EndReason.HANGUP, "callback": {"requested": True}},
            "some",
            ScreeningStatus.CALLBACK_REQUESTED,
        ),
        ({"end_reason": EndReason.COMPLETED}, "all", ScreeningStatus.COMPLETED),
        ({"end_reason": EndReason.COMPLETED}, "declined", ScreeningStatus.COMPLETED),
        ({"end_reason": EndReason.HANGUP}, "all", ScreeningStatus.PARTIALLY_COMPLETED),
        ({"end_reason": EndReason.COMPLETED}, "some", ScreeningStatus.PARTIALLY_COMPLETED),
        ({"end_reason": EndReason.HANGUP}, "some", ScreeningStatus.PARTIALLY_COMPLETED),
        ({"end_reason": EndReason.HANGUP}, "none", None),  # unchanged
        ({"end_reason": EndReason.NO_RESPONSE}, "none", None),
    ],
)
def test_screening_status(
    overrides: dict[str, Any], fields: str, expected: ScreeningStatus | None
) -> None:
    final = _all_answered()
    if fields == "some":
        for key in list(final)[4:]:
            final[key] = FinalField(value=None, status="missing", source="none")
    elif fields == "none":
        final = {k: FinalField(value=None, status="missing", source="none") for k in final}
    elif fields == "declined":  # declined and unknown still count as settled
        first, second = list(final)[:2]
        final[first] = FinalField(value=None, status="declined", source="none")
        final[second] = FinalField(value=None, status="unknown", source="none")
    assert screening_status(make_result(**overrides), final, QUESTIONS) == expected


def test_final_pass_completes_a_screening_the_live_state_had_missing() -> None:
    """All other fields answered live; the last one was missed by STT but is in the words."""
    valid: dict[str, Any] = {
        "current_location": "Delhi",
        "current_company": "Infosys",
        "total_experience": 5.0,
        "relevant_experience": 3.0,
        "current_ctc": 12.0,
        "notice_period": "30 days",
        "reason_for_change": "growth",
        "interested": True,
        "interview_availability": "Monday",
    }
    live = {k: {"value": v, "status": "answered", "raw_text": str(v)} for k, v in valid.items()}
    live["expected_ctc"] = {"value": None, "status": "missing"}
    assert {q.key for q in QUESTIONS} == set(live)
    out = _final(
        final_output({"expected_ctc_lpa": 18}, [("expected_ctc", "eighteen lakhs", 10)]),
        fields=live,
        end_reason=EndReason.COMPLETED,
    )
    assert out.status == ScreeningStatus.COMPLETED


# --- The LLM call -------------------------------------------------------------------------------


async def test_run_final_pass_sends_the_numbered_transcript() -> None:
    llm = ScriptedLLM([final_output()])
    out = await run_final_pass(llm, TRANSCRIPT, QUESTIONS)
    assert out is not None
    prompt = llm.calls[0][-1].content
    assert "[2] Candidate: I'm in Delhi" in prompt and "[1] Assistant:" in prompt


async def test_run_final_pass_failure_returns_none() -> None:
    assert await run_final_pass(ScriptedLLM([LLMTimeoutError("t")]), TRANSCRIPT, QUESTIONS) is None


async def test_no_candidate_words_no_llm_call() -> None:
    llm = ScriptedLLM([])
    assert await run_final_pass(llm, TRANSCRIPT[:1], QUESTIONS) is None
    assert llm.calls == []


def test_restated_answers_are_not_conflicts() -> None:
    """Real calls 2026-11-19: same answer in other words → keep live, no conflict."""
    transcript = [
        {"seq": 1, "speaker": "assistant", "text": "Notice period?"},
        {"seq": 2, "speaker": "candidate", "text": "Thirty days."},
        {"seq": 3, "speaker": "assistant", "text": "Why change?"},
        {"seq": 4, "speaker": "candidate", "text": "I want to grow more in my career."},
    ]
    live = {
        "notice_period": {
            "value": "Thirty days",
            "status": "confirmed",
            "raw_text": "Thirty days.",
            "meta": {"days": 30},
        },
        "reason_for_change": {
            "value": "grow more in career",
            "status": "answered",
            "raw_text": "I want to grow more in my career.",
        },
    }
    out = _final(
        final_output(
            {
                "notice_period": "30 days",
                "notice_period_days": 30,
                "reason_for_change": "I want to grow more in my career",
            },
            [
                ("notice_period", "Thirty days.", 2),
                ("reason_for_change", "I want to grow more in my career.", 4),
            ],
        ),
        fields=live,
        transcript=transcript,
    )
    assert out.conflicts == {}
    assert out.fields["notice_period"].value == "Thirty days"
    assert out.fields["reason_for_change"].value == "grow more in career"


def test_live_line_is_found_by_exact_words_not_a_fuzzy_lookalike() -> None:
    from app.agent.final_pass import live_seq, transcript_lines

    lines = transcript_lines(TRANSCRIPT)
    assert live_seq({"raw_text": "twelve lakhs"}, lines) == 6  # not "eighteen lakhs" (seq 10)
    assert live_seq({"raw_text": "something unrelated", "turn": 2}, lines) == 4
