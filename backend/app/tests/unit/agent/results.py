"""Builders for stored screening results and final-pass outputs (test-only)."""

from typing import Any

from app.agent.conversation_manager import ScreeningResult
from app.agent.final_pass import FinalPassOutput
from app.agent.state import EndReason
from app.database.models import ScreeningStatus

MODEL_KEYS = (
    "current_location current_company total_experience_years relevant_experience_years "
    "current_ctc_lpa expected_ctc_lpa notice_period notice_period_days reason_for_change "
    "interested interview_availability"
).split()


def make_result(**overrides: Any) -> ScreeningResult:
    values: dict[str, Any] = {
        "end_reason": EndReason.COMPLETED,
        "screening_status": ScreeningStatus.COMPLETED,
        "collected_data": {
            "current_location": "Delhi",
            "total_experience": 3.0,
            "current_ctc": 12.0,
            "interested": True,
            "notice_period": None,
        },
        "fields": {
            "current_location": {
                "value": "Delhi",
                "status": "confirmed",
                "raw_text": "I'm in Delhi",
            },
            "total_experience": {"value": 3.0, "status": "confirmed", "raw_text": "three years"},
            "current_ctc": {"value": 12.0, "status": "confirmed", "raw_text": "twelve lakhs"},
            "interested": {"value": True, "status": "confirmed", "raw_text": "yes"},
            "notice_period": {"value": None, "status": "declined"},
        },
        "missing_fields": [],
        "callback": {"requested": False},
        "opted_out": False,
        "declined_opportunity": False,
        "identity_confirmed": True,
        "candidate_questions": [],
        "escalation_reason": None,
        "transcript": [
            {"seq": 1, "speaker": "assistant", "text": "Where are you based?"},
            {"seq": 2, "speaker": "candidate", "text": "I'm in Delhi"},
            {"seq": 3, "speaker": "assistant", "text": "And your experience?"},
            {"seq": 4, "speaker": "candidate", "text": "three years"},
            {"seq": 5, "speaker": "assistant", "text": "Current CTC?"},
            {"seq": 6, "speaker": "candidate", "text": "twelve lakhs"},
            {"seq": 7, "speaker": "assistant", "text": "Are you interested?"},
            {"seq": 8, "speaker": "candidate", "text": "yes"},
        ],
        "turns": 4,
        "llm_calls": 4,
        "input_tokens": 10,
        "output_tokens": 5,
    }
    values.update(overrides)
    return ScreeningResult(**values)


def final_output(
    fields: dict[str, Any] | None = None,
    evidence: list[tuple[str, str, int]] | None = None,
    custom: list[tuple[str, str, str, int]] | None = None,
) -> FinalPassOutput:
    """`fields` uses the model's keys (e.g. total_experience_years); evidence (field, quote,
    seq); custom (key, answer, quote, seq)."""
    data = dict.fromkeys(MODEL_KEYS)
    data.update(fields or {})
    return FinalPassOutput.model_validate(
        {
            "fields": data,
            "evidence": [{"field": f, "quote": q, "seq": s} for f, q, s in evidence or []],
            "custom_answers": [
                {"key": k, "answer": a, "quote": q, "seq": s} for k, a, q, s in custom or []
            ],
        }
    )
