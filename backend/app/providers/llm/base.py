"""Provider-neutral LLM interface. The agent depends on this, never on a vendor SDK."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)

Role = Literal["system", "developer", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class LLMResult[T]:
    value: T
    latency_ms: int
    input_tokens: int
    output_tokens: int
    model: str
    request_id: str | None = None
    cached_tokens: int = 0
    attempts: int = 1


class LLMError(RuntimeError):
    """Base class. Messages never contain prompt text or secrets."""


class LLMTimeoutError(LLMError):
    pass


class LLMUnavailableError(LLMError):
    """Rate limited, 5xx or connection failure after retries."""


class LLMOutputError(LLMError):
    """The model refused, was cut off, or returned output that failed schema validation."""


class LLMConfigError(LLMError):
    """Bad API key, unknown model or an invalid request: retrying won't help."""


class LLMProvider(ABC):
    @abstractmethod
    async def structured(
        self,
        messages: list[Message],
        schema: type[M],
        *,
        timeout_s: float,
        max_tokens: int = 1000,
        cache_key: str | None = None,
    ) -> LLMResult[M]:
        """Return output validated against `schema` (a Pydantic model)."""

    @abstractmethod
    async def text(
        self,
        messages: list[Message],
        *,
        timeout_s: float,
        max_tokens: int,
        cache_key: str | None = None,
    ) -> LLMResult[str]:
        """Return plain text."""

    async def aclose(self) -> None:  # noqa: B027  (optional hook)
        """Release HTTP connections."""
