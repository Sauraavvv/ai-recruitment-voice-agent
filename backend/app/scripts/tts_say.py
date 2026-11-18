"""Speak a line with the configured voice and save it as a WAV (P3-T6 listening checks).

    make tts-say TEXT="Hello, am I speaking with Priya Iyer?"   # plays it on macOS
    make tts-say TEXT="Your CTC is 12.5 LPA." PHONE=1           # plus the 8 kHz μ-law version

Writes artifacts/tts/<time>-<words>.wav (and -8k.wav), plus last.wav / last-8k.wav for the
Makefile to play. Prints the normalized text, so pronunciation problems can be traced to either
the normalizer or the voice. Add respellings to app/voice/pronunciations.yaml.
"""

import argparse
import asyncio
import re
import shutil
import subprocess
import time
from pathlib import Path

from app.config import get_settings
from app.providers.tts import create_tts_provider
from app.providers.tts.kitten_provider import KittenTTSProvider
from app.voice import pcm
from app.voice.text_normalizer import normalize_for_speech

OUT_DIR = Path("artifacts/tts")


async def say(text: str, *, voice: str | None, phone: bool, play: bool) -> None:
    settings = get_settings()
    if voice:
        settings = settings.model_copy(update={"kitten_voice": voice})
    provider = create_tts_provider(settings)
    assert isinstance(provider, KittenTTSProvider)
    started = time.perf_counter()
    await provider.initialize()
    load_s = time.perf_counter() - started

    print(f"text:   {text}")
    print(f"spoken: {normalize_for_speech(text)}")
    started = time.perf_counter()
    clip = await provider.synthesize(text, cache=False)
    synth_ms = (time.perf_counter() - started) * 1000
    await provider.close()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = "-".join(re.findall(r"[a-z0-9]+", text.lower())[:6]) or "clip"
    base = OUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{slug}"
    files = {base.with_suffix(".wav"): pcm.wav_bytes(clip.pcm, clip.sample_rate)}
    if phone:
        narrow = pcm.wav_bytes(pcm.phone_band(clip.pcm, clip.sample_rate), 8000)
        files[Path(f"{base}-8k.wav")] = narrow
    for path, data in files.items():
        path.write_bytes(data)
        last = OUT_DIR / ("last-8k.wav" if path.name.endswith("-8k.wav") else "last.wav")
        last.write_bytes(data)
        print(f"wrote:  {path}")
    print(
        f"voice {provider.voice}, {clip.sample_rate} Hz, {clip.duration_ms} ms of audio, "
        f"synthesized in {synth_ms:.0f} ms (model load {load_s:.1f} s)"
    )
    if play and (player := shutil.which("afplay")):
        for path in files:
            subprocess.run([player, str(path)], check=False)  # noqa: S603


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("text")
    parser.add_argument("--voice", help="override KITTEN_VOICE")
    parser.add_argument("--phone", action="store_true", help="also write the 8 kHz μ-law version")
    parser.add_argument("--no-play", action="store_true")
    args = parser.parse_args()
    asyncio.run(say(args.text, voice=args.voice, phone=args.phone, play=not args.no_play))


if __name__ == "__main__":
    main()
