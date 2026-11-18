"""Telephony audio conversion: pure functions, no I/O (phase-05 P5-T8).

Inside the app, audio is mono 16-bit little-endian PCM at the TTS rate. On the phone side it is
whatever `TELEPHONY_ENCODING` / `TELEPHONY_SAMPLE_RATE` say (verified on a real call, see
docs/telephony.md). Rates and frame sizes are always passed in; nothing here hardcodes them.

μ-law is a NumPy G.711 implementation, because `audioop` is removed in Python 3.13.
"""

from collections.abc import Iterator
from typing import Literal

import numpy as np
import numpy.typing as npt
import soxr

from app.voice import pcm as pcm_utils

Encoding = Literal["slin", "mulaw"]

_MULAW_BIAS = 0x84  # decoder bias (16-bit domain)
_MULAW_BIAS_14 = 0x21  # encoder bias (14-bit domain)
_MULAW_CLIP_14 = 8159
_MULAW_SEG_END = np.array([0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF])


def bytes_per_sample(encoding: Encoding) -> int:
    return 2 if encoding == "slin" else 1


def bytes_per_second(encoding: Encoding, sample_rate: int) -> int:
    return bytes_per_sample(encoding) * sample_rate


def duration_ms(n_bytes: int, encoding: Encoding, sample_rate: int) -> float:
    return n_bytes * 1000.0 / bytes_per_second(encoding, sample_rate)


# --- G.711 μ-law -----------------------------------------------------------------------------


def _encode_mulaw_array(samples: npt.NDArray[np.int16]) -> npt.NDArray[np.uint8]:
    """G.711 μ-law, bit-exact with the classic Sun reference (and CPython's old audioop)."""
    v = samples.astype(np.int32) >> 2  # 14-bit, arithmetic shift
    mask = np.where(v < 0, 0x7F, 0xFF)
    v = np.minimum(np.abs(v), _MULAW_CLIP_14) + _MULAW_BIAS_14
    segment = np.searchsorted(_MULAW_SEG_END, v)  # first segment whose end >= v
    mantissa = (v >> (segment + 1)) & 0x0F
    encoded = np.where(segment >= 8, 0x7F, (segment << 4) | mantissa) ^ mask
    return encoded.astype(np.uint8)


def _build_decode_table() -> npt.NDArray[np.int16]:
    codes = np.arange(256, dtype=np.int32)
    u = ~codes & 0xFF
    sign = u & 0x80
    exponent = (u >> 4) & 0x07
    mantissa = u & 0x0F
    magnitude = (((mantissa << 3) + _MULAW_BIAS) << exponent) - _MULAW_BIAS
    return np.where(sign != 0, -magnitude, magnitude).astype(np.int16)


_MULAW_DECODE = _build_decode_table()


def pcm16_to_mulaw(pcm: bytes) -> bytes:
    return _encode_mulaw_array(np.frombuffer(pcm, dtype="<i2")).tobytes()


def mulaw_to_pcm16(data: bytes) -> bytes:
    return _MULAW_DECODE[np.frombuffer(data, dtype=np.uint8)].astype("<i2").tobytes()


# --- Conversion both ways --------------------------------------------------------------------


def to_telephony(pcm: bytes, from_rate: int, *, to_rate: int, encoding: Encoding) -> bytes:
    """App PCM (16-bit, `from_rate`) → phone-side bytes. Resampling uses soxr's anti-aliasing."""
    if len(pcm) % 2:
        raise ValueError("16-bit PCM must have an even number of bytes")
    out = pcm
    if from_rate != to_rate:
        out = pcm_utils.float_to_pcm16(
            pcm_utils.resample(pcm_utils.pcm16_to_float(pcm), from_rate, to_rate)
        )
    return pcm16_to_mulaw(out) if encoding == "mulaw" else out


def from_telephony(data: bytes, *, encoding: Encoding) -> bytes:
    """Phone-side bytes → 16-bit PCM at the same rate."""
    return mulaw_to_pcm16(data) if encoding == "mulaw" else data


class StreamResampler:
    """Chunk-by-chunk resampling for streamed TTS, without clicks at chunk borders.

    soxr's stream API keeps filter state between chunks; `flush()` returns the tail.
    """

    def __init__(self, from_rate: int, to_rate: int) -> None:
        self._passthrough = from_rate == to_rate
        self._odd = b""
        self._rs = (
            None
            if self._passthrough
            else soxr.ResampleStream(from_rate, to_rate, 1, dtype="float32", quality="HQ")
        )

    def process(self, pcm: bytes, *, last: bool = False) -> bytes:
        data = self._odd + pcm
        cut = len(data) - len(data) % 2
        self._odd, data = data[cut:], data[:cut]
        if self._rs is None:
            return data
        audio = pcm_utils.pcm16_to_float(data)
        out = self._rs.resample_chunk(audio, last=last)
        return pcm_utils.float_to_pcm16(np.asarray(out, dtype=np.float32))

    def flush(self) -> bytes:
        return self.process(b"", last=True)


# --- Framing ---------------------------------------------------------------------------------


class Framer:
    """Cuts a byte stream into frames of exactly `frame_bytes`, carrying the remainder over.

    Only the final frame (from `flush`) is padded, with silence of the right encoding.
    """

    def __init__(self, frame_bytes: int, *, encoding: Encoding) -> None:
        if frame_bytes <= 0 or frame_bytes % bytes_per_sample(encoding):
            raise ValueError("frame size must be a positive whole number of samples")
        self.frame_bytes = frame_bytes
        self._silence = b"\x00" if encoding == "slin" else b"\xff"  # μ-law 0xFF = zero
        self._buffer = bytearray()

    @property
    def pending(self) -> int:
        return len(self._buffer)

    def push(self, data: bytes) -> Iterator[bytes]:
        self._buffer.extend(data)
        while len(self._buffer) >= self.frame_bytes:
            frame = bytes(self._buffer[: self.frame_bytes])
            del self._buffer[: self.frame_bytes]
            yield frame

    def flush(self, *, pad: bool = True) -> Iterator[bytes]:
        if not self._buffer:
            return
        rest = bytes(self._buffer)
        self._buffer.clear()
        if pad:
            rest += self._silence * (self.frame_bytes - len(rest))
        yield rest

    def reset(self) -> None:
        self._buffer.clear()


def frames(data: bytes, frame_bytes: int, *, encoding: Encoding) -> list[bytes]:
    """Whole clip → frames, last one padded."""
    framer = Framer(frame_bytes, encoding=encoding)
    return [*framer.push(data), *framer.flush()]
