"""Speech-to-text provider interface (P4-T1).

One provider instance per call session; streams are never shared. Audio goes in through
`send_audio()`; `TranscriptEvent`s come out of `get_transcription()` / `events()`.
`voice.utterance.UtteranceAssembler` turns the events into finished utterances.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Literal

EventKind = Literal["partial", "final", "speech_started", "utterance_end", "error", "closed"]


class STTError(Exception):
    """Base class for transcription failures."""


class STTConfigError(STTError):
    """The provider refused the session (bad key, bad model or parameters). Don't retry."""


class STTConnectionError(STTError):
    """No working stream (couldn't connect, or reconnecting failed)."""


@dataclass(frozen=True)
class TranscriptEvent:
    session_id: str
    kind: EventKind
    text: str = ""
    confidence: float | None = None
    # Seconds of session audio (continuous across reconnects), not wall-clock time. For
    # transcripts: first word start and last word end.
    start_s: float | None = None
    end_s: float | None = None
    endpoint: bool = False  # the provider says the speaker finished (Deepgram speech_final)
    received_at: float = 0.0  # time.monotonic()
    detail: str | None = None  # error description


@dataclass
class STTStats:
    connects: int = 0
    reconnects: int = 0
    audio_s_sent: float = 0.0
    dropped_audio_s: float = 0.0  # buffer overflow while reconnecting
    request_ids: list[str] = field(default_factory=list)  # for provider support tickets


class STTProvider(ABC):
    session_id: str
    stats: STTStats

    @abstractmethod
    async def start_stream(
        self,
        *,
        session_id: str,
        encoding: str,
        sample_rate: int,
        channels: int = 1,
        keyterms: Sequence[str] = (),
    ) -> None:
        """Open the stream. Raises STTConfigError (bad key) or STTConnectionError."""

    @abstractmethod
    async def send_audio(self, audio_chunk: bytes) -> None:
        """Queue audio. Never blocks on the network; a bounded buffer covers reconnects."""

    @abstractmethod
    async def get_transcription(self) -> TranscriptEvent:
        """The next event. After the stream ends, keeps returning the `closed` event."""

    async def events(self) -> AsyncIterator[TranscriptEvent]:
        """All events up to and including `closed`."""
        while True:
            event = await self.get_transcription()
            yield event
            if event.kind == "closed":
                return

    @abstractmethod
    def sent_at(self, audio_s: float) -> float | None:
        """Monotonic time at which the audio at `audio_s` (session time) was handed to
        `send_audio`. Used to measure end-of-speech → transcript latency."""

    @abstractmethod
    async def close(self) -> None:
        """Flush the final results, then close. Idempotent."""
