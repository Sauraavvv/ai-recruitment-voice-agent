"""Live agent evaluation as a pytest gate (phase plan 7.2). Calls the real OpenAI API.

Excluded from the default `make test`; run with `make agent-eval` or `pytest -m llm`.
"""

import os

import pytest

from app.tests.agent_eval.runner import evaluate, print_report

pytestmark = pytest.mark.llm


@pytest.mark.skipif(
    not (os.getenv("OPENAI_API_KEY") and os.getenv("OPENAI_MODEL")),
    reason="OPENAI_API_KEY and OPENAI_MODEL are not set",
)
async def test_agent_scenarios() -> None:
    runs = int(os.getenv("AGENT_EVAL_RUNS", "3"))
    summary = await evaluate(runs=runs)
    print_report(summary)
    failing_safety = [sid for sid, s in summary["scenarios"].items() if not s["safety_ok"]]
    assert not failing_safety, f"safety assertions failed: {failing_safety}"
    assert summary["non_safety_check_pass_rate"] >= 0.9
