"""Telephony provider interface (plan.md Module E).

The rest of the app sees internal statuses and E.164 numbers only; each adapter maps its
provider's statuses and number formats at the boundary.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class TelephonyError(Exception):
    """A provider request failed. Messages never contain credentials."""


class TelephonyConfigError(TelephonyError):
    """Credentials or account configuration rejected (401/403, unknown account or flow)."""


class TelephonyRejectedError(TelephonyError):
    """The provider refused the request; no call was placed (4xx other than auth)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class TelephonyTimeoutError(TelephonyError):
    """No answer from the provider. The call MAY have been placed: never retry blindly."""


@dataclass(frozen=True)
class ProviderCall:
    """Result of placing a call."""

    provider_call_id: str
    raw_status: str | None


@dataclass(frozen=True)
class ProviderCallStatus:
    """A provider's view of one call, already mapped to internal terms."""

    provider_call_id: str
    raw_status: str | None
    status: str  # internal CallStatus value
    end_reason: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_seconds: int | None = None
    recording_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class TelephonyProvider(ABC):
    name: str

    @abstractmethod
    async def initiate_call(
        self, *, to_phone: str, call_attempt_id: str, status_callback_url: str
    ) -> ProviderCall:
        """Place an outbound call to `to_phone` (E.164) that runs our streaming flow."""

    @abstractmethod
    async def get_call_status(self, provider_call_id: str) -> ProviderCallStatus | None:
        """Current status, or None if the provider has no such call."""

    @abstractmethod
    async def find_calls(self, *, to_phone: str, since: datetime) -> list[ProviderCallStatus]:
        """Calls to `to_phone` created at or after `since` (used after an initiate timeout)."""

    async def close(self) -> None:  # noqa: B027 - optional hook
        """Release HTTP clients."""
