"""Deepgram streaming transcription behind `STTProvider` (P4-T2, T4, T5, T6).

Protocol (checked against the live API on 2026-11-18, docs/benchmarks/stt.md):
- `wss://api.deepgram.com/v1/listen?...`, header `Authorization: Token <key>`; raw audio frames
  go up, JSON messages come down: `Results` (`is_final`, `speech_final`,
  `channel.alternatives[0].transcript/confidence`, `start`, `duration`), `UtteranceEnd`
  (`last_word_end`), `SpeechStarted` (`timestamp`), `Metadata`, `Error`.
- Client control messages: `KeepAlive` (sent while no audio flows; Deepgram closes an idle
  stream after about 10 s), `Finalize` (flush now), `CloseStream` (flush, then the server closes).
- A plain `websockets` client rather than Deepgram's SDK: the surface is small and the SDK's
  major versions have changed their APIs.

Error handling (plan P4-T6):
- Connect: 3 s timeout, up to 3 attempts with backoff. 401/403/400 → STTConfigError at once.
- Mid-stream disconnect: reconnect and resume. Audio is buffered meanwhile in a bounded queue
  (2 s; the oldest audio is dropped and logged). Timestamps stay continuous across connections.
- No working stream for more than 5 s: an `error` event, then `closed`. The session apologizes
  and ends (P6).
- Empty finals are passed on; `UtteranceAssembler` ignores them.
"""

import asyncio
import contextlib
import json
import time
from bisect import bisect_left
from collections import deque
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus

from app.providers.stt.base import (
    STTConfigError,
    STTConnectionError,
    STTProvider,
    STTStats,
    TranscriptEvent,
)
from app.utils.log import get_logger

logger = get_logger(__name__)

DEEPGRAM_LISTEN_URL = "wss://api.deepgram.com/v1/listen"
DEFAULT_MODEL = "nova-3"
DEFAULT_LANGUAGE = "en-IN"
BYTES_PER_SAMPLE = {"linear16": 2, "mulaw": 1, "alaw": 1}
MAX_MARKS = 15_000  # send_audio() timing marks kept for sent_at() (5 min of 20 ms chunks)


class DeepgramSTTProvider(STTProvider):
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        language: str = DEFAULT_LANGUAGE,
        endpointing_ms: int = 300,
        utterance_end_ms: int = 1000,
        keyterms: Sequence[str] = (),
        smart_format: bool = False,
        url: str = DEEPGRAM_LISTEN_URL,
        connect_timeout_s: float = 3.0,
        connect_attempts: int = 3,
        backoff_s: float = 0.25,
        reconnect_window_s: float = 5.0,
        buffer_s: float = 2.0,
        keepalive_interval_s: float = 4.0,
        close_timeout_s: float = 2.0,
    ) -> None:
        self.model = model
        self.language = language
        self.endpointing_ms = endpointing_ms
        self.utterance_end_ms = utterance_end_ms
        self.keyterms = list(keyterms)
        self.smart_format = smart_format
        self.connect_timeout_s = connect_timeout_s
        self.connect_attempts = max(1, connect_attempts)
        self.backoff_s = backoff_s
        self.reconnect_window_s = reconnect_window_s
        self.buffer_s = buffer_s
        self.keepalive_interval_s = keepalive_interval_s
        self.close_timeout_s = close_timeout_s
        self._api_key = api_key
        self._url = url
        # Called with every raw server message (tools record fixtures with it)
        self.on_message: Callable[[dict[str, Any]], None] | None = None

        self.session_id = ""
        self.stats = STTStats()
        self._log: Any = logger
        self._bytes_per_s = 0
        self._ws: ClientConnection | None = None
        self._supervisor: asyncio.Task[None] | None = None
        self._events: asyncio.Queue[TranscriptEvent] = asyncio.Queue()
        self._closed_event: TranscriptEvent | None = None
        self._closing = False
        self._started = False
        # Audio waiting to be sent: (session position in seconds, bytes)
        self._buffer: deque[tuple[float, bytes]] = deque()
        self._buffered_bytes = 0
        self._audio_ready = asyncio.Event()
        self._queued_s = 0.0  # session audio handed to send_audio() so far
        self._offset_s = 0.0  # session position of the current connection's first audio
        self._conn_sent_s = 0.0  # audio sent on the current connection
        self._conn_messages = 0  # server messages on the current connection
        self._mark_ends: list[float] = []  # session position at the end of each chunk
        self._mark_times: list[float] = []  # monotonic time that chunk was handed over

    # --- public interface --------------------------------------------------------------------

    async def start_stream(
        self,
        *,
        session_id: str,
        encoding: str,
        sample_rate: int,
        channels: int = 1,
        keyterms: Sequence[str] = (),
    ) -> None:
        if self._started:
            raise RuntimeError("start_stream() was already called; use one provider per session")
        if encoding not in BYTES_PER_SAMPLE:
            raise STTConfigError(f"unsupported encoding {encoding!r}")
        self._started = True
        self.session_id = session_id
        self._log = logger.bind(session_id=session_id)
        self._bytes_per_s = BYTES_PER_SAMPLE[encoding] * sample_rate * channels
        self._query = self._build_query(
            encoding, sample_rate, channels, [*self.keyterms, *keyterms]
        )
        ws = await self._connect(deadline=None)
        self._supervisor = asyncio.create_task(self._run(ws), name=f"stt-{session_id}")

    async def send_audio(self, audio_chunk: bytes) -> None:
        if not audio_chunk or self._closing or self._closed_event is not None:
            return
        if not self._started:
            raise RuntimeError("call start_stream() first")
        duration = len(audio_chunk) / self._bytes_per_s
        self._buffer.append((self._queued_s, audio_chunk))
        self._buffered_bytes += len(audio_chunk)
        self._queued_s += duration
        self._mark_ends.append(self._queued_s)
        self._mark_times.append(time.monotonic())
        if len(self._mark_ends) > MAX_MARKS:
            del self._mark_ends[: MAX_MARKS // 10], self._mark_times[: MAX_MARKS // 10]
        self._trim_buffer()
        self._audio_ready.set()

    async def get_transcription(self) -> TranscriptEvent:
        if self._closed_event is not None and self._events.empty():
            return self._closed_event
        return await self._events.get()

    def sent_at(self, audio_s: float) -> float | None:
        i = bisect_left(self._mark_ends, audio_s)
        if i >= len(self._mark_ends):
            return None
        # the chunk ending at mark_ends[i] arrived at mark_times[i]; audio_s is inside it
        return self._mark_times[i] - (self._mark_ends[i] - audio_s)

    async def finalize(self) -> None:
        """Ask Deepgram to finalize what it has heard so far (e.g. when a local VAD decides the
        turn ended before Deepgram's endpointing does)."""
        if self._ws is not None:
            with contextlib.suppress(ConnectionClosed):
                await self._ws.send(json.dumps({"type": "Finalize"}))

    async def close(self) -> None:
        if not self._started or self._closing:
            if self._supervisor is not None:
                await asyncio.wait({self._supervisor}, timeout=self.close_timeout_s + 1)
            self._finish()
            return
        self._closing = True
        self._audio_ready.set()
        if self._supervisor is not None:
            done, _ = await asyncio.wait({self._supervisor}, timeout=self.close_timeout_s + 1)
            if not done:
                self._supervisor.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._supervisor
        self._finish()

    def simulate_network_drop(self) -> None:
        """Tests only: kill the socket without a closing handshake, as a network failure would."""
        if self._ws is not None:
            self._ws.transport.abort()

    # --- connection --------------------------------------------------------------------------

    def _build_query(
        self, encoding: str, sample_rate: int, channels: int, keyterms: list[str]
    ) -> str:
        params: list[tuple[str, str]] = [
            ("model", self.model),
            ("language", self.language),
            ("encoding", encoding),
            ("sample_rate", str(sample_rate)),
            ("channels", str(channels)),
            ("interim_results", "true"),
            ("endpointing", str(self.endpointing_ms)),
            ("utterance_end_ms", str(self.utterance_end_ms)),
            ("vad_events", "true"),
            ("punctuate", "true"),
            ("smart_format", "true" if self.smart_format else "false"),
        ]
        terms = list(dict.fromkeys(t.strip() for t in keyterms if t.strip()))
        if self.model.startswith("nova-3"):
            params += [("keyterm", t) for t in terms]
        else:  # Nova-2 and older use keyword boosting
            params += [("keywords", f"{t}:2") for t in terms]
        return urlencode(params)

    async def _connect(self, *, deadline: float | None) -> ClientConnection:
        """Up to `connect_attempts` attempts (or until `deadline` when reconnecting)."""
        attempt = 0
        last: str = "no attempt"
        while True:
            attempt += 1
            timeout = self.connect_timeout_s
            if deadline is not None:
                timeout = min(timeout, deadline - time.monotonic())
                if timeout <= 0 or self._closing:
                    break
            elif attempt > self.connect_attempts:
                break
            started = time.monotonic()
            try:
                ws = await connect(
                    f"{self._url}?{self._query}",
                    additional_headers={"Authorization": f"Token {self._api_key}"},
                    open_timeout=timeout,
                    max_size=2**20,
                )
            except InvalidStatus as exc:
                status = exc.response.status_code
                if status in (401, 403):
                    raise STTConfigError(f"Deepgram rejected the API key ({status})") from None
                if status == 400:
                    reason = exc.response.headers.get("dg-error") or exc.response.body or b""
                    text = reason.decode(errors="replace") if isinstance(reason, bytes) else reason
                    raise STTConfigError(f"Deepgram refused the parameters: {text[:200]}") from None
                last = f"HTTP {status}"
            except (OSError, TimeoutError, InvalidHandshake) as exc:
                last = type(exc).__name__
            else:
                self.stats.connects += 1
                request_id = ws.response.headers.get("dg-request-id") if ws.response else None
                if request_id:
                    self.stats.request_ids.append(request_id)
                self._log.info(
                    "stt_connected",
                    provider="deepgram",
                    model=self.model,
                    language=self.language,
                    attempt=attempt,
                    connect_ms=int((time.monotonic() - started) * 1000),
                    request_id=request_id,
                )
                return ws
            self._log.warning(
                "stt_connect_failed", provider="deepgram", attempt=attempt, error=last
            )
            pause = self.backoff_s * 2 ** (attempt - 1)
            if deadline is not None:
                pause = min(pause, max(0.0, deadline - time.monotonic()))
            await asyncio.sleep(pause)
        raise STTConnectionError(f"could not connect to Deepgram ({last})")

    async def _run(self, ws: ClientConnection) -> None:
        """Owns the connection: serve it, reconnect after a drop, emit `closed` at the end."""
        down_since: float | None = None  # when the stream last stopped working
        try:
            while True:
                self._ws = ws
                self._offset_s = self._buffer[0][0] if self._buffer else self._queued_s
                self._conn_sent_s = 0.0
                self._conn_messages = 0
                opened = time.monotonic()
                await self._serve(ws)
                self._ws = None
                if self._closing:
                    return
                # A connection that dies at once without a word doesn't count as working, so a
                # flapping stream still hits the reconnect window.
                if down_since is None or self._conn_messages or time.monotonic() - opened >= 1.0:
                    down_since = time.monotonic()
                self.stats.reconnects += 1
                self._log.warning(
                    "stt_disconnected",
                    provider="deepgram",
                    close_code=ws.close_code,
                    close_reason=ws.close_reason,
                )
                try:
                    ws = await self._connect(deadline=down_since + self.reconnect_window_s)
                except STTConnectionError as exc:
                    self._emit("error", detail=f"transcription stream lost: {exc}")
                    return
                except STTConfigError as exc:
                    self._emit("error", detail=str(exc))
                    return
                if self._closing:
                    await ws.close()
                    return
        except Exception as exc:  # never let the session die silently
            self._log.exception("stt_supervisor_failed", provider="deepgram")
            self._emit("error", detail=f"{type(exc).__name__}: {exc}")
        finally:
            self._ws = None
            self._finish()

    async def _serve(self, ws: ClientConnection) -> None:
        reader = asyncio.create_task(self._read(ws))
        sender = asyncio.create_task(self._send(ws))
        try:
            done, _ = await asyncio.wait({reader, sender}, return_when=asyncio.FIRST_COMPLETED)
            if sender in done and not sender.exception() and self._closing:
                # CloseStream was sent: wait for the last results, then Deepgram closes.
                await asyncio.wait({reader}, timeout=self.close_timeout_s)
        finally:
            for task in (reader, sender):
                task.cancel()
            await asyncio.gather(reader, sender, return_exceptions=True)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(ws.close(), timeout=1)

    async def _send(self, ws: ClientConnection) -> None:
        while True:
            if self._buffer:
                position, chunk = self._buffer.popleft()
                self._buffered_bytes -= len(chunk)
                try:
                    await ws.send(chunk)
                except ConnectionClosed:
                    self._buffer.appendleft((position, chunk))  # resend after reconnecting
                    self._buffered_bytes += len(chunk)
                    raise
                self._conn_sent_s += len(chunk) / self._bytes_per_s
                self.stats.audio_s_sent += len(chunk) / self._bytes_per_s
                continue
            if self._closing:
                await ws.send(json.dumps({"type": "CloseStream"}))
                return
            self._audio_ready.clear()
            try:
                await asyncio.wait_for(self._audio_ready.wait(), timeout=self.keepalive_interval_s)
            except TimeoutError:
                await ws.send(json.dumps({"type": "KeepAlive"}))

    async def _read(self, ws: ClientConnection) -> None:
        with contextlib.suppress(ConnectionClosed):
            async for message in ws:
                if isinstance(message, str):
                    msg = json.loads(message)
                    self._conn_messages += 1
                    if self.on_message is not None:
                        self.on_message(msg)
                    self._handle(msg)

    def _trim_buffer(self) -> None:
        limit = int(self.buffer_s * self._bytes_per_s)
        dropped = 0
        while self._buffered_bytes > limit and len(self._buffer) > 1:
            _, chunk = self._buffer.popleft()
            self._buffered_bytes -= len(chunk)
            dropped += len(chunk)
        if dropped:
            self.stats.dropped_audio_s += dropped / self._bytes_per_s
            self._log.warning(
                "stt_audio_dropped",
                provider="deepgram",
                dropped_ms=int(dropped / self._bytes_per_s * 1000),
                total_dropped_ms=int(self.stats.dropped_audio_s * 1000),
            )

    # --- messages ----------------------------------------------------------------------------

    def _handle(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        offset = self._offset_s
        if kind == "Results":
            alternatives = (msg.get("channel") or {}).get("alternatives") or [{}]
            best = alternatives[0]
            text = (best.get("transcript") or "").strip()
            final = bool(msg.get("is_final"))
            if not final and not text:
                return
            # Word timings when there are words: the segment itself runs on into the silence
            # after them, and end-of-speech latency is measured from the last word.
            words = best.get("words") or []
            start = float(msg.get("start") or 0.0)
            end = start + float(msg.get("duration") or 0.0)
            if words:
                start, end = float(words[0]["start"]), float(words[-1]["end"])
            self._emit(
                "final" if final else "partial",
                text=text,
                confidence=best.get("confidence"),
                start_s=start + offset,
                end_s=end + offset,
                # speech_final: Deepgram's endpointing; from_finalize: we asked (finalize())
                endpoint=bool(msg.get("speech_final") or (final and msg.get("from_finalize"))),
            )
        elif kind == "UtteranceEnd":
            last = msg.get("last_word_end")
            self._emit("utterance_end", end_s=None if last is None else float(last) + offset)
        elif kind == "SpeechStarted":
            self._emit("speech_started", start_s=float(msg.get("timestamp") or 0.0) + offset)
        elif kind == "Error":
            # Non-fatal (e.g. a malformed control message); fatal errors close the socket.
            self._log.warning(
                "stt_provider_error",
                provider="deepgram",
                variant=msg.get("variant"),
                description=msg.get("description"),
            )
        elif kind == "Metadata":
            self._log.debug("stt_metadata", request_id=msg.get("request_id"))

    def _emit(self, kind: Any, **fields: Any) -> None:
        if self._closed_event is not None:
            return
        event = TranscriptEvent(
            session_id=self.session_id, kind=kind, received_at=time.monotonic(), **fields
        )
        if kind == "error":
            self._log.error("stt_error", provider="deepgram", detail=event.detail)
        self._events.put_nowait(event)

    def _finish(self) -> None:
        if self._closed_event is not None:
            return
        if self._buffer:
            self._log.info(
                "stt_unsent_audio", unsent_ms=int(self._buffered_bytes / self._bytes_per_s * 1000)
            )
            self._buffer.clear()
            self._buffered_bytes = 0
        self._emit("closed")
        self._closed_event = TranscriptEvent(
            session_id=self.session_id, kind="closed", received_at=time.monotonic()
        )
        self._log.info(
            "stt_closed",
            provider="deepgram",
            audio_s=round(self.stats.audio_s_sent, 2),
            reconnects=self.stats.reconnects,
            dropped_ms=int(self.stats.dropped_audio_s * 1000),
        )
