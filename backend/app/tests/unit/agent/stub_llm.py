"""Scripted LLM for deterministic agent tests. Test-only; production uses the OpenAI adapter."""

from collections import deque
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from app.agent.prompts import CandidateContext, JobConfig
from app.agent.schemas import AgentTurn, NextAction
from app.providers.llm.base import LLMProvider, LLMResult, M, Message

NOW = datetime(2026, 11, 18, 5, 30, tzinfo=UTC)  # 11:00 IST, a Wednesday


class FixedClock:
    def __init__(self, now: datetime = NOW) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def turn(
    say: str = "Okay.",
    *,
    fields: dict[str, Any] | None = None,
    evidence: dict[str, str] | None = None,
    next_question: str | None = None,
    action: NextAction = NextAction.ASK_QUESTION,
    **flags: Any,
) -> AgentTurn:
    """An AgentTurn with sensible defaults. `evidence` maps field key -> quote."""
    extracted = {
        k: None
        for k in (
            "current_location current_company total_experience_years relevant_experience_years "
            "current_ctc_lpa expected_ctc_lpa notice_period notice_period_days reason_for_change "
            "interested interview_availability"
        ).split()
    }
    extracted.update(fields or {})
    data: dict[str, Any] = {
        "extracted_fields": extracted,
        "evidence": [{"field": k, "quote": q} for k, q in (evidence or {}).items()],
        "ranges": [],
        "custom_answers": [],
        "declined_fields": [],
        "unknown_fields": [],
        "confirmed_fields": [],
        "identity_confirmed": None,
        "permission_granted": None,
        "callback_requested": False,
        "callback_time_text": None,
        "callback_time_iso": None,
        "opt_out": False,
        "declined_opportunity": False,
        "candidate_question": None,
        "next_action": action,
        "next_question": next_question,
        "conversation_complete": False,
        "response_text": say,
    }
    data.update(flags)
    return AgentTurn.model_validate(data)


class ScriptedLLM(LLMProvider):
    """Returns queued outputs in order. Queue an Exception instance to raise it."""

    def __init__(self, outputs: list[Any] | None = None) -> None:
        self.outputs: deque[Any] = deque(outputs or [])
        self.calls: list[list[Message]] = []

    def push(self, *outputs: Any) -> None:
        self.outputs.extend(outputs)

    async def structured(
        self,
        messages: list[Message],
        schema: type[M],
        *,
        timeout_s: float,
        max_tokens: int = 1000,
        cache_key: str | None = None,
    ) -> LLMResult[M]:
        self.calls.append(messages)
        out = self.outputs.popleft()
        if isinstance(out, Exception):
            raise out
        assert isinstance(out, BaseModel)
        return LLMResult(value=out, latency_ms=5, input_tokens=100, output_tokens=50, model="stub")  # type: ignore[arg-type]

    async def text(
        self,
        messages: list[Message],
        *,
        timeout_s: float,
        max_tokens: int,
        cache_key: str | None = None,
    ) -> LLMResult[str]:
        self.calls.append(messages)
        out = self.outputs.popleft()
        if isinstance(out, Exception):
            raise out
        return LLMResult(
            value=str(out), latency_ms=5, input_tokens=100, output_tokens=50, model="stub"
        )


JOB = JobConfig.from_dict(
    {
        "id": "job-1",
        "job_title": "Backend Developer",
        "company_name": "Acme Technologies",
        "location": "Bengaluru",
        "required_experience": "3-6 years",
        "skills": ["Python", "FastAPI"],
        "job_description": "Build APIs for the hiring platform.",
    }
)
CANDIDATE = CandidateContext(name="Rahul Sharma", candidate_id="cand-1")
