"""Groq adapter (OpenAI-compatible Chat Completions). Used to write telephonic round questions.

Groq serves open-weight models (default: openai/gpt-oss-120b) behind an OpenAI-compatible API,
so this uses the `openai` SDK pointed at Groq's base URL. Output is requested as a JSON object
and validated against the Pydantic schema here (one extra try if it doesn't validate).

Several API keys rotate: each request starts at the next key (round-robin across the process),
and a key that is rate limited (429) or rejected (401/403) hands over to the next one within
the same request. Logs name a key only by its position, never its value.
"""

import asyncio
import itertools
import json
import random
import time
from collections.abc import Awaitable, Callable
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

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

_RETRYABLE = (openai.InternalServerError, openai.APIConnectionError)
_CONFIG = (openai.NotFoundError, openai.BadRequestError, openai.UnprocessableEntityError)

# Where the next request starts in the key list (shared by every provider in the process)
_rotation = itertools.count()


class GroqProvider(LLMProvider):
    def __init__(
        self,
        api_keys: str | list[str],
        model: str,
        *,
        reasoning_effort: str | None = None,
        max_retries: int = 2,
        clients: list[Any] | None = None,
    ) -> None:
        keys = [api_keys] if isinstance(api_keys, str) else list(api_keys)
        if not keys and not clients:
            raise LLMConfigError("No Groq API key")
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.max_retries = max_retries
        self._clients: list[Any] = clients or [
            AsyncOpenAI(api_key=key, base_url=GROQ_BASE_URL, max_retries=0) for key in keys
        ]

    async def aclose(self) -> None:
        for client in self._clients:
            await client.close()

    def _params(self, messages: list[Message], max_tokens: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            # Chat Completions has no "developer" role on every model: send it as system
            "messages": [
                {"role": "system" if m.role == "developer" else m.role, "content": m.content}
                for m in messages
            ],
            "max_completion_tokens": max_tokens,
        }
        if self.reasoning_effort:
            params["reasoning_effort"] = self.reasoning_effort
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
        params = self._params(messages, max_tokens)
        params["response_format"] = {"type": "json_object"}
        last_error: Exception | None = None
        for output_try in range(2):  # one more try when the JSON doesn't fit the schema
            response, latency_ms, attempts = await self._with_retries(
                lambda client: client.chat.completions.create(**params, timeout=timeout_s),
                timeout_s,
                schema.__name__,
            )
            content = (response.choices[0].message.content or "").strip()
            try:
                value = schema.model_validate(json.loads(content))
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                log.warning(
                    "llm_bad_output",
                    schema=schema.__name__,
                    output_try=output_try + 1,
                    error=type(exc).__name__,
                )
                continue
            return self._result(response, value, latency_ms, attempts, schema.__name__)
        raise LLMOutputError(f"Output failed validation: {type(last_error).__name__}")

    async def text(
        self,
        messages: list[Message],
        *,
        timeout_s: float,
        max_tokens: int,
        cache_key: str | None = None,
    ) -> LLMResult[str]:
        params = self._params(messages, max_tokens)
        response, latency_ms, attempts = await self._with_retries(
            lambda client: client.chat.completions.create(**params, timeout=timeout_s),
            timeout_s,
            "text",
        )
        text = (response.choices[0].message.content or "").strip()
        if not text:
            raise LLMOutputError("Empty text output")
        return self._result(response, text, latency_ms, attempts, "text")

    async def _with_retries(
        self, call: Callable[[Any], Awaitable[Any]], timeout_s: float, label: str
    ) -> tuple[Any, int, int]:
        """Run `call(client)` starting at the next key in rotation. A rate-limited or rejected
        key hands over to the next key; when every usable key is rate limited (or the server
        errs), wait and go round again, up to `max_retries` more rounds."""
        count = len(self._clients)
        start = next(_rotation) % count
        attempt = 0
        rounds = 0
        rejected: set[int] = set()
        while True:
            for offset in range(count):
                index = (start + offset) % count
                if index in rejected:
                    continue
                attempt += 1
                started = time.perf_counter()
                try:
                    # Hard backstop in case the SDK timeout doesn't fire
                    async with asyncio.timeout(timeout_s + 1):
                        response = await call(self._clients[index])
                    return response, int((time.perf_counter() - started) * 1000), attempt
                except (TimeoutError, openai.APITimeoutError) as exc:
                    log.warning("llm_timeout", schema=label, key=index, timeout_s=timeout_s)
                    raise LLMTimeoutError(f"LLM call timed out after {timeout_s}s") from exc
                except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
                    log.error("llm_key_rejected", schema=label, key=index, status=exc.status_code)
                    rejected.add(index)  # a bad key won't get better: skip it from now on
                except openai.RateLimitError:
                    log.warning("llm_key_rate_limited", schema=label, key=index)
                except _RETRYABLE as exc:
                    log.warning("llm_retry", schema=label, key=index, error=type(exc).__name__)
                except _CONFIG as exc:
                    log.error("llm_config_error", schema=label, status=exc.status_code)
                    raise LLMConfigError(
                        f"The AI service rejected the request ({exc.status_code})"
                    ) from exc
                except openai.OpenAIError as exc:
                    raise LLMError(f"AI service error: {type(exc).__name__}") from exc
            if len(rejected) == count:
                raise LLMConfigError("Every AI key was rejected")
            rounds += 1
            if rounds > self.max_retries:
                log.error("llm_unavailable", schema=label, attempts=attempt, keys=count)
                raise LLMUnavailableError("AI service unavailable: every key is busy")
            delay = min(4.0, 0.5 * 2 ** (rounds - 1)) * (0.5 + random.random())  # noqa: S311
            await asyncio.sleep(delay)

    def _result(
        self, response: Any, value: Any, latency_ms: int, attempts: int, label: str
    ) -> LLMResult[Any]:
        usage = response.usage
        input_tokens = (getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
        output_tokens = (getattr(usage, "completion_tokens", 0) or 0) if usage else 0
        request_id = getattr(response, "_request_id", None)
        log.info(
            "llm_call",
            schema=label,
            model=response.model,
            latency_ms=latency_ms,
            input_tokens=input_tokens,
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
            attempts=attempts,
        )
