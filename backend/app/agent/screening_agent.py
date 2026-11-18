"""One LLM call per candidate turn, with the retry policy from phase plan 5.6 step 3."""

from dataclasses import dataclass, field

import structlog

from app.agent.prompts import PROMPT_VERSION
from app.agent.schemas import AgentTurn
from app.providers.llm.base import (
    LLMError,
    LLMOutputError,
    LLMProvider,
    LLMTimeoutError,
    LLMUnavailableError,
    Message,
)

log = structlog.get_logger(__name__)

DEFAULT_TIMEOUT_S = 8.0
MAX_OUTPUT_TOKENS = 1200
_RETRY_ON = (LLMTimeoutError, LLMUnavailableError, LLMOutputError)


@dataclass
class CallMetrics:
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    model: str
    request_id: str | None
    ok: bool = True
    error: str | None = None


@dataclass
class TurnCall:
    turn: AgentTurn
    calls: list[CallMetrics] = field(default_factory=list)

    @property
    def retries(self) -> int:
        return len(self.calls) - 1


class TurnFailed(LLMError):
    def __init__(self, message: str, calls: list[CallMetrics]) -> None:
        super().__init__(message)
        self.calls = calls


class ScreeningAgent:
    def __init__(
        self,
        llm: LLMProvider,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        cache_key: str | None = None,
    ) -> None:
        self.llm = llm
        self.timeout_s = timeout_s
        self.cache_key = cache_key

    async def run(self, messages: list[Message]) -> TurnCall:
        """Call the LLM; retry once on timeout, outage or invalid output."""
        calls: list[CallMetrics] = []
        last_error: LLMError | None = None
        for attempt in (1, 2):
            try:
                result = await self.llm.structured(
                    messages,
                    AgentTurn,
                    timeout_s=self.timeout_s,
                    max_tokens=MAX_OUTPUT_TOKENS,
                    cache_key=self.cache_key,
                )
            except _RETRY_ON as exc:
                last_error = exc
                calls.append(CallMetrics(0, 0, 0, 0, "", None, ok=False, error=type(exc).__name__))
                log.warning(
                    "agent_turn_retry" if attempt == 1 else "agent_turn_failed",
                    error=type(exc).__name__,
                    prompt_version=PROMPT_VERSION,
                )
                continue
            calls.append(
                CallMetrics(
                    result.latency_ms,
                    result.input_tokens,
                    result.output_tokens,
                    result.cached_tokens,
                    result.model,
                    result.request_id,
                )
            )
            return TurnCall(result.value, calls)
        raise TurnFailed(f"LLM turn failed: {type(last_error).__name__}", calls)
