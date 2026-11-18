"""PCM helpers: float → int16, silence trimming, peak normalization, phone band."""

import io
import wave

import numpy as np

from app.providers.tts.base import AudioClip
from app.voice import pcm

SR = 24000


def tone(seconds: float, amplitude: float = 0.5, sr: int = SR) -> np.ndarray:
    t = np.arange(int(sr * seconds)) / sr
    return (amplitude * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def test_float_to_pcm16_scales_and_clips() -> None:
    samples = np.array([0.0, 0.5, -0.5, 1.0, -1.0, 1.7, -3.0], dtype=np.float32)
    out = np.frombuffer(pcm.float_to_pcm16(samples), dtype="<i2")
    assert out.tolist() == [0, 16384, -16384, 32767, -32767, 32767, -32767]


def test_float_to_pcm16_length() -> None:
    assert len(pcm.float_to_pcm16(np.zeros(1234, dtype=np.float32))) == 2468


def test_as_mono_float_flattens_and_cleans() -> None:
    out = pcm.as_mono_float(np.array([[0.1, np.nan, np.inf, -np.inf]]))
    assert out.shape == (4,)
    assert out.dtype == np.float32
    assert out.tolist() == [np.float32(0.1), 0.0, 1.0, -1.0]


def test_trim_silence_keeps_padding() -> None:
    silence = np.zeros(SR, dtype=np.float32)  # 1 s either side
    audio = np.concatenate([silence, tone(0.5), silence])
    trimmed = pcm.trim_silence(audio, SR, padding_ms=50)
    expected = int(SR * 0.5) + 2 * int(SR * 0.05)
    assert abs(trimmed.size - expected) <= 2


def test_trim_silence_all_silent_is_empty() -> None:
    assert pcm.trim_silence(np.zeros(SR, dtype=np.float32), SR).size == 0
    assert pcm.trim_silence(np.zeros(0, dtype=np.float32), SR).size == 0


def test_normalize_peak_to_minus_3_dbfs() -> None:
    out = pcm.normalize_peak(tone(0.2, amplitude=0.1))
    assert abs(float(np.max(np.abs(out))) - 10 ** (-3 / 20)) < 1e-3


def test_normalize_peak_leaves_silence_alone() -> None:
    silence = np.zeros(100, dtype=np.float32)
    assert np.array_equal(pcm.normalize_peak(silence), silence)


def test_phone_band_is_8khz_and_keeps_duration() -> None:
    wide = pcm.float_to_pcm16(tone(1.0))
    narrow = pcm.phone_band(wide, SR)
    assert abs(len(narrow) // 2 - 8000) <= 2
    # μ-law keeps the tone recognisable: correlation with a clean 8 kHz version stays high
    clean = pcm.resample(pcm.pcm16_to_float(wide), SR, 8000)
    got = pcm.pcm16_to_float(narrow)[: clean.size]
    assert float(np.corrcoef(clean[: got.size], got)[0, 1]) > 0.99


def test_wav_bytes_header() -> None:
    data = pcm.wav_bytes(b"\x00\x00" * 240, SR)
    with wave.open(io.BytesIO(data)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (
            1,
            2,
            SR,
            240,
        )


def test_audio_clip_duration() -> None:
    clip = AudioClip.from_pcm(b"\x00\x00" * SR, SR)
    assert clip.duration_ms == 1000
    assert not clip.is_empty
    assert AudioClip.from_pcm(b"", SR).is_empty
