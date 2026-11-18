"""Provider-neutral text-to-speech interface. The voice pipeline depends on this, never on a
vendor package.

Providers return their model's native format (mono, signed 16-bit little-endian PCM at
`sample_rate`). Conversion to the telephony codec is a separate step (Phase 5), so either side
can change on its own.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

# Played when speech fails for good; every provider pre-synthesizes it at startup.
TECHNICAL_APOLOGY = "Sorry, I'm having a technical problem. We'll call you back."


@dataclass(frozen=True)
class AudioClip:
    pcm: bytes  # signed 16-bit little-endian, mono
    sample_rate: int  # the model's native rate
    duration_ms: int

    @classmethod
    def from_pcm(cls, pcm: bytes, sample_rate: int) -> "AudioClip":
        return cls(
            pcm=pcm, sample_rate=sample_rate, duration_ms=len(pcm) // 2 * 1000 // sample_rate
        )

    @property
    def is_empty(self) -> bool:
        return not self.pcm


@dataclass(frozen=True)
class ProviderStatus:
    """What the settings page (Phase 8) and call eligibility (Phase 5) need to know."""

    name: str
    ready: bool
    detail: str  # model and voice, or why it isn't ready
    last_error: str | None = None
    last_latency_ms: int | None = None
    model_loads: int = 0
    # A provider made of others (primary + fallback) lists their statuses here.
    components: tuple["ProviderStatus", ...] = ()


class TTSError(RuntimeError):
    """Base class. Messages never contain the text being spoken."""


class TTSConfigError(TTSError):
    """Bad model path, unknown voice or a missing dependency: retrying won't help."""


class TTSNotReadyError(TTSError):
    """`synthesize` was called before `initialize` succeeded."""


class TTSTimeoutError(TTSError):
    pass


class TTSSynthesisError(TTSError):
    """The model raised or produced unusable audio."""


class TTSStreamInterruptedError(TTSSynthesisError):
    """A stream failed after some audio was already delivered."""


class TTSProvider(ABC):
    sample_rate: int

    @abstractmethod
    async def initialize(self) -> None:
        """Load the model and synthesize a warm-up sentence. Raises TTSConfigError on failure."""

    @abstractmethod
    async def synthesize(self, text: str, *, call_attempt_id: str | None = None) -> AudioClip:
        """Speak agent text. The provider normalizes it for its model (numbers, acronyms…) and
        splits text that is too long for one pass. Empty text gives an empty clip."""

    async def stream(
        self, text: str, *, call_attempt_id: str | None = None
    ) -> AsyncIterator[AudioClip]:
        """Yield the audio in pieces as soon as each is ready, for playback while the rest is
        still being generated. The default yields the whole clip at once (local models are fast
        enough)."""
        clip = await self.synthesize(text, call_attempt_id=call_attempt_id)
        if not clip.is_empty:
            yield clip

    def forget_call(self, call_attempt_id: str) -> None:  # noqa: B027  (optional hook)
        """The call ended: drop any per-call state (the fallback provider's sticky choice)."""

    @abstractmethod
    def apology_clip(self, *, call_attempt_id: str | None = None) -> AudioClip:
        """Pre-synthesized 'Sorry, I'm having a technical problem…' for a call to end on (P6)."""

    @abstractmethod
    async def close(self) -> None:
        """Release the model and its executor."""

    @abstractmethod
    def status(self) -> ProviderStatus: ...
