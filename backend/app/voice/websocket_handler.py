"""Exotel Voicebot media stream (phase-05 P5-T6..T9). PoC behaviour: test clip, echo,
mark/clear checks. Phase 6 replaces the PoC script with the conversation.

Lifecycle of one stream:
  accept → `connected` → `start` (resolve + verify the attempt, check the media format) →
  register a CallSession → media/mark/dtmf/stop … → cleanup (cancel tasks, unregister, save the
  capture, release the slot).

The inbound queue is bounded (about 2 s of audio); on overflow the oldest audio is dropped and
logged. Outgoing audio is framed to TELEPHONY_FRAME_BYTES and paced close to real time, at most
TELEPHONY_SEND_AHEAD_MS ahead, so `clear` (barge-in) takes effect quickly.
"""

import asyncio
import base64
import contextlib
import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from app.config import Settings
from app.database.connection import get_sessionmaker
from app.providers.telephony import exotel_models as em
from app.providers.tts.base import TTSError, TTSProvider
from app.services import call_service
from app.utils.log import get_logger
from app.utils.redis import KEY_PREFIX, get_redis
from app.voice import audio_converter as ac
from app.voice import pcm as pcm_utils

logger = get_logger(__name__)

START_TIMEOUT_S = 10.0
INBOUND_QUEUE_SECONDS = 2.0
POC_MODE_KEY = KEY_PREFIX + "call:{attempt_id}:poc_mode"
POC_MODES = ("full", "listen", "screen")  # screen: live screening (voice/live_screening.py)
SAVE_GRACE_S = 30.0  # after the caller hangs up, time to finish and store the screening
MAX_LOGGED_MEDIA = 30  # media messages kept in the capture's message log

# Live sessions in this process, by call_attempt_id.
SESSIONS: dict[str, "CallSession"] = {}


# --- Outgoing audio ---------------------------------------------------------------------------


class AudioSender:
    """Frames phone-side audio and paces it to Exotel. One playback at a time."""

    def __init__(self, ws: WebSocket, stream_sid: str, settings: Settings) -> None:
        self._ws = ws
        self._sid = stream_sid
        self.encoding: ac.Encoding = settings.telephony_encoding
        self.rate = settings.telephony_sample_rate
        self.frame_bytes = settings.telephony_frame_bytes
        self.frame_s = ac.duration_ms(self.frame_bytes, self.encoding, self.rate) / 1000
        self.ahead_s = max(settings.telephony_send_ahead_ms / 1000, self.frame_s)
        self._framer = ac.Framer(self.frame_bytes, encoding=self.encoding)
        self._playhead = 0.0  # monotonic time at which everything sent so far has played
        self._lock = asyncio.Lock()
        self.frames_sent = 0
        self.bytes_sent = 0

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

    async def push(self, phone_audio: bytes, *, ahead_s: float | None = None) -> None:
        """Send whole frames now (paced); keep the remainder for the next push."""
        async with self._lock:
            for frame in self._framer.push(phone_audio):
                await self._send_frame(frame, ahead_s=ahead_s or self.ahead_s)

    async def play(
        self, phone_audio: bytes, *, mark: str | None = None, ahead_s: float | None = None
    ) -> None:
        """Send a whole clip (last frame padded), then an optional mark."""
        await self.push(phone_audio, ahead_s=ahead_s)
        async with self._lock:
            for frame in self._framer.flush():
                await self._send_frame(frame, ahead_s=ahead_s or self.ahead_s)
        if mark:
            await self.mark(mark)

    async def mark(self, name: str) -> None:
        await self.send_json({"event": "mark", "stream_sid": self._sid, "mark": {"name": name}})

    async def clear(self) -> None:
        self._framer.reset()
        self._playhead = time.monotonic()
        await self.send_json({"event": "clear", "stream_sid": self._sid})

    @property
    def buffered_s(self) -> float:
        return max(0.0, self._playhead - time.monotonic())


# --- Capture (PoC) ----------------------------------------------------------------------------


@dataclass
class StreamCapture:
    """What came in on the stream: counts, timing, first message of each type, audio."""

    started: float = field(default_factory=time.monotonic)
    counts: dict[str, int] = field(default_factory=dict)
    first_shapes: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    media_bytes: int = 0
    media_sizes: dict[int, int] = field(default_factory=dict)
    first_media_at: float | None = None
    last_media_at: float | None = None
    last_sequence: int | None = None
    sequence_gaps: int = 0
    dropped_inbound_bytes: int = 0
    audio: bytearray = field(default_factory=bytearray)
    marks_sent: dict[str, float] = field(default_factory=dict)
    marks_back: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def t(self) -> float:
        return round(time.monotonic() - self.started, 3)

    def note(self, text: str) -> None:
        self.notes.append(f"{self.t():8.3f}s {text}")

    def record(self, message: dict[str, Any], payload_len: int | None) -> None:
        kind = str(message.get("event", "?"))
        self.counts[kind] = self.counts.get(kind, 0) + 1
        if kind not in self.first_shapes:
            self.first_shapes[kind] = em.message_shape(message)
            logger.info("stream_first_message", message_type=kind, shape=self.first_shapes[kind])
        seq = message.get("sequence_number")
        try:
            seq_i = int(seq) if seq is not None else None
        except (TypeError, ValueError):
            seq_i = None
        if seq_i is not None and self.last_sequence is not None and seq_i != self.last_sequence + 1:
            self.sequence_gaps += 1
        if seq_i is not None:
            self.last_sequence = seq_i
        if kind != "media" or self.counts[kind] <= MAX_LOGGED_MEDIA:
            self.messages.append({"t": self.t(), "message": sanitize(message)})
        if payload_len is not None:
            now = time.monotonic()
            self.first_media_at = self.first_media_at or now
            self.last_media_at = now
            self.media_bytes += payload_len
            self.media_sizes[payload_len] = self.media_sizes.get(payload_len, 0) + 1

    def inbound_rate(self) -> float | None:
        if not (self.first_media_at and self.last_media_at) or self.counts.get("media", 0) < 10:
            return None
        span = self.last_media_at - self.first_media_at
        n = self.counts["media"]
        # n chunks span n-1 intervals; scale bytes accordingly
        return self.media_bytes * (n - 1) / n / span if span > 0 else None

    def summary(self) -> dict[str, Any]:
        return {
            "counts": self.counts,
            "media_bytes": self.media_bytes,
            "media_chunk_sizes": self.media_sizes,
            "inbound_bytes_per_second": round(self.inbound_rate() or 0, 1),
            "sequence_gaps": self.sequence_gaps,
            "dropped_inbound_bytes": self.dropped_inbound_bytes,
            "marks_sent": self.marks_sent,
            "marks_back": self.marks_back,
            "mark_latency_s": {
                k: round(self.marks_back[k] - v, 3)
                for k, v in self.marks_sent.items()
                if k in self.marks_back
            },
            "notes": self.notes,
        }


_SENSITIVE = {"from", "to", "account_sid"}


def sanitize(message: Any) -> Any:
    """Copy of a stream message safe to keep: audio replaced by its length, numbers masked."""
    if isinstance(message, dict):
        out: dict[str, Any] = {}
        for k, v in message.items():
            if k == "payload" and isinstance(v, str):
                out[k] = f"<base64 {len(v)} chars>"
            elif k in _SENSITIVE and isinstance(v, str):
                out[k] = ("…" + v[-2:]) if len(v) > 5 else "…"
            else:
                out[k] = sanitize(v)
        return out
    if isinstance(message, list):
        return [sanitize(v) for v in message]
    return message


# --- Session ----------------------------------------------------------------------------------


@dataclass
class CallSession:
    attempt_id: str
    stream_sid: str
    call_sid: str | None
    sender: AudioSender
    inbound: "InboundQueue"
    capture: StreamCapture
    tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    hangup_requested: bool = False
    stop_reason: str | None = None
    mark_events: dict[str, asyncio.Event] = field(default_factory=dict)

    def spawn(self, coro: Any, name: str) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro, name=f"{name}:{self.attempt_id[:8]}")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def close_tasks(self) -> None:
        for task in list(self.tasks):
            task.cancel()
        for task in list(self.tasks):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self.tasks.clear()

    def mark_event(self, name: str) -> asyncio.Event:
        return self.mark_events.setdefault(name, asyncio.Event())


class InboundQueue:
    """Bounded FIFO of inbound audio chunks; overflow drops the oldest."""

    def __init__(self, max_bytes: int, capture: StreamCapture) -> None:
        self._chunks: deque[bytes] = deque()
        self._bytes = 0
        self._max = max_bytes
        self._capture = capture
        self._ready = asyncio.Event()

    def put(self, chunk: bytes) -> None:
        self._chunks.append(chunk)
        self._bytes += len(chunk)
        while self._bytes > self._max and len(self._chunks) > 1:
            old = self._chunks.popleft()
            self._bytes -= len(old)
            self._capture.dropped_inbound_bytes += len(old)
        self._ready.set()

    async def get(self) -> bytes:
        while not self._chunks:
            self._ready.clear()
            await self._ready.wait()
        chunk = self._chunks.popleft()
        self._bytes -= len(chunk)
        return chunk

    def drain(self) -> None:
        self._chunks.clear()
        self._bytes = 0


# --- PoC script -------------------------------------------------------------------------------

INTRO_FULL = (
    "Hello, this is a test call from the recruitment assistant. "
    "If you can hear me clearly, please say something after the beep. "
    "You will hear yourself back about one second later."
)
INTRO_LISTEN = (
    "Hello, this is a test call from the recruitment assistant. "
    "Please say a few words, and then hang up whenever you like."
)
CLEAR_INTRO = "Now a stop test. I will count to ten, but I should stop at about three."
COUNTING = "One. Two. Three. Four. Five. Six. Seven. Eight. Nine. Ten."
GOODBYE = "The test is finished. Thank you, goodbye."
ECHO_SECONDS = 15.0
ECHO_DELAY_S = 1.0
CLEAR_AFTER_S = 2.6  # "one, two, three" takes about this long


def _beep(rate: int, *, hz: float = 880.0, ms: int = 300) -> bytes:
    t = np.arange(int(rate * ms / 1000)) / rate
    tone = (0.3 * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    fade = min(len(tone) // 10, int(rate * 0.01))
    if fade:
        ramp = np.linspace(0, 1, fade, dtype=np.float32)
        tone[:fade] *= ramp
        tone[-fade:] *= ramp[::-1]
    return pcm_utils.float_to_pcm16(tone)


async def _speak(tts: TTSProvider, text: str, settings: Settings, attempt_id: str) -> bytes:
    clip = await tts.synthesize(text, call_attempt_id=attempt_id)
    return ac.to_telephony(
        clip.pcm,
        clip.sample_rate,
        to_rate=settings.telephony_sample_rate,
        encoding=settings.telephony_encoding,
    )


async def _wait_mark(session: CallSession, name: str, timeout: float) -> bool:
    try:
        await asyncio.wait_for(session.mark_event(name).wait(), timeout)
        return True
    except TimeoutError:
        session.capture.note(f"mark {name} not returned within {timeout:.0f}s")
        return False


async def _send_mark(session: CallSession, name: str) -> None:
    session.capture.marks_sent[name] = time.monotonic()
    await session.sender.mark(name)


async def _echo(session: CallSession, seconds: float) -> None:
    """Send the caller's own audio back ECHO_DELAY_S later."""
    session.inbound.drain()
    await asyncio.sleep(ECHO_DELAY_S)
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            chunk = await asyncio.wait_for(session.inbound.get(), timeout=1.0)
        except TimeoutError:
            continue
        # Inbound and outbound use the same configured format: send the bytes back as they are.
        await session.sender.push(chunk)


async def run_poc(
    session: CallSession, mode: str, tts: TTSProvider | None, settings: Settings
) -> None:
    cap = session.capture
    if tts is None or not tts.status().ready:
        cap.note("no TTS available; playing beeps only")
    try:
        say = (
            (lambda text: _speak(tts, text, settings, session.attempt_id))
            if tts is not None and tts.status().ready
            else None
        )
        beep = ac.to_telephony(
            _beep(settings.telephony_sample_rate),
            settings.telephony_sample_rate,
            to_rate=settings.telephony_sample_rate,
            encoding=settings.telephony_encoding,
        )
        await asyncio.sleep(0.3)
        intro = await say(INTRO_FULL if mode == "full" else INTRO_LISTEN) if say else b""
        cap.note(f"intro clip {len(intro)} bytes; playing")
        await session.sender.play(intro + (beep if mode == "full" else b""))
        await _send_mark(session, "intro")
        await _wait_mark(session, "intro", timeout=30)
        if mode == "listen":
            cap.note("listen mode: waiting for the caller to hang up")
            return

        cap.note("echo start")
        await _echo(session, ECHO_SECONDS)
        cap.note("echo end")
        await session.sender.play(b"")
        await asyncio.sleep(session.sender.buffered_s + 0.5)

        if say:
            await session.sender.play(await say(CLEAR_INTRO))
            await _send_mark(session, "clear-intro")
            await _wait_mark(session, "clear-intro", timeout=20)
            counting = await say(COUNTING)
            ms = ac.duration_ms(
                len(counting), settings.telephony_encoding, settings.telephony_sample_rate
            )
            cap.note(f"counting clip {ms:.0f} ms; sending all of it ahead")
            sent_at = time.monotonic()
            # Send far ahead so Exotel holds most of it in its buffer, then clear.
            await session.sender.play(counting, ahead_s=30.0)
            await _send_mark(session, "counting")
            await asyncio.sleep(max(0.0, CLEAR_AFTER_S - (time.monotonic() - sent_at)))
            await session.sender.clear()
            cap.note(f"clear sent {time.monotonic() - sent_at:.2f}s after counting started")
            got = await _wait_mark(session, "counting", timeout=3)
            cap.note(f"counting mark after clear: {'returned' if got else 'not returned'}")
            await asyncio.sleep(1.0)
            await session.sender.play(await say(GOODBYE))
        await _send_mark(session, "bye")
        await _wait_mark(session, "bye", timeout=20)
        cap.note("hanging up from the backend (closing the stream)")
        session.hangup_requested = True
    except TTSError as exc:
        cap.note(f"TTS failed: {exc}")
        session.hangup_requested = True


# --- Stream entry point -----------------------------------------------------------------------


async def _receive_json(ws: WebSocket) -> dict[str, Any]:
    raw = await ws.receive_text()
    message = json.loads(raw)
    return message if isinstance(message, dict) else {"event": "?", "_raw": message}


async def handle_exotel_stream(ws: WebSocket, settings: Settings) -> None:
    await ws.accept()
    capture = StreamCapture()
    tasks_before = len(asyncio.all_tasks())
    try:
        start_msg: dict[str, Any] | None = None
        async with asyncio.timeout(START_TIMEOUT_S):
            while start_msg is None:
                message = await _receive_json(ws)
                capture.record(message, None)
                if message.get("event") == "start":
                    start_msg = message
    except (TimeoutError, WebSocketDisconnect, ValueError) as exc:
        logger.warning("stream_no_start", error=type(exc).__name__)
        with contextlib.suppress(Exception):
            await ws.close(code=1008)
        return

    start = em.parse_stream_start(start_msg)
    if not em.media_format_matches(
        start, encoding=settings.telephony_encoding, sample_rate=settings.telephony_sample_rate
    ):
        logger.error(
            "stream_media_format_mismatch",
            announced_encoding=start.encoding,
            announced_rate=start.sample_rate,
            configured_encoding=settings.telephony_encoding,
            configured_rate=settings.telephony_sample_rate,
        )
        await ws.close(code=1003)
        return

    async with get_sessionmaker()() as db:
        attempt = await call_service.attach_stream(db, start)
    if attempt is None:
        logger.warning("stream_unknown_call", provider_call_id=start.call_sid)
        await ws.close(code=1008)
        return

    attempt_id = str(attempt.id)
    sender = AudioSender(ws, start.stream_sid or "", settings)
    max_inbound = int(
        ac.bytes_per_second(settings.telephony_encoding, settings.telephony_sample_rate)
        * INBOUND_QUEUE_SECONDS
    )
    session = CallSession(
        attempt_id=attempt_id,
        stream_sid=start.stream_sid or "",
        call_sid=start.call_sid,
        sender=sender,
        inbound=InboundQueue(max_inbound, capture),
        capture=capture,
    )
    SESSIONS[attempt_id] = session
    log = logger.bind(call_attempt_id=attempt_id, provider_call_id=start.call_sid)
    log.info(
        "stream_started",
        stream_sid=start.stream_sid,
        encoding=start.encoding,
        sample_rate=start.sample_rate,
        custom_parameters=sorted(start.custom_parameters),
    )

    mode = "full"
    with contextlib.suppress(Exception):
        mode = await get_redis().get(POC_MODE_KEY.format(attempt_id=attempt_id)) or "full"
    tts: TTSProvider | None = getattr(ws.app.state, "tts", None)
    live = None
    if mode == "screen" and tts is not None and tts.status().ready:
        from app.voice.live_screening import LiveScreening

        live = LiveScreening(session, settings, tts)
        script = session.spawn(live.run(), "screen")
    else:
        script = session.spawn(run_poc(session, mode, tts, settings), "poc")

    ended_by = "error"
    receiver: asyncio.Task[Any] | None = None
    try:
        receiver = asyncio.create_task(_receive_loop(ws, session))
        hangup_watch = asyncio.create_task(_wait_hangup(session, script))
        done, _ = await asyncio.wait({receiver, hangup_watch}, return_when=asyncio.FIRST_COMPLETED)
        hangup_watch.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await hangup_watch
        if session.hangup_requested and receiver not in done:
            ended_by = "agent"
            with contextlib.suppress(Exception):
                await ws.close(code=1000)
            receiver.cancel()
        else:
            ended_by = "caller" if session.stop_reason else "error"
            if receiver.done() and receiver.exception():
                log.warning("stream_receive_error", error=repr(receiver.exception()))
            if live is not None and not script.done():
                # Let the conversation end cleanly and store what it collected
                live.caller_hung_up()
                await asyncio.wait({script}, timeout=SAVE_GRACE_S)
    finally:
        if receiver is not None and not receiver.done():
            receiver.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            if receiver is not None:
                await receiver
        await session.close_tasks()
        SESSIONS.pop(attempt_id, None)
        if tts is not None:
            tts.forget_call(attempt_id)
        await asyncio.sleep(0)
        tasks_after = len(asyncio.all_tasks())
        summary = capture.summary() | {
            "ended_by": ended_by,
            "stop_reason": session.stop_reason,
            "frames_sent": sender.frames_sent,
            "bytes_sent": sender.bytes_sent,
            "tasks_before": tasks_before,
            "tasks_after": tasks_after,
            "mode": mode,
        }
        _save_capture(settings, attempt_id, capture, summary)
        log.info(
            "stream_ended",
            **{
                k: summary[k]
                for k in (
                    "ended_by",
                    "stop_reason",
                    "counts",
                    "inbound_bytes_per_second",
                    "media_chunk_sizes",
                    "frames_sent",
                    "mark_latency_s",
                    "tasks_before",
                    "tasks_after",
                    "dropped_inbound_bytes",
                )
            },
        )
        try:
            async with get_sessionmaker()() as db:
                await call_service.stream_ended(
                    db, get_redis(), settings, uuid.UUID(attempt_id), ended_by=ended_by
                )
        except Exception:
            log.exception("stream_end_update_failed")


async def _wait_hangup(session: CallSession, script: asyncio.Task[Any]) -> None:
    """Returns once the script asked to hang up; in listen mode it never does."""
    await asyncio.wait({script})  # doesn't raise the script's errors; does honour cancel
    if not session.hangup_requested:
        await asyncio.Event().wait()  # wait for the caller (cancelled by the stream's end)


async def _receive_loop(ws: WebSocket, session: CallSession) -> None:
    cap = session.capture
    encoding = session.sender.encoding
    while True:
        try:
            message = await _receive_json(ws)
        except WebSocketDisconnect:
            cap.note("websocket closed by Exotel")
            return
        except ValueError:
            cap.note("non-JSON message ignored")
            continue
        kind = message.get("event")
        if kind == "media":
            payload = (message.get("media") or {}).get("payload") or ""
            try:
                chunk = base64.b64decode(payload)
            except ValueError:
                cap.record(message, 0)
                continue
            cap.record(message, len(chunk))
            cap.audio.extend(ac.from_telephony(chunk, encoding=encoding))
            session.inbound.put(chunk)
        elif kind == "mark":
            cap.record(message, None)
            name = str((message.get("mark") or {}).get("name", ""))
            cap.marks_back[name] = time.monotonic()
            cap.note(f"mark {name} returned")
            session.mark_event(name).set()
        elif kind == "stop":
            cap.record(message, None)
            session.stop_reason = str((message.get("stop") or {}).get("reason") or "stop")
            cap.note(f"stop received: {session.stop_reason}")
            return
        else:  # dtmf, clear acks, anything new
            cap.record(message, None)


def _save_capture(
    settings: Settings, attempt_id: str, capture: StreamCapture, summary: dict[str, Any]
) -> None:
    """PoC only, testers' phones only: inbound WAV + message log (gitignored artifacts/)."""
    if not settings.telephony_capture_dir:
        return
    try:
        folder = Path(settings.telephony_capture_dir)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{attempt_id}_in.wav").write_bytes(
            pcm_utils.wav_bytes(bytes(capture.audio), settings.telephony_sample_rate)
        )
        (folder / f"{attempt_id}_stream.json").write_text(
            json.dumps(
                {
                    "summary": summary,
                    "first_shapes": capture.first_shapes,
                    "messages": capture.messages,
                },
                indent=2,
                default=str,
            )
        )
    except OSError:
        logger.exception("stream_capture_save_failed", call_attempt_id=attempt_id)
