"""The demo's LLM: Groq first, OpenAI when Groq can't answer the turn."""

from typing import Any

import pytest
from pydantic import BaseModel, SecretStr

from app.providers.llm import create_demo_llm
from app.providers.llm.base import (
    LLMConfigError,
    LLMError,
    LLMProvider,
    LLMResult,
    LLMTimeoutError,
    LLMUnavailableError,
    Message,
)
from app.providers.llm.fallback import FallbackLLM
from app.providers.llm.groq_provider import GroqProvider
from app.providers.llm.openai_provider import OpenAIProvider
from app.tests.conftest import make_settings


class Out(BaseModel):
    answer: str


class Fake(LLMProvider):
    def __init__(self, name: str, error: Exception | None = None) -> None:
        self.name = name
        self.error = error
        self.calls: list[float] = []
        self.closed = False

    def _result(self, value: Any) -> Any:
        return LLMResult(
            value=value, latency_ms=1, input_tokens=1, output_tokens=1, model=self.name
        )

    async def structured(self, messages: Any, schema: Any, *, timeout_s: float, **_: Any) -> Any:
        self.calls.append(timeout_s)
        if self.error:
            raise self.error
        return self._result(schema(answer=self.name))

    async def text(self, messages: Any, *, timeout_s: float, **_: Any) -> Any:
        self.calls.append(timeout_s)
        if self.error:
            raise self.error
        return self._result(self.name)

    async def aclose(self) -> None:
        self.closed = True


MSG = [Message("user", "hi")]


async def test_primary_answers_when_it_can() -> None:
    groq, openai = Fake("groq"), Fake("openai")
    llm = FallbackLLM(groq, openai, fallback_timeout_s=8)
    assert (await llm.structured(MSG, Out, timeout_s=5)).value.answer == "groq"
    assert openai.calls == [] and llm.switches == 0


@pytest.mark.parametrize(
    "error",
    [LLMUnavailableError("all keys busy"), LLMTimeoutError("slow"), LLMConfigError("400")],
)
async def test_switches_when_groq_cannot_answer(error: Exception) -> None:
    groq, openai = Fake("groq", error), Fake("openai")
    llm = FallbackLLM(groq, openai, fallback_timeout_s=8)
    assert (await llm.structured(MSG, Out, timeout_s=5)).value.answer == "openai"
    assert (await llm.text(MSG, timeout_s=5, max_tokens=10)).value == "openai"
    assert openai.calls == [8, 8] and llm.switches == 2  # the fallback gets its own timeout
    await llm.aclose()
    assert groq.closed and openai.closed


async def test_fallback_errors_are_not_hidden() -> None:
    llm = FallbackLLM(Fake("groq", LLMUnavailableError("busy")), Fake("openai", LLMError("down")))
    with pytest.raises(LLMError, match="down"):
        await llm.structured(MSG, Out, timeout_s=5)


def test_create_demo_llm_choices() -> None:
    both = create_demo_llm(
        make_settings(
            groq_api_keys=SecretStr("k1"), openai_api_key=SecretStr("sk"), openai_model="m"
        )
    )
    assert isinstance(both, FallbackLLM)
    assert isinstance(both.primary, GroqProvider) and isinstance(both.fallback, OpenAIProvider)
    assert both.primary.json_schema and both.primary.max_retries == 0

    groq_only = create_demo_llm(
        make_settings(groq_api_keys=SecretStr("k1"), openai_api_key=None, openai_model="m")
    )
    assert isinstance(groq_only, GroqProvider)
    openai_only = create_demo_llm(
        make_settings(
            groq_api_keys=None, groq_api_key=None, openai_api_key=SecretStr("sk"), openai_model="m"
        )
    )
    assert isinstance(openai_only, OpenAIProvider)
    with pytest.raises(LLMConfigError):
        create_demo_llm(make_settings(groq_api_keys=None, groq_api_key=None, openai_api_key=None))
