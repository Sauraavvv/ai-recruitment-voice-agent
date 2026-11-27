"""An LLM that switches to a second provider when the first can't answer.

Used by the home page demo: Groq first (fast); when every Groq key is rate limited, the call
times out or the output doesn't fit the schema, the same turn goes to OpenAI, so the visitor's
call carries on instead of ending with "I'm having trouble on my side".
"""

import structlog

from app.providers.llm.base import (
    LLMConfigError,
    LLMOutputError,
    LLMProvider,
    LLMResult,
    LLMTimeoutError,
    LLMUnavailableError,
    M,
    Message,
)

log = structlog.get_logger(__name__)

# What makes the turn move to the fallback (a bad key setup on the fallback still raises)
SWITCH_ON = (LLMUnavailableError, LLMTimeoutError, LLMOutputError, LLMConfigError)


class FallbackLLM(LLMProvider):
    def __init__(
        self,
        primary: LLMProvider,
        fallback: LLMProvider,
        *,
        fallback_timeout_s: float | None = None,
        names: tuple[str, str] = ("primary", "fallback"),
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.fallback_timeout_s = fallback_timeout_s
        self.names = names
        self.switches = 0

    def _timeout(self, timeout_s: float) -> float:
        return max(timeout_s, self.fallback_timeout_s or 0)

    async def structured(
        self,
        messages: list[Message],
        schema: type[M],
        *,
        timeout_s: float,
        max_tokens: int = 1000,
        cache_key: str | None = None,
    ) -> LLMResult[M]:
        try:
            return await self.primary.structured(
                messages, schema, timeout_s=timeout_s, max_tokens=max_tokens, cache_key=cache_key
            )
        except SWITCH_ON as exc:
            self._switched(exc, schema.__name__)
        return await self.fallback.structured(
            messages,
            schema,
            timeout_s=self._timeout(timeout_s),
            max_tokens=max_tokens,
            cache_key=cache_key,
        )

    async def text(
        self,
        messages: list[Message],
        *,
        timeout_s: float,
        max_tokens: int,
        cache_key: str | None = None,
    ) -> LLMResult[str]:
        try:
            return await self.primary.text(
                messages, timeout_s=timeout_s, max_tokens=max_tokens, cache_key=cache_key
            )
        except SWITCH_ON as exc:
            self._switched(exc, "text")
        return await self.fallback.text(
            messages, timeout_s=self._timeout(timeout_s), max_tokens=max_tokens, cache_key=cache_key
        )

    def _switched(self, exc: Exception, label: str) -> None:
        self.switches += 1
        log.warning(
            "llm_switched",
            schema=label,
            primary=self.names[0],
            fallback=self.names[1],
            reason=type(exc).__name__,
        )

    async def aclose(self) -> None:
        for provider in (self.primary, self.fallback):
            try:
                await provider.aclose()
            except Exception:
                log.warning("llm_close_failed", provider=type(provider).__name__)
