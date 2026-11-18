"""Stream a WAV file to Deepgram like a live call and show what comes back (plan P4-T3, T4).

    make stt-file FILE=artifacts/stt-audio/synthetic/rishi/c07_multi_answer.wav [RATE=8000]
    python -m app.scripts.stt_file FILE [--rate 8000] [--fast] [--model nova-2]
        [--language en-IN] [--endpointing 300] [--keyterm Infosys] [--dump-events out.json]

Audio is sent in 20 ms frames at real-time pace (`--fast` sends as fast as possible), then
2.5 s of silence. `--rate 8000` sends the phone-band version (8 kHz, through μ-law), which is
what calls will sound like. Partials are shown live; each finished utterance is printed with
its latency from the end of speech (the last word's end time) to the utterance completing.

`--dump-events` saves Deepgram's raw messages, sanitized (request ids and hashes removed) and
timestamped relative to the first audio, for tests/fixtures/deepgram_events/.
"""

import argparse
import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.providers.stt import create_stt_provider
from app.providers.stt.base import STTError
from app.providers.stt.deepgram_provider import DeepgramSTTProvider
from app.scripts.stt_tools import prepare, read_wav, stream_pcm
from app.utils.log import configure_logging
from app.voice.utterance import UtteranceAssembler

SECRET_FIELDS = {"request_id", "sha256", "transaction_key", "model_uuid", "created"}


def sanitize(msg: Any) -> Any:
    if isinstance(msg, dict):
        return {k: sanitize(v) for k, v in msg.items() if k not in SECRET_FIELDS}
    if isinstance(msg, list):
        return [sanitize(v) for v in msg]
    return msg


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()
    updates: dict[str, Any] = {}
    if args.model:
        updates["deepgram_stt_model"] = args.model
    if args.language:
        updates["deepgram_stt_language"] = args.language
    if args.endpointing:
        updates["deepgram_stt_endpointing_ms"] = args.endpointing
    settings = settings.model_copy(update=updates)
    audio, rate = read_wav(Path(args.file))
    data = prepare(audio, rate, args.rate)

    stt = create_stt_provider(settings, keyterms=args.keyterm)
    assert isinstance(stt, DeepgramSTTProvider)
    raw: list[dict[str, Any]] = []
    t0 = 0.0
    if args.dump_events:
        stt.on_message = lambda m: raw.append({"_t": round(time.monotonic() - t0, 3), **m})
    session_id = f"file-{uuid.uuid4().hex[:8]}"
    assembler = UtteranceAssembler(session_id)
    print(
        f"{args.file}  {len(data) / 2 / args.rate:.1f} s at {args.rate} Hz  "
        f"{stt.model}/{stt.language} endpointing={stt.endpointing_ms} ms"
    )
    try:
        await stt.start_stream(session_id=session_id, encoding="linear16", sample_rate=args.rate)
    except STTError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    t0 = time.monotonic()

    async def show() -> None:
        async for event in stt.events():
            if event.kind == "partial":
                print(
                    f"\r\033[K\033[2m… {assembler.preview} {event.text}\033[0m", end="", flush=True
                )
            utterance = assembler.feed(event)
            if event.kind == "final" and event.text:
                print(
                    f"\r\033[K  final  {event.start_s:5.2f}-{event.end_s:5.2f}s "
                    f"conf={event.confidence:.2f} endpoint={event.endpoint}  {event.text}"
                )
            elif event.kind in ("utterance_end", "error"):
                print(f"\r\033[K  {event.kind} {event.end_s or event.detail or ''}")
            if utterance is not None:
                spoken = stt.sent_at(utterance.ended_at or 0)
                latency = (utterance.completed_at - spoken) * 1000 if spoken else float("nan")
                print(
                    f"\033[1m» {utterance.text}\033[0m  [{utterance.trigger}, "
                    f"conf={utterance.confidence or 0:.2f}, {latency:.0f} ms after speech]"
                )

    shower = asyncio.create_task(show())
    await stream_pcm(stt, data, args.rate, realtime=not args.fast)
    await stt.close()
    await shower
    print(
        f"\nconnects={stt.stats.connects} audio={stt.stats.audio_s_sent:.1f}s "
        f"fillers_dropped={assembler.dropped_fillers}"
    )
    if args.dump_events:
        out = Path(args.dump_events)
        out.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "file": Path(args.file).name,
            "rate": args.rate,
            "model": stt.model,
            "language": stt.language,
            "endpointing_ms": stt.endpointing_ms,
        }
        out.write_text(json.dumps({"meta": meta, "messages": sanitize(raw)}, indent=1) + "\n")
        print(f"events: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stream a WAV to Deepgram STT")
    parser.add_argument("file")
    parser.add_argument("--rate", type=int, default=16000, choices=(8000, 16000))
    parser.add_argument("--fast", action="store_true", help="don't pace at real time")
    parser.add_argument("--model")
    parser.add_argument("--language")
    parser.add_argument("--endpointing", type=int)
    parser.add_argument("--keyterm", action="append", default=[])
    parser.add_argument("--dump-events")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    configure_logging("INFO" if args.verbose else "WARNING")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
