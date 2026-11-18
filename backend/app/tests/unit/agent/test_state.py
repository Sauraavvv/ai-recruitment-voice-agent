"""Merge table (phase plan 5.3), missing-field tracking and next-question selection."""

from app.agent.state import (
    MAX_ASKS,
    AskKind,
    FieldStatus,
    MergeOutcome,
    QuestionSpec,
    ScreeningState,
)

QUESTIONS = [
    QuestionSpec(key="interested", prompt="Interested?", type="boolean"),
    QuestionSpec(key="current_location", prompt="Where?"),
    QuestionSpec(key="total_experience", prompt="Years?", type="number"),
    QuestionSpec(key="interview_availability", prompt="When?", required=False),
]


def status(s: ScreeningState, key: str) -> FieldStatus:
    return s.fields[key].status  # a call, so mypy doesn't narrow across merges


def new_state() -> ScreeningState:
    return ScreeningState.new(candidate_name="Asha Rao", job_title="QA", questions=QUESTIONS)


def test_value_into_missing_is_answered() -> None:
    s = new_state()
    assert s.merge("current_location", "Pune", raw_text="in Pune", turn=1) is MergeOutcome.SET
    rec = s.fields["current_location"]
    assert (rec.value, rec.status, rec.raw_text, rec.turn) == (
        "Pune",
        FieldStatus.ANSWERED,
        "in Pune",
        1,
    )


def test_null_never_overwrites() -> None:
    s = new_state()
    s.merge("current_location", "Pune", raw_text="Pune", turn=1)
    assert s.merge("current_location", None, raw_text=None, turn=2) is MergeOutcome.IGNORED
    assert s.fields["current_location"].value == "Pune"


def test_same_value_is_unchanged_and_affirmation_confirms() -> None:
    s = new_state()
    s.merge("total_experience", 5.0, raw_text="5", turn=1)
    assert s.merge("total_experience", 5, raw_text="five", turn=2) is MergeOutcome.UNCHANGED
    assert status(s, "total_experience") == FieldStatus.ANSWERED
    s.merge("total_experience", 5.0, raw_text="yes 5", turn=3, affirmed=True)
    assert status(s, "total_experience") == FieldStatus.CONFIRMED


def test_same_string_ignores_case() -> None:
    s = new_state()
    s.merge("current_location", "Pune", raw_text="Pune", turn=1)
    assert s.merge("current_location", " pune ", raw_text="pune", turn=2) is MergeOutcome.UNCHANGED


def test_different_value_is_corrected_with_history_and_needs_confirmation() -> None:
    s = new_state()
    s.merge("total_experience", 5.0, raw_text="5 years", turn=1)
    s.confirm("total_experience")
    outcome = s.merge("total_experience", 6.0, raw_text="actually 6", turn=4)
    rec = s.fields["total_experience"]
    assert outcome is MergeOutcome.CORRECTED
    assert rec.value == 6.0 and rec.status is FieldStatus.ANSWERED and rec.needs_confirmation
    assert [p.value for p in rec.previous] == [5.0]
    assert s.next_field() == "total_experience"  # confirmation comes first


def test_decline_only_from_missing_and_volunteered_later() -> None:
    s = new_state()
    assert s.decline("total_experience")
    assert status(s, "total_experience") == FieldStatus.DECLINED
    assert "total_experience" not in s.missing_fields()
    assert s.merge("total_experience", 4.0, raw_text="ok it's 4", turn=5) is MergeOutcome.SET
    assert status(s, "total_experience") == FieldStatus.ANSWERED

    s.merge("current_location", "Pune", raw_text="Pune", turn=1)
    assert not s.decline("current_location")  # a refusal never discards an answer
    assert s.fields["current_location"].value == "Pune"


def test_boolean_false_is_a_value() -> None:
    s = new_state()
    assert s.merge("interested", False, raw_text="no", turn=1) is MergeOutcome.SET
    assert s.merge("interested", True, raw_text="yes", turn=2) is MergeOutcome.CORRECTED


def test_next_field_follows_job_order_and_skips_settled() -> None:
    s = new_state()
    assert s.next_field() == "interested"
    s.merge("interested", True, raw_text="yes", turn=1)
    s.merge("total_experience", 3.0, raw_text="3", turn=1)
    assert s.next_field() == "current_location"
    s.mark_unknown("current_location")
    assert s.next_field() == "interview_availability"


def test_next_field_skips_fields_asked_too_often() -> None:
    s = new_state()
    for _ in range(MAX_ASKS):
        s.note_asked("interested", AskKind.QUESTION)
    assert s.next_field() == "current_location"


def test_required_complete_ignores_optional() -> None:
    s = new_state()
    s.merge("interested", True, raw_text="yes", turn=1)
    s.merge("current_location", "Pune", raw_text="Pune", turn=1)
    s.decline("total_experience")
    assert s.required_complete()
    assert s.missing_fields() == ["interview_availability"]
    assert s.missing_fields(required_only=True) == []


def test_plan_json_shape() -> None:
    s = new_state()
    s.merge("current_location", "Gurgaon", raw_text="Gurgaon", turn=1)
    data = s.plan_json()
    assert data["collected_data"]["current_location"] == "Gurgaon"
    assert "current_location" not in data["missing_fields"]
    assert data["conversation_status"] == "in_progress"
    assert set(data) >= {"callback_requested", "opted_out", "current_question"}
