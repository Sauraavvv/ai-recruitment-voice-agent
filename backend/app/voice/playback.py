"""Outgoing audio: agent text → TTS stream → 8 kHz frames → paced WebSocket messages
(phase-06 P6-T4, P6-T5).

- `AudioSender`: frames phone-side audio and paces it, at most TELEPHONY_SEND_AHEAD_MS ahead of
  real time, so `clear` (barge-in) takes effect quickly. Bound to one session: audio for another
  session is refused (plan: no audio crossing between candidates).
- `MarkTracker`: Exotel echoes a `mark` once the audio before it has played (verified in P5,
  about 0.47 s after it finished at our end). That's the "playback finished" signal.
- `Player`: speaks one reply at a time. The reply's first sentence is streamed while the rest is
  already being synthesized (chunk N+1 during N). Records t3 (first TTS audio) and t4 (first
  frame sent) for the latency table. On barge-in the pipeline cancels `speak()` and calls
  `interrupt()`, which sends `clear` and estimates how much the candidate heard.
"""

import asyncio
import base64
import contextlib
import json
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from app.providers.tts.base import AudioClip, TTSProvider
from app.voice import audio_converter as ac
from app.voice.chunker import split_sentences

# Exotel plays our audio this long after our playhead (mark round trip in P5 minus network).
PLAYOUT_LAG_MS = 400.0
MARK_GRACE_S = 5.0


class CrossSessionAudioError(RuntimeError):
    """Audio produced for one call was about to be sent on another call's stream."""


class TextSink(Protocol):
    async def send_text(self, data: str) -> None: ...


class AudioSender:
    """Frames phone-side audio and paces it to Exotel. One playback at a time."""

    def __init__(
        self,
        ws: TextSink,
        stream_sid: str,
        *,
        encoding: ac.Encoding,
        sample_rate: int,
        frame_bytes: int,
        send_ahead_ms: int,
        session_id: str | None = None,
    ) -> None:
        self._ws = ws
        self._sid = stream_sid
        self.session_id = session_id
        self.encoding: ac.Encoding = encoding
        self.rate = sample_rate
        self.frame_bytes = frame_bytes
        self.frame_s = ac.duration_ms(frame_bytes, encoding, sample_rate) / 1000
        self.ahead_s = max(send_ahead_ms / 1000, self.frame_s)
        self._framer = ac.Framer(frame_bytes, encoding=encoding)
        self._playhead = 0.0  # monotonic time at which everything sent so far has played
        self._lock = asyncio.Lock()
        self.frames_sent = 0
        self.bytes_sent = 0
        self.clears = 0
        self.on_frame: Callable[[int], None] | None = None  # bytes per frame, for the player

    def _check(self, session_id: str | None) -> None:
        if session_id is not None and self.session_id is not None and session_id != self.session_id:
            raise CrossSessionAudioError(f"audio for {session_id} on stream of {self.session_id}")

    async def send_json(self, message: dict[str, Any]) -> None:
        await self._ws.send_text(json.dumps(message))

    async def _send_frame(self, frame: bytes, *, ahead_s: float) -> None:
        now = time.monotonic()
        wait = self._playhead - now - ahead_s
        if wait > 0:
            await asyncio.sleep(wait)
            now = time.monotonic()
        await self.send_json(
            {
                "event": "media",
                "stream_sid": self._sid,
                "media": {"payload": base64.b64encode(frame).decode()},
            }
        )
        self._playhead = max(self._playhead, now) + self.frame_s
        self.frames_sent += 1
        self.bytes_sent += len(frame)
        if self.on_frame is not None:
            self.on_frame(len(frame))

    async def push(
        self, phone_audio: bytes, *, ahead_s: float | None = None, session_id: str | None = None
    ) -> None:
        """Send whole frames now (paced); keep the remainder for the next push."""
        self._check(session_id)
        async with self._lock:
            for frame in self._framer.push(phone_audio):
                await self._send_frame(frame, ahead_s=ahead_s or self.ahead_s)

    async def flush(self, *, ahead_s: float | None = None, session_id: str | None = None) -> None:
        """Send the remainder, padded to a whole frame."""
        self._check(session_id)
        async with self._lock:
            for frame in self._framer.flush():
                await self._send_frame(frame, ahead_s=ahead_s or self.ahead_s)

    async def play(
        self,
        phone_audio: bytes,
        *,
        mark: str | None = None,
        ahead_s: float | None = None,
        session_id: str | None = None,
    ) -> None:
        """Send a whole clip (last frame padded), then an optional mark."""
        await self.push(phone_audio, ahead_s=ahead_s, session_id=session_id)
        await self.flush(ahead_s=ahead_s, session_id=session_id)
        if mark:
            await self.mark(mark)

    async def mark(self, name: str) -> None:
        await self.send_json({"event": "mark", "stream_sid": self._sid, "mark": {"name": name}})

    async def clear(self) -> None:
        self._framer.reset()
        self._playhead = time.monotonic()
        self.clears += 1
        await self.send_json({"event": "clear", "stream_sid": self._sid})

    @property
    def buffered_s(self) -> float:
        return max(0.0, self._playhead - time.monotonic())

    @property
    def playhead(self) -> float:
        """Monotonic time at which everything sent so far will have played at our end."""
        return self._playhead


class MarkTracker:
    """Marks we sent and the ones Exotel echoed back."""

    def __init__(self) -> None:
        self.sent: dict[str, float] = {}
        self.returned: dict[str, float] = {}
        self._events: dict[str, asyncio.Event] = {}

    def event(self, name: str) -> asyncio.Event:
        return self._events.setdefault(name, asyncio.Event())

    def note_sent(self, name: str) -> None:
        self.sent[name] = time.monotonic()

    def note_returned(self, name: str) -> None:
        self.returned[name] = time.monotonic()
        self.event(name).set()

    async def wait(self, name: str, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self.event(name).wait(), timeout)
            return True
        except TimeoutError:
            return False

    def latencies(self) -> dict[str, float]:
        back = self.returned
        return {k: round(back[k] - v, 3) for k, v in self.sent.items() if k in back}


@dataclass
class SpeechResult:
    label: str
    text: str
    started_at: float  # monotonic, speak() called
    first_chunk_at: float | None = None  # t3: first TTS audio ready
    first_frame_at: float | None = None  # t4: first frame of it sent
    sent_ms: float = 0.0  # audio sent to the phone
    mark_returned: bool | None = None
    interrupted: bool = False
    heard_ms: float | None = None
    cached: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def total_ms(self) -> float:
        return self.sent_ms


def _closing(
    stream: AsyncIterator[AudioClip],
) -> contextlib.aclosing[AsyncGenerator[AudioClip, None]]:
    """Close the provider's stream (and its HTTP request) when playback stops early."""
    return contextlib.aclosing(cast(AsyncGenerator[AudioClip, None], stream))


def split_for_prefetch(text: str) -> list[str]:
    """First sentence alone (fast first audio), the rest as one more request."""
    sentences = split_sentences(text)
    if len(sentences) <= 1:
        return [text]
    return [sentences[0], " ".join(sentences[1:])]


class Player:
    def __init__(
        self,
        sender: AudioSender,
        tts: TTSProvider,
        marks: MarkTracker,
        *,
        session_id: str,
        no_split: frozenset[str] = frozenset(),
    ) -> None:
        if sender.session_id is not None and sender.session_id != session_id:
            raise CrossSessionAudioError("player and sender belong to different sessions")
        self.sender = sender
        self.tts = tts
        self.marks = marks
        self.session_id = session_id
        self.no_split = no_split  # cached fixed phrases: one request, served from the cache
        self.current: SpeechResult | None = None
        self.on_first_frame: Callable[[SpeechResult], None] | None = None
        self._count = 0
        sender.on_frame = self._frame_sent

    def _frame_sent(self, n_bytes: int) -> None:
        cur = self.current
        if cur is None or cur.interrupted:
            return
        if cur.first_frame_at is None:
            cur.first_frame_at = time.monotonic()
            if self.on_first_frame is not None:
                self.on_first_frame(cur)
        cur.sent_ms += ac.duration_ms(n_bytes, self.sender.encoding, self.sender.rate)

    def _label(self, kind: str) -> str:
        self._count += 1
        return f"{kind}-{self._count}"

    async def _clips(self, text: str) -> AsyncIterator[AudioClip]:
        parts = [text] if text in self.no_split else split_for_prefetch(text)
        aid = self.session_id
        if len(parts) == 1:
            async with _closing(self.tts.stream(text, call_attempt_id=aid)) as gen:
                async for clip in gen:
                    yield clip
            return
        queue: asyncio.Queue[AudioClip | BaseException | None] = asyncio.Queue()

        async def prefetch() -> None:
            try:
                async with _closing(self.tts.stream(parts[1], call_attempt_id=aid)) as gen:
                    async for clip in gen:
                        queue.put_nowait(clip)
            except Exception as exc:
                queue.put_nowait(exc)
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(prefetch(), name=f"tts-prefetch:{aid[:8]}")
        try:
            async with _closing(self.tts.stream(parts[0], call_attempt_id=aid)) as gen:
                async for clip in gen:
                    yield clip
            while (item := await queue.get()) is not None:
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    def new_label(self, kind: str) -> str:
        return self._label(kind)

    async def speak(
        self, text: str, *, kind: str = "reply", label: str | None = None, wait: bool = True
    ) -> SpeechResult:
        """Stream `text` to the phone. With `wait`, returns once Exotel says it has played.
        Cancelling it stops sending at once (call `interrupt()` to clear what's queued)."""
        result = SpeechResult(
            label=label or self._label(kind), text=text, started_at=time.monotonic()
        )
        self.current = result
        resampler: ac.StreamResampler | None = None
        async for clip in self._clips(text):
            if result.first_chunk_at is None:
                result.first_chunk_at = time.monotonic()
            if resampler is None:
                resampler = ac.StreamResampler(clip.sample_rate, self.sender.rate)
            await self.sender.push(
                self._encode(resampler.process(clip.pcm)), session_id=self.session_id
            )
        if resampler is not None:
            await self.sender.push(self._encode(resampler.flush()), session_id=self.session_id)
        await self._finish(result, wait=wait)
        return result

    async def play_clip(
        self, clip: AudioClip, *, kind: str, label: str | None = None, wait: bool = True
    ) -> SpeechResult:
        """A pre-synthesized clip (greeting, acknowledgement, apology)."""
        result = SpeechResult(
            label=label or self._label(kind), text=kind, started_at=time.monotonic(), cached=True
        )
        result.first_chunk_at = result.started_at
        self.current = result
        audio = ac.to_telephony(
            clip.pcm, clip.sample_rate, to_rate=self.sender.rate, encoding=self.sender.encoding
        )
        await self.sender.push(audio, session_id=self.session_id)
        await self._finish(result, wait=wait)
        return result

    async def wait_played(self, result: SpeechResult) -> bool:
        result.mark_returned = await self.marks.wait(
            result.label, timeout=self.sender.buffered_s + MARK_GRACE_S
        )
        return result.mark_returned

    def _encode(self, pcm: bytes) -> bytes:
        return ac.pcm16_to_mulaw(pcm) if self.sender.encoding == "mulaw" else pcm

    async def _finish(self, result: SpeechResult, *, wait: bool) -> None:
        await self.sender.flush(session_id=self.session_id)
        self.marks.note_sent(result.label)
        await self.sender.mark(result.label)
        result.extra["tts_done"] = True
        if wait:
            await self.wait_played(result)

    def heard_ms(self, result: SpeechResult | None = None) -> float:
        """Estimate of how much of the playback the candidate has heard so far."""
        result = result or self.current
        if result is None:
            return 0.0
        played = result.sent_ms - self.sender.buffered_s * 1000 - PLAYOUT_LAG_MS
        return max(0.0, min(result.sent_ms, played))

    async def interrupt(self) -> SpeechResult | None:
        """Barge-in: stop what's queued at Exotel (`clear`) and record what was heard."""
        result = self.current
        if result is not None and not result.interrupted:
            result.heard_ms = self.heard_ms(result)
            result.interrupted = True
        await self.sender.clear()
        return result
