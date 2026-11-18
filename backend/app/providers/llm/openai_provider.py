"""OpenAI adapter (Responses API). The only module in the app that imports `openai`."""

import asyncio
import random
import time
from typing import Any

import openai
import structlog
from openai import AsyncOpenAI
from pydantic import ValidationError

from app.providers.llm.base import (
    LLMConfigError,
    LLMError,
    LLMOutputError,
    LLMProvider,
    LLMResult,
    LLMTimeoutError,
    LLMUnavailableError,
    M,
    Message,
)

log = structlog.get_logger(__name__)

# Transient failures worth retrying inside the adapter (plan: 429/5xx with jitter, max 2).
_RETRYABLE = (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError)
_CONFIG = (
    openai.AuthenticationError,
    openai.PermissionDeniedError,
    openai.NotFoundError,
    openai.BadRequestError,
    openai.UnprocessableEntityError,
)


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        reasoning_effort: str | None = None,
        max_retries: int = 2,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_retries = max_retries
        # SDK retries off: this class owns retry policy so latency stays predictable.
        self._client = client or AsyncOpenAI(api_key=api_key, max_retries=0)

    async def aclose(self) -> None:
        await self._client.close()

    def _common(self, messages: list[Message], max_tokens: int, cache_key: str | None) -> Any:
        params: dict[str, Any] = {
            "model": self.model,
            "input": [{"role": m.role, "content": m.content} for m in messages],
            "max_output_tokens": max_tokens,
            "store": False,  # candidate data isn't kept on OpenAI's side for later retrieval
        }
        if cache_key:
            params["prompt_cache_key"] = cache_key
        if self.reasoning_effort:
            params["reasoning"] = {"effort": self.reasoning_effort}
        return params

    async def structured(
        self,
        messages: list[Message],
        schema: type[M],
        *,
        timeout_s: float,
        max_tokens: int = 1000,
        cache_key: str | None = None,
    ) -> LLMResult[M]:
        params = self._common(messages, max_tokens, cache_key)

        async def call() -> Any:
            return await self._client.responses.parse(
                **params, text_format=schema, timeout=timeout_s
            )

        response, latency_ms, attempts = await self._with_retries(call, timeout_s, schema.__name__)
        parsed = response.output_parsed
        if parsed is None:
            raise LLMOutputError(f"No parsed output (status={response.status})")
        return self._result(response, parsed, latency_ms, attempts, schema.__name__)

    async def text(
        self,
        messages: list[Message],
        *,
        timeout_s: float,
        max_tokens: int,
        cache_key: str | None = None,
    ) -> LLMResult[str]:
        params = self._common(messages, max_tokens, cache_key)

        async def call() -> Any:
            return await self._client.responses.create(**params, timeout=timeout_s)

        response, latency_ms, attempts = await self._with_retries(call, timeout_s, "text")
        text = (response.output_text or "").strip()
        if not text:
            raise LLMOutputError(f"Empty text output (status={response.status})")
        return self._result(response, text, latency_ms, attempts, "text")

    async def _with_retries(self, call: Any, timeout_s: float, label: str) -> tuple[Any, int, int]:
        attempt = 0
        while True:
            attempt += 1
            started = time.perf_counter()
            try:
                # Hard backstop in case the SDK timeout doesn't fire (e.g. slow streaming body).
                async with asyncio.timeout(timeout_s + 1):
                    response = await call()
                return response, int((time.perf_counter() - started) * 1000), attempt
            except (TimeoutError, openai.APITimeoutError) as exc:
                log.warning("llm_timeout", schema=label, attempt=attempt, timeout_s=timeout_s)
                raise LLMTimeoutError(f"LLM call timed out after {timeout_s}s") from exc
            except _CONFIG as exc:
                log.error("llm_config_error", schema=label, status=exc.status_code)
                raise LLMConfigError(f"OpenAI rejected the request ({exc.status_code})") from exc
            except _RETRYABLE as exc:
                if attempt > self.max_retries:
                    log.error("llm_unavailable", schema=label, attempts=attempt)
                    raise LLMUnavailableError(f"OpenAI unavailable: {type(exc).__name__}") from exc
                delay = min(2.0, 0.25 * 2 ** (attempt - 1)) * (0.5 + random.random())  # noqa: S311
                log.warning("llm_retry", schema=label, attempt=attempt, error=type(exc).__name__)
                await asyncio.sleep(delay)
            except (
                ValidationError,
                openai.LengthFinishReasonError,
                openai.ContentFilterFinishReasonError,
            ) as exc:
                log.warning("llm_bad_output", schema=label, error=type(exc).__name__)
                raise LLMOutputError(f"Output failed validation: {type(exc).__name__}") from exc
            except openai.OpenAIError as exc:
                raise LLMError(f"OpenAI error: {type(exc).__name__}") from exc

    def _result(
        self, response: Any, value: Any, latency_ms: int, attempts: int, label: str
    ) -> LLMResult[Any]:
        usage = response.usage
        input_tokens = usage.input_tokens if usage else 0
        output_tokens = usage.output_tokens if usage else 0
        details = getattr(usage, "input_tokens_details", None) if usage else None
        cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
        request_id = getattr(response, "_request_id", None)
        log.info(
            "llm_call",
            schema=label,
            model=response.model,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            cached_tokens=cached,
            output_tokens=output_tokens,
            attempts=attempts,
            request_id=request_id,
        )
        return LLMResult(
            value=value,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=response.model,
            request_id=request_id,
            cached_tokens=cached,
            attempts=attempts,
        )
