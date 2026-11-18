import hashlib

import numpy as np
import pytest

from app.voice import audio_converter as ac
from app.voice import pcm


def _sine(hz: float, rate: int, seconds: float) -> bytes:
    t = np.arange(int(rate * seconds)) / rate
    return pcm.float_to_pcm16((0.5 * np.sin(2 * np.pi * hz * t)).astype(np.float32))


def _dominant_hz(data: bytes, rate: int) -> float:
    x = np.frombuffer(data, dtype="<i2").astype(np.float64)
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1 / rate)[np.argmax(spectrum)])


@pytest.mark.parametrize("to_rate", [8000, 16000, 24000])
def test_resampling_keeps_frequency_and_duration(to_rate: int) -> None:
    src = _sine(1000, 24000, 1.0)
    out = ac.to_telephony(src, 24000, to_rate=to_rate, encoding="slin")
    assert len(out) // 2 == pytest.approx(to_rate, abs=2)  # 1 s of samples
    assert _dominant_hz(out, to_rate) == pytest.approx(1000, abs=2)


def test_resampling_filters_above_nyquist() -> None:
    # 6 kHz can't exist at 8 kHz; it must be filtered out, not folded to 2 kHz.
    out = ac.to_telephony(_sine(6000, 24000, 0.5), 24000, to_rate=8000, encoding="slin")
    rms = np.sqrt(np.mean(np.frombuffer(out, dtype="<i2").astype(np.float64) ** 2))
    assert rms < 0.01 * 32767


def test_mulaw_is_bit_exact_with_g711_reference() -> None:
    every_sample = np.arange(-32768, 32768, dtype="<i2").tobytes()
    # sha256 of CPython audioop.lin2ulaw over the full 16-bit range (Python 3.12)
    expected = "81d633c9e6972a18c74a58720b96cb8ca0bdd096d4060b646dd708c3b846019a"
    assert hashlib.sha256(ac.pcm16_to_mulaw(every_sample)).hexdigest() == expected
    assert ac.pcm16_to_mulaw(np.array([0], dtype="<i2").tobytes()) == b"\xff"


def test_mulaw_round_trip_error_is_bounded() -> None:
    src = _sine(440, 8000, 0.5)
    back = ac.from_telephony(ac.pcm16_to_mulaw(src), encoding="mulaw")
    a = np.frombuffer(src, dtype="<i2").astype(np.float64)
    b = np.frombuffer(back, dtype="<i2").astype(np.float64)
    snr = 10 * np.log10(np.sum(a**2) / np.sum((a - b) ** 2))
    assert snr > 35  # G.711 gives about 38 dB on a loud tone


def test_framer_carries_remainder_and_pads_only_last() -> None:
    framer = ac.Framer(320, encoding="slin")
    out = list(framer.push(b"\x01" * 500))
    assert [len(f) for f in out] == [320]
    assert framer.pending == 180
    out = list(framer.push(b"\x02" * 500))
    assert [len(f) for f in out] == [320, 320]
    assert framer.pending == 40
    (last,) = list(framer.flush())
    assert len(last) == 320 and last.endswith(b"\x00" * 280)
    assert list(framer.flush()) == []


def test_frames_never_exceed_size_and_cover_everything() -> None:
    data = bytes(range(256)) * 50  # 12 800 bytes
    out = ac.frames(data, 3200, encoding="slin")
    assert all(len(f) == 3200 for f in out)
    assert b"".join(out)[: len(data)] == data
    mulaw_tail = ac.frames(b"\x10" * 100, 320, encoding="mulaw")[0]
    assert mulaw_tail.endswith(b"\xff" * 220)  # μ-law silence


def test_framer_rejects_odd_frames_for_16_bit() -> None:
    with pytest.raises(ValueError):
        ac.Framer(321, encoding="slin")


def test_stream_resampler_matches_whole_clip() -> None:
    src = _sine(1000, 24000, 1.0)
    rs = ac.StreamResampler(24000, 8000)
    pieces = [rs.process(src[i : i + 1001]) for i in range(0, len(src), 1001)]  # odd sizes
    out = b"".join(pieces) + rs.flush()
    assert abs(len(out) // 2 - 8000) <= 2
    assert _dominant_hz(out, 8000) == pytest.approx(1000, abs=2)


def test_durations() -> None:
    assert ac.duration_ms(3200, "slin", 8000) == 200
    assert ac.duration_ms(3200, "slin", 16000) == 100
    assert ac.duration_ms(160, "mulaw", 8000) == 20
