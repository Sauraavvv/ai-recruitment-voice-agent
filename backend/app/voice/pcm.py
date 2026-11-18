"""PCM helpers shared by TTS providers and the audio tools.

All functions work on mono float32 arrays in [-1, 1] or int16 PCM bytes, and do no I/O.
"""

import io
import wave

import numpy as np
import numpy.typing as npt
import soxr

FloatAudio = npt.NDArray[np.float32]

# Silence trimming: anything quieter than this (relative to full scale) counts as silence.
SILENCE_THRESHOLD_DBFS = -45.0
TRIM_PADDING_MS = 50
TARGET_PEAK_DBFS = -3.0


def _db_to_amplitude(db: float) -> float:
    return float(10 ** (db / 20))


def as_mono_float(samples: npt.ArrayLike) -> FloatAudio:
    """Flatten model output (often shaped [1, N]) to a 1-D float32 array, dropping NaN/inf."""
    audio = np.asarray(samples, dtype=np.float32).reshape(-1)
    return np.nan_to_num(audio, nan=0.0, posinf=1.0, neginf=-1.0)


def trim_silence(
    audio: FloatAudio,
    sample_rate: int,
    *,
    threshold_dbfs: float = SILENCE_THRESHOLD_DBFS,
    padding_ms: int = TRIM_PADDING_MS,
) -> FloatAudio:
    """Cut leading and trailing silence, keeping `padding_ms` either side. All-silent → empty."""
    if audio.size == 0:
        return audio
    loud = np.flatnonzero(np.abs(audio) > _db_to_amplitude(threshold_dbfs))
    if loud.size == 0:
        return audio[:0]
    pad = sample_rate * padding_ms // 1000
    start = max(0, int(loud[0]) - pad)
    end = min(audio.size, int(loud[-1]) + 1 + pad)
    return audio[start:end]


def normalize_peak(audio: FloatAudio, *, target_dbfs: float = TARGET_PEAK_DBFS) -> FloatAudio:
    """Scale so the loudest sample sits at `target_dbfs`. Silence is returned unchanged."""
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak < 1e-6:
        return audio
    return (audio * (_db_to_amplitude(target_dbfs) / peak)).astype(np.float32)


def gain_soft_limited(
    audio: FloatAudio, gain_db: float, *, ceiling_dbfs: float = -1.0
) -> FloatAudio:
    """Raise loudness by `gain_db`, rounding off peaks smoothly below `ceiling_dbfs`.

    c·tanh(g·x/c) is linear for quiet samples and never exceeds the ceiling. It is stateless,
    so it can run chunk by chunk on a stream.
    """
    if gain_db == 0 or audio.size == 0:
        return audio
    c = _db_to_amplitude(ceiling_dbfs)
    out: FloatAudio = (c * np.tanh(audio * _db_to_amplitude(gain_db) / c)).astype(np.float32)
    return out


def float_to_pcm16(audio: FloatAudio) -> bytes:
    """float32 [-1, 1] → signed 16-bit little-endian bytes, clipping anything out of range."""
    clipped = np.clip(audio, -1.0, 1.0)
    return (np.round(clipped * 32767.0)).astype("<i2").tobytes()


def pcm16_to_float(pcm: bytes) -> FloatAudio:
    return (np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32767.0).astype(np.float32)


def resample(audio: FloatAudio, from_rate: int, to_rate: int) -> FloatAudio:
    """High-quality resampling (libsoxr, with its anti-aliasing filter)."""
    if from_rate == to_rate or audio.size == 0:
        return audio
    out: FloatAudio = np.asarray(
        soxr.resample(audio, from_rate, to_rate, quality="HQ"), dtype=np.float32
    )
    return out


def mulaw_round_trip(audio: FloatAudio) -> FloatAudio:
    """Encode to 8-bit μ-law and decode again, to hear what G.711 does to the audio.

    This is a listening aid. The real telephony codec and framing are Phase 5's audio_converter.
    """
    mu = 255.0
    x = np.clip(audio, -1.0, 1.0)
    encoded = np.round(np.sign(x) * np.log1p(mu * np.abs(x)) / np.log1p(mu) * 127.0) / 127.0
    decoded: FloatAudio = (np.sign(encoded) * np.expm1(np.abs(encoded) * np.log1p(mu)) / mu).astype(
        np.float32
    )
    return decoded


def phone_band(pcm: bytes, sample_rate: int) -> bytes:
    """What a candidate hears: downsample to 8 kHz, round-trip through μ-law. Returns 8 kHz PCM."""
    audio = resample(pcm16_to_float(pcm), sample_rate, 8000)
    return float_to_pcm16(mulaw_round_trip(audio))


def wav_bytes(pcm: bytes, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()
