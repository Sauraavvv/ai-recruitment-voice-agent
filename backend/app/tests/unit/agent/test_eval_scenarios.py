"""Scenario files are checked offline so a typo doesn't waste a paid eval run."""

from app.agent.schemas import FieldName
from app.tests.agent_eval.runner import load_scenarios, validate_scenario


def test_all_scenarios_are_well_formed() -> None:
    scenarios = load_scenarios(None)
    assert len(scenarios) >= 14
    known = {f.value for f in FieldName}
    for sc in scenarios:
        assert validate_scenario(sc, known) == [], sc["id"]
    assert len({sc["id"] for sc in scenarios}) == len(scenarios)
