"""Test-only harness for `CallSession` (phase-06 §7.1): fake STT, TTS and phone line, the
scripted LLM, and an inbound audio feeder. Nothing here writes to a database.

    h = Harness(llm)
    await h.start()                  # session running, greeting played
    h.say("Yes, speaking.")          # the candidate's next utterance (STT events)
    await h.voice(800)               # loud audio on the line for 800 ms (VAD, barge-in)
    outcome = await h.hang_up()
"""

import asyncio
import contextlib
import json
import time
from collections.abc import AsyncIterator, Callable, Sequence
from typing import Any

import numpy as np

from app.agent.conversation_manager import ConversationManager, ScreeningResult
from app.config import Settings
from app.providers.stt.base import STTProvider, STTStats, TranscriptEvent
from app.providers.tts.base import AudioClip, ProviderStatus, TTSProvider, TTSSynthesisError
from app.tests.conftest import make_settings
from app.tests.unit.agent.stub_llm import CANDIDATE, JOB, FixedClock, ScriptedLLM
from app.voice.audio_processor import InboundQueue
from app.voice.pipeline import CallContext, CallSession, SessionOutcome
from app.voice.playback import AudioSender, MarkTracker
from app.voice.turn_manager import TurnState
from app.voice.vad import SpeechDetector

RATE = 8000
FRAME = 320  # 20 ms at 8 kHz, 16-bit


def fast_settings(**overrides: Any) -> Settings:
    # model_copy skips validation, so timers can be shorter than production allows
    return make_settings().model_copy(
        update={
            "greeting_wait_ms": 60,
            "silence_timeout_s": 0.6,
            "barge_in_min_ms": 200,
            "backchannel_max_ms": 400,
            "vad_end_silence_ms": 200,
            "vad_speech_start_ms": 60,
            "telephony_send_ahead_ms": 100,
            "telephony_frame_bytes": 640,
            "call_wrap_up_s": 600,
            "max_call_duration_s": 900,
            "voice_tts_warm": False,
            "voice_hold_after_ms": 0,
            **overrides,
        }
    )


class FakeSTT(STTProvider):
    """Events are pushed by the test (`say`), audio is only counted."""

    def __init__(self) -> None:
        self.session_id = ""
        self.stats = STTStats()
        self.audio_bytes = 0
        self.finalizes = 0
        self.queue: asyncio.Queue[TranscriptEvent] = asyncio.Queue()
        self.closed = False
        self.fail_start: Exception | None = None

    async def start_stream(
        self,
        *,
        session_id: str,
        encoding: str,
        sample_rate: int,
        channels: int = 1,
        keyterms: Sequence[str] = (),
    ) -> None:
        self.session_id = session_id
        if self.fail_start is not None:
            raise self.fail_start

    async def send_audio(self, audio_chunk: bytes) -> None:
        self.audio_bytes += len(audio_chunk)

    async def finalize(self) -> None:
        self.finalizes += 1

    def push(self, kind: str, text: str = "", **kw: Any) -> None:
        self.queue.put_nowait(
            TranscriptEvent(self.session_id, kind, text, received_at=time.monotonic(), **kw)  # type: ignore[arg-type]
        )

    def say(self, text: str, confidence: float = 0.95) -> None:
        self.push("partial", text)
        self.push("final", text, confidence=confidence, endpoint=True, start_s=0.0, end_s=1.0)

    async def get_transcription(self) -> TranscriptEvent:
        return await self.queue.get()

    def sent_at(self, audio_s: float) -> float | None:
        return None  # the harness measures t0 with the VAD

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.push("closed")


class FakeTTS(TTSProvider):
    """A tone, `ms_per_word` long per word, at 24 kHz. Streams in two pieces."""

    sample_rate = 24000

    def __init__(self, ms_per_word: float = 40.0, delay_s: float = 0.0) -> None:
        self.ms_per_word = ms_per_word
        self.delay_s = delay_s
        self.spoken: list[tuple[str | None, str]] = []  # (call_attempt_id, text)
        self.fail = False
        self.forgotten: list[str] = []

    def _clip(self, text: str) -> AudioClip:
        n = int(self.sample_rate * max(1, len(text.split())) * self.ms_per_word / 1000)
        tone = (3000 * np.sin(np.arange(n) * 2 * np.pi * 300 / self.sample_rate)).astype("<i2")
        return AudioClip.from_pcm(tone.tobytes(), self.sample_rate)

    async def initialize(self) -> None:
        return None

    async def synthesize(self, text: str, *, call_attempt_id: str | None = None) -> AudioClip:
        if self.fail:
            raise TTSSynthesisError("fake failure")
        self.spoken.append((call_attempt_id, text))
        return self._clip(text)

    async def stream(
        self, text: str, *, call_attempt_id: str | None = None
    ) -> AsyncIterator[AudioClip]:
        if self.fail:
            raise TTSSynthesisError("fake failure")
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        self.spoken.append((call_attempt_id, text))
        pcm = self._clip(text).pcm
        half = len(pcm) // 4 * 2
        yield AudioClip.from_pcm(pcm[:half], self.sample_rate)
        yield AudioClip.from_pcm(pcm[half:], self.sample_rate)

    def forget_call(self, call_attempt_id: str) -> None:
        self.forgotten.append(call_attempt_id)

    def apology_clip(self, *, call_attempt_id: str | None = None) -> AudioClip:
        self.spoken.append((call_attempt_id, "<apology>"))
        return self._clip("sorry technical problem")

    async def close(self) -> None:
        return None

    def status(self) -> ProviderStatus:
        return ProviderStatus("fake", True, "tone")


class FakeLine:
    """The phone side of the WebSocket: records what we send, echoes marks once the audio before
    them has played (and never after a `clear`, like Exotel)."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.sender: AudioSender | None = None
        self.marks: MarkTracker | None = None
        self._pending: set[asyncio.Task[None]] = set()

    async def send_text(self, data: str) -> None:
        message = json.loads(data)
        self.sent.append(message)
        if message["event"] == "mark":
            task = asyncio.create_task(self._echo(message["mark"]["name"]))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)
        elif message["event"] == "clear":
            for task in list(self._pending):
                task.cancel()

    async def _echo(self, name: str) -> None:
        assert self.sender is not None and self.marks is not None
        await asyncio.sleep(self.sender.buffered_s + 0.03)
        self.marks.note_returned(name)

    def events(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.sent if m["event"] == kind]


class Harness:
    def __init__(
        self,
        llm: ScriptedLLM | None = None,
        *,
        attempt_id: str = "attempt-0001",
        settings: Settings | None = None,
        tts: FakeTTS | None = None,
        candidate: Any = CANDIDATE,
        on_end: Callable[[SessionOutcome[ScreeningResult]], Any] | None = None,
    ) -> None:
        self.settings = settings or fast_settings()
        self.llm = llm or ScriptedLLM()
        self.stt = FakeSTT()
        self.tts = tts or FakeTTS()
        self.line = FakeLine()
        self.marks = MarkTracker()
        self.inbound = InboundQueue(RATE * 2 * 2)
        self.sender = AudioSender(
            self.line,
            f"stream-{attempt_id}",
            encoding="slin",
            sample_rate=RATE,
            frame_bytes=self.settings.telephony_frame_bytes,
            send_ahead_ms=self.settings.telephony_send_ahead_ms,
            session_id=attempt_id,
        )
        self.line.sender, self.line.marks = self.sender, self.marks
        self.manager = ConversationManager(JOB, candidate, self.llm, FixedClock())
        self.vad = SpeechDetector(
            lambda _frame: True,  # energy only: loud frames are speech
            start_ms=self.settings.vad_speech_start_ms,
            end_silence_ms=self.settings.vad_end_silence_ms,
            min_dbfs=self.settings.vad_min_dbfs,
            echo_margin_db=0.0,
            name="energy",
        )
        self.session = CallSession(
            CallContext(attempt_id=attempt_id, job=JOB, candidate=candidate),
            settings=self.settings,
            sender=self.sender,
            inbound=self.inbound,
            marks=self.marks,
            stt=self.stt,
            tts=self.tts,
            manager=self.manager,
            vad=self.vad,
            on_end=on_end,
        )
        self._loud_until = 0.0
        self._feeder: asyncio.Task[None] | None = None
        self.task: asyncio.Task[SessionOutcome[ScreeningResult]] | None = None

    # --- driving ---------------------------------------------------------------------------

    async def _feed(self) -> None:
        loud = (np.random.default_rng(1).normal(0, 6000, FRAME // 2)).astype("<i2").tobytes()
        quiet = b"\0" * FRAME
        start = time.monotonic()
        i = 0
        while True:
            self.inbound.put(loud if time.monotonic() < self._loud_until else quiet)
            i += 1
            await asyncio.sleep(max(0.0, start + i * 0.02 - time.monotonic()))

    async def start(self, *, wait_greeting: bool = True) -> None:
        self._feeder = asyncio.create_task(self._feed())
        self.task = asyncio.create_task(self.session.run())
        if wait_greeting:
            await self.wait(lambda: self.session._greeted, 5)

    async def voice(self, ms: float, *, wait: bool = True) -> None:
        self._loud_until = time.monotonic() + ms / 1000
        if wait:
            await asyncio.sleep(ms / 1000)

    def say(self, text: str, confidence: float = 0.95) -> None:
        self.stt.say(text, confidence)

    @property
    def state(self) -> TurnState:
        return self.session.turns.state

    async def wait(self, condition: Callable[[], bool], timeout: float = 5.0) -> None:
        async def poll() -> None:
            while not condition():  # noqa: ASYNC110  (test polling)
                await asyncio.sleep(0.01)

        await asyncio.wait_for(poll(), timeout)

    async def wait_listening(self, replies: int, timeout: float = 5.0) -> None:
        """Until the agent has said `replies` lines in all and is listening again."""
        await self.wait(
            lambda: self.state is TurnState.LISTENING and self.agent_lines() >= replies, timeout
        )

    def agent_lines(self) -> int:
        return sum(1 for e in self.manager.transcript if e.speaker == "assistant")

    async def hang_up(
        self, reason: str = "stop", timeout: float = 10.0
    ) -> SessionOutcome[ScreeningResult]:
        self.session.caller_hung_up(reason)
        return await self.finished(timeout)

    async def finished(self, timeout: float = 10.0) -> SessionOutcome[ScreeningResult]:
        assert self.task is not None
        try:
            return await asyncio.wait_for(asyncio.shield(self.task), timeout)
        finally:
            if self._feeder is not None:
                self._feeder.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._feeder

    def spoken(self) -> list[str]:
        return [text for _aid, text in self.tts.spoken]
