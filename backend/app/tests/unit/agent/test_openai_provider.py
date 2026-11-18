"""Retry and error mapping in the OpenAI adapter, with a fake client (no network)."""

from types import SimpleNamespace
from typing import Any

import openai
import pytest
from pydantic import BaseModel

from app.providers.llm.base import (
    LLMConfigError,
    LLMOutputError,
    LLMTimeoutError,
    LLMUnavailableError,
    Message,
)
from app.providers.llm.openai_provider import OpenAIProvider


class Out(BaseModel):
    answer: str


def _response(status: int) -> Any:
    import httpx2  # the HTTP client this SDK version uses

    url = "https://api.openai.com/v1/responses"
    return httpx2.Response(status, request=httpx2.Request("POST", url))


def _ok(parsed: Any) -> Any:
    return SimpleNamespace(
        output_parsed=parsed,
        status="completed",
        model="test-model",
        usage=SimpleNamespace(
            input_tokens=120,
            output_tokens=30,
            input_tokens_details=SimpleNamespace(cached_tokens=64),
        ),
        _request_id="req_1",
    )


class FakeResponses:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.kwargs: list[dict[str, Any]] = []

    async def parse(self, **kwargs: Any) -> Any:
        self.kwargs.append(kwargs)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def provider(outcomes: list[Any], **kw: Any) -> tuple[OpenAIProvider, FakeResponses]:
    fake = FakeResponses(outcomes)
    client = SimpleNamespace(responses=fake)
    return OpenAIProvider("k", "test-model", client=client, **kw), fake  # type: ignore[arg-type]


MSGS = [Message("system", "s"), Message("user", "hi")]


async def test_parses_and_reports_usage() -> None:
    p, fake = provider([_ok(Out(answer="x"))], reasoning_effort="none")
    res = await p.structured(MSGS, Out, timeout_s=5, cache_key="screening-1")
    assert res.value == Out(answer="x")
    assert (res.input_tokens, res.cached_tokens, res.output_tokens) == (120, 64, 30)
    assert res.request_id == "req_1" and res.attempts == 1
    sent = fake.kwargs[0]
    assert sent["text_format"] is Out and sent["store"] is False
    assert sent["prompt_cache_key"] == "screening-1"
    assert sent["reasoning"] == {"effort": "none"}
    assert sent["input"][0] == {"role": "system", "content": "s"}


async def test_retries_rate_limit_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    err = openai.RateLimitError("slow down", response=_response(429), body=None)
    p, _ = provider([err, _ok(Out(answer="x"))])
    res = await p.structured(MSGS, Out, timeout_s=5)
    assert res.attempts == 2


async def test_gives_up_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    errs = [
        openai.InternalServerError("boom", response=_response(500), body=None) for _ in range(3)
    ]
    p, fake = provider(errs)
    with pytest.raises(LLMUnavailableError):
        await p.structured(MSGS, Out, timeout_s=5)
    assert len(fake.kwargs) == 3  # 1 + 2 retries


async def test_auth_error_is_not_retried() -> None:
    err = openai.AuthenticationError("bad key", response=_response(401), body=None)
    p, fake = provider([err, _ok(Out(answer="x"))])
    with pytest.raises(LLMConfigError) as exc:
        await p.structured(MSGS, Out, timeout_s=5)
    assert len(fake.kwargs) == 1
    assert "bad key" not in str(exc.value)


async def test_timeout_maps_to_llm_timeout() -> None:
    p, _ = provider([TimeoutError()])
    with pytest.raises(LLMTimeoutError):
        await p.structured(MSGS, Out, timeout_s=5)


async def test_refusal_or_empty_parse_is_output_error() -> None:
    p, _ = provider([_ok(None)])
    with pytest.raises(LLMOutputError):
        await p.structured(MSGS, Out, timeout_s=5)


async def _no_sleep(_: float) -> None:
    return None
