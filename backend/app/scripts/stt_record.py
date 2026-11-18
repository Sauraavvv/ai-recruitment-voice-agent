"""Record real test clips for the STT benchmark (plan P4-T8). Run on the Mac host:

    make stt-record SPEAKER=asha            # every line in tests/fixtures/stt_clips.yaml
    make stt-record SPEAKER=asha ONLY=c09   # just some lines

Only record people who have agreed to it; the clips stay on this machine
(artifacts/stt-audio/real/<speaker>/, not committed; plan P4 §10).

For each line: read the prompt, press Enter, say it naturally (numbers the way you'd normally
say them), and press Enter again when done. Lines marked PAUSE want a real pause where the
"..." is, as if recalling a number. Press s to skip, r to redo the last line.
For background noise, record a second take with the fan or TV on, then rename it to
<clip id>+fan.wav (or +tv, +traffic).
"""

import argparse
import sys
import threading
from pathlib import Path

import numpy as np

from app.scripts.stt_tools import AUDIO_ROOT, load_specs
from app.voice import pcm

RATE = 16000


def record_until_enter() -> np.ndarray:
    import sounddevice as sd

    chunks: list[np.ndarray] = []
    stop = threading.Event()

    def callback(data: np.ndarray, _frames: int, _time: object, _status: object) -> None:
        chunks.append(data.copy())

    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", callback=callback):

        def wait_for_enter() -> None:
            input()
            stop.set()

        threading.Thread(target=wait_for_enter, daemon=True).start()
        stop.wait()
    return np.concatenate(chunks)[:, 0] if chunks else np.zeros(0, dtype=np.float32)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--speaker", required=True, help="a short name for the folder")
    parser.add_argument("--only", help="comma-separated clip id prefixes")
    args = parser.parse_args(argv)
    folder = AUDIO_ROOT / "real" / args.speaker
    folder.mkdir(parents=True, exist_ok=True)
    specs = [s for s in load_specs().values() if s.text]
    if args.only:
        specs = [s for s in specs if any(s.id.startswith(p) for p in args.only.split(","))]

    print(f"Recording {len(specs)} lines into {folder}. Ctrl+C to stop.\n")
    i = 0
    while i < len(specs):
        spec = specs[i]
        flag = "  [PAUSE where the … is]" if spec.pause else ""
        print(f"\n{i + 1}/{len(specs)} {spec.id}{flag}\n    \033[1m{spec.text}\033[0m")
        choice = input("  Enter = start, s = skip, r = redo previous: ").strip().lower()
        if choice == "s":
            i += 1
            continue
        if choice == "r" and i > 0:
            i -= 1
            continue
        print("  ● recording… press Enter when done")
        audio = record_until_enter()
        if audio.size < RATE // 2:
            print("  too short, again")
            continue
        path: Path = folder / f"{spec.id}.wav"
        path.write_bytes(pcm.wav_bytes(pcm.float_to_pcm16(audio), RATE))
        peak_db = 20 * np.log10(float(np.abs(audio).max()) + 1e-9)
        print(f"  saved {path.name} ({audio.size / RATE:.1f} s, peak {peak_db:.0f} dBFS)")
        i += 1
    print("\nDone. Benchmark them: make bench-stt args='--sets real'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
