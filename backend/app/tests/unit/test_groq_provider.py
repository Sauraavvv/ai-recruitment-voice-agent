"""Groq adapter with stand-in clients (no network): JSON parsing, one retry on bad output,
key rotation and failover, and what's sent."""

from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from pydantic import BaseModel, SecretStr

from app.providers.llm import groq_provider
from app.providers.llm.base import LLMConfigError, LLMOutputError, LLMUnavailableError, Message
from app.providers.llm.groq_provider import GroqProvider
from app.tests.conftest import make_settings


class Out(BaseModel):
    answer: str


def _error(cls: type[openai.APIStatusError], status: int) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return cls("no", response=response, body=None)  # type: ignore[arg-type]


class FakeClient:
    """Answers with the next queued item: a JSON string, or an exception to raise."""

    def __init__(self, name: str, replies: list[Any]) -> None:
        self.name = name
        self.replies = replies
        self.sent: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs: Any) -> Any:
        self.sent.append(kwargs)
        reply = self.replies.pop(0) if self.replies else f'{{"answer": "{self.name}"}}'
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
            model="openai/gpt-oss-120b",
        )

    async def close(self) -> None:
        pass


def _provider(*clients: FakeClient, **kwargs: Any) -> GroqProvider:
    return GroqProvider(
        [], "openai/gpt-oss-120b", reasoning_effort="medium", clients=list(clients), **kwargs
    )


@pytest.fixture(autouse=True)
def _start_at_first_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import itertools

    monkeypatch.setattr(groq_provider, "_rotation", itertools.count())


async def test_structured_parses_json_and_sends_json_mode() -> None:
    client = FakeClient("a", ['{"answer": "yes"}'])
    messages = [Message("developer", "rules"), Message("user", "hi")]
    result = await _provider(client).structured(messages, Out, timeout_s=5, max_tokens=100)
    assert result.value.answer == "yes"
    assert (result.input_tokens, result.output_tokens) == (10, 5)
    sent = client.sent[0]
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["reasoning_effort"] == "medium" and sent["max_completion_tokens"] == 100
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]


async def test_structured_retries_once_on_bad_output() -> None:
    client = FakeClient("a", ["not json", '{"answer": "second"}'])
    result = await _provider(client).structured([Message("user", "hi")], Out, timeout_s=5)
    assert result.value.answer == "second" and len(client.sent) == 2

    with pytest.raises(LLMOutputError):
        await _provider(FakeClient("a", ["nope", '{"wrong": 1}'])).structured(
            [Message("user", "hi")], Out, timeout_s=5
        )


async def test_requests_rotate_through_the_keys() -> None:
    a, b, c = FakeClient("a", []), FakeClient("b", []), FakeClient("c", [])
    provider = _provider(a, b, c)
    answers = [
        (await provider.structured([Message("user", "hi")], Out, timeout_s=5)).value.answer
        for _ in range(4)
    ]
    assert answers == ["a", "b", "c", "a"]


async def test_a_busy_or_bad_key_hands_over_to_the_next() -> None:
    a = FakeClient("a", [_error(openai.RateLimitError, 429)])
    b = FakeClient("b", [_error(openai.AuthenticationError, 401)])
    c = FakeClient("c", [])
    result = await _provider(a, b, c).structured([Message("user", "hi")], Out, timeout_s=5)
    assert result.value.answer == "c" and result.attempts == 3


async def test_every_key_rejected_or_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = [FakeClient(n, [_error(openai.AuthenticationError, 401)]) for n in "ab"]
    with pytest.raises(LLMConfigError):
        await _provider(*bad).structured([Message("user", "hi")], Out, timeout_s=5)

    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr("app.providers.llm.groq_provider.asyncio.sleep", no_wait)
    busy = [FakeClient(n, [_error(openai.RateLimitError, 429)] * 3) for n in "ab"]
    with pytest.raises(LLMUnavailableError):
        await _provider(*busy, max_retries=2).structured([Message("user", "hi")], Out, timeout_s=5)
    assert [len(c.sent) for c in busy] == [3, 3]  # three rounds over both keys


def test_settings_collect_the_keys() -> None:
    settings = make_settings().model_copy(
        update={
            "groq_api_keys": SecretStr(" k1, k2 ,\nk3,k1,, "),
            "groq_api_key": SecretStr("k4"),
        }
    )
    assert settings.groq_keys == ["k1", "k2", "k3", "k4"]
    assert make_settings().model_copy(update={"groq_api_keys": None}).groq_keys == []


# --- json_schema mode (the home page demo's screening agent) ---------------------------------


class Turn(BaseModel):
    reply: str
    unknown_fields: list[str]
    note: str | None
    done: bool


def _invalid_json(failed: str) -> openai.BadRequestError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    body = {"code": "json_validate_failed", "failed_generation": failed, "message": "no"}
    return openai.BadRequestError("no", response=httpx.Response(400, request=request), body=body)  # type: ignore[arg-type]


async def test_json_schema_mode_sends_the_strict_schema() -> None:
    client = FakeClient("a", ['{"reply": "hi", "unknown_fields": [], "note": null, "done": false}'])
    result = await _provider(client, json_schema=True).structured(
        [Message("user", "hi")], Turn, timeout_s=5
    )
    assert result.value.reply == "hi"
    fmt = client.sent[0]["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert set(fmt["json_schema"]["schema"]["required"]) == {
        "reply",
        "unknown_fields",
        "note",
        "done",
    }


async def test_json_schema_mode_repairs_a_missing_empty_field() -> None:
    # Groq refused the output: only the empty list, the null and the flag were left out
    client = FakeClient("a", [_invalid_json('{"reply": "Thanks."}')])
    result = await _provider(client, json_schema=True).structured(
        [Message("user", "hi")], Turn, timeout_s=5
    )
    assert result.value == Turn(reply="Thanks.", unknown_fields=[], note=None, done=False)
    assert len(client.sent) == 1


async def test_json_schema_mode_never_invents_real_answers() -> None:
    # `reply` can't be filled in: one more try, then a clear output error
    client = FakeClient("a", [_invalid_json('{"done": true}'), _invalid_json('{"done": true}')])
    with pytest.raises(LLMOutputError):
        await _provider(client, json_schema=True).structured(
            [Message("user", "hi")], Turn, timeout_s=5
        )
    assert len(client.sent) == 2


async def test_json_schema_mode_other_bad_requests_stay_errors() -> None:
    client = FakeClient("a", [_error(openai.BadRequestError, 400)])
    with pytest.raises(LLMConfigError):
        await _provider(client, json_schema=True).structured(
            [Message("user", "hi")], Turn, timeout_s=5
        )
