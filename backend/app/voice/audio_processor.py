"""Inbound phone audio: decode, buffer, frame (phase-06 P6-T1).

Exotel sends base64 linear16 at 8 kHz in 320-byte (20 ms) chunks (docs/telephony.md). The VAD
needs exact 20 ms frames, so `InboundFramer` re-frames whatever arrives; Deepgram takes the same
bytes as they are.
"""

import asyncio
import base64
import binascii
from collections import deque

from app.voice import audio_converter as ac

FRAME_MS = 20


def decode_media(payload: str, *, encoding: ac.Encoding) -> bytes:
    """Base64 media payload → linear16 PCM. Raises ValueError on bad base64."""
    try:
        raw = base64.b64decode(payload, validate=False)
    except binascii.Error as exc:
        raise ValueError("bad base64 payload") from exc
    return ac.from_telephony(raw, encoding=encoding)


def frame_bytes(sample_rate: int, frame_ms: int = FRAME_MS) -> int:
    return sample_rate * frame_ms // 1000 * 2  # linear16 mono


class InboundFramer:
    """Splits linear16 audio into fixed frames, carrying the remainder to the next push."""

    def __init__(self, sample_rate: int, frame_ms: int = FRAME_MS) -> None:
        self.size = frame_bytes(sample_rate, frame_ms)
        self._carry = b""

    def push(self, audio: bytes) -> list[bytes]:
        data = self._carry + audio
        cut = len(data) - len(data) % self.size
        self._carry = data[cut:]
        return [data[i : i + self.size] for i in range(0, cut, self.size)]


class InboundQueue:
    """Bounded FIFO of inbound audio chunks; overflow drops the oldest (counted)."""

    def __init__(self, max_bytes: int) -> None:
        self._chunks: deque[bytes] = deque()
        self._bytes = 0
        self._max = max_bytes
        self._ready = asyncio.Event()
        self._closed = False
        self.dropped_bytes = 0

    def put(self, chunk: bytes) -> None:
        if self._closed:
            return
        self._chunks.append(chunk)
        self._bytes += len(chunk)
        while self._bytes > self._max and len(self._chunks) > 1:
            old = self._chunks.popleft()
            self._bytes -= len(old)
            self.dropped_bytes += len(old)
        self._ready.set()

    def close(self) -> None:
        """No more audio: `get()` raises EOFError once the queue is empty."""
        self._closed = True
        self._ready.set()

    async def get(self) -> bytes:
        while not self._chunks:
            if self._closed:
                raise EOFError
            self._ready.clear()
            await self._ready.wait()
        chunk = self._chunks.popleft()
        self._bytes -= len(chunk)
        return chunk

    def drain(self) -> None:
        self._chunks.clear()
        self._bytes = 0
