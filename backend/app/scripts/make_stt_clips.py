"""Generate the synthetic STT test set with macOS `say` (plan P4-T8). Runs on the Mac host:

    make stt-clips            # = cd backend && .venv/bin/python -m app.scripts.make_stt_clips

Voices: the three Indian-English system voices (Rishi, Tara, Aman). Each line of
tests/fixtures/stt_clips.yaml is spoken by each voice at 16 kHz; lines with `noise` also get
background-noise versions (fan = pink noise at 12 dB SNR, traffic = rumbling brown noise at
10 dB, tv = another voice talking at 8 dB). The silence clip is 10 s of a faint noise floor.

Synthetic voices are cleaner and more regular than people, so treat these numbers as a lower
bound on the error rate. Real recordings go through app/scripts/stt_record.py.
"""

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

from app.scripts.stt_tools import AUDIO_ROOT, load_specs, say
from app.voice import pcm
from app.voice.pcm import FloatAudio

RATE = 16000
VOICES = ("Rishi", "Tara", "Aman")
TV_VOICE = "Samantha"
TV_TEXT = (
    "And in tonight's match the home side needed forty runs from the last three overs. "
    "The weather tomorrow will be partly cloudy with a chance of rain in the evening. "
)
LEAD_IN_S = 0.3


def rms(audio: FloatAudio) -> float:
    active = audio[np.abs(audio) > 0.01]
    return float(np.sqrt(np.mean(active**2))) if active.size else 1e-4


def colored_noise(n: int, exponent: float, rng: np.random.Generator) -> FloatAudio:
    """1/f^exponent noise (1 = pink, 2 = brown), unit RMS."""
    spectrum = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n, 1 / RATE)
    freqs[0] = freqs[1]
    noise = np.fft.irfft(spectrum / freqs ** (exponent / 2), n)
    out: FloatAudio = (noise / np.sqrt(np.mean(noise**2))).astype(np.float32)
    return out


def mix(speech: FloatAudio, noise: FloatAudio, snr_db: float) -> FloatAudio:
    noise = np.resize(noise, speech.size)
    noise = noise / max(rms(noise), 1e-6) * rms(speech) / 10 ** (snr_db / 20)
    out = speech + noise
    return (out / max(1.0, float(np.abs(out).max()) / 0.95)).astype(np.float32)


def make_noise(kind: str, n: int, rng: np.random.Generator, tmp: Path) -> tuple[FloatAudio, float]:
    if kind == "fan":
        return colored_noise(n, 1.0, rng), 12.0
    if kind == "traffic":
        rumble = colored_noise(n, 2.0, rng)
        swell = 0.6 + 0.4 * np.sin(np.linspace(0, 2 * np.pi * n / RATE / 4, n))
        return (rumble * swell).astype(np.float32), 10.0
    if kind == "tv":
        return say(TV_TEXT * 2, TV_VOICE, RATE), 8.0
    raise ValueError(f"unknown noise {kind!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=AUDIO_ROOT / "synthetic")
    parser.add_argument("--voices", default=",".join(VOICES))
    args = parser.parse_args(argv)
    if not Path("/usr/bin/say").exists():
        print("This needs macOS `say`; run it on the Mac host, not in Docker.", file=sys.stderr)
        return 1

    rng = np.random.default_rng(4)
    lead = np.zeros(int(LEAD_IN_S * RATE), dtype=np.float32)
    count = 0
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        for voice in args.voices.split(","):
            folder = args.out / voice.lower()
            if folder.exists():
                shutil.rmtree(folder)
            folder.mkdir(parents=True)
            for spec in load_specs().values():
                if spec.say:
                    speech = np.concatenate([lead, say(spec.say, voice, RATE)])
                else:  # silence: a faint noise floor, as a quiet phone line has
                    speech = (colored_noise(10 * RATE, 1.0, rng) * 10 ** (-60 / 20)).astype(
                        np.float32
                    )
                files = {spec.id: speech}
                for kind in spec.noise:
                    noise, snr = make_noise(kind, speech.size, rng, tmp)
                    files[f"{spec.id}+{kind}"] = mix(speech, noise, snr)
                for name, audio in files.items():
                    path = folder / f"{name}.wav"
                    path.write_bytes(pcm.wav_bytes(pcm.float_to_pcm16(audio), RATE))
                    count += 1
            print(f"{voice}: {folder}")
    print(f"{count} clips written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
