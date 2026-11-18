"""STT benchmark over the test clips (plan P4-T9). Uses the live Deepgram API (about $0.50 for
the full synthetic set with the default configurations).

    make bench-stt                                  # all configurations, synthetic set
    make bench-stt args='--configs n3-in-8k-500,flux-8k --sets synthetic,real'

For each configuration (model × language × 8/16 kHz × endpointing) and clip it streams the
audio at real-time pace, then 2.5 s of silence, and measures:
- key-entity accuracy: numbers, companies and cities from tests/fixtures/stt_clips.yaml found
  in the finished utterances (more useful here than word error rate)
- latency: end of speech (the last word's end) → utterance complete, p50/p95
- false endpoints: more utterances than the clip has answers (the speaker was cut off), split
  into clips with a mid-answer pause and clips without; spurious utterances on silence/filler

Nova runs through DeepgramSTTProvider + UtteranceAssembler, exactly as calls will. Flux
(`/v2/listen`, Deepgram's turn-taking model) runs through a minimal client here, for comparison:
one utterance per `EndOfTurn`.

Results: artifacts/stt-bench/<time>.json, and a table printed for docs/benchmarks/stt.md.
"""

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import numpy as np
from websockets.asyncio.client import connect

from app.config import get_settings
from app.providers.stt import default_keyterms
from app.providers.stt.deepgram_provider import DeepgramSTTProvider
from app.scripts.stt_tools import (
    ClipFile,
    discover,
    entity_hits,
    prepare,
    read_wav,
    speech_end_s,
    stream_pcm,
)
from app.utils.log import configure_logging
from app.voice import pcm
from app.voice.utterance import UtteranceAssembler

OUT_DIR = Path("artifacts/stt-bench")
TAIL_S = 2.5
# The silence after each answer is a faint noise floor, as on a real phone line. With digital
# zeros Deepgram's endpointing fires noticeably sooner than it will on calls (benchmarks/stt.md).
TAIL_DBFS: float | None = -60.0
# Company names the agent would add per job/candidate; the bench boosts the ones in the clips.
CLIP_KEYTERMS = ["Infosys", "Wipro", "Accenture", "HCL", "Tata Consultancy Services"]


@dataclass(frozen=True)
class Config:
    name: str
    kind: str  # nova | flux
    model: str
    language: str
    rate: int
    endpointing_ms: int = 500
    eot_threshold: float = 0.7
    smart_format: bool = True
    # Send Finalize this long after the speech ends, as a local end-of-speech detector would.
    # The bench knows where speech ends from the clean clip (an ideal detector).
    finalize_ms: int | None = None


CONFIGS = [
    Config("n3-in-8k-300", "nova", "nova-3", "en-IN", 8000, 300),
    Config("n3-in-8k-500", "nova", "nova-3", "en-IN", 8000, 500),
    Config("n3-in-8k-800", "nova", "nova-3", "en-IN", 8000, 800),
    Config("n3-en-8k-500", "nova", "nova-3", "en", 8000, 500),
    Config("n2-in-8k-500", "nova", "nova-2", "en-IN", 8000, 500),
    Config("n3-in-16k-500", "nova", "nova-3", "en-IN", 16000, 500),
    Config("n3-in-8k-300-nosf", "nova", "nova-3", "en-IN", 8000, 300, smart_format=False),
    Config("n3-in-8k-fin400", "nova", "nova-3", "en-IN", 8000, 300, finalize_ms=400),
    Config("flux-8k", "flux", "flux-general-en", "en", 8000),
]


@dataclass
class ClipResult:
    config: str
    clip: str
    clip_id: str
    noise: str | None
    pause: bool
    expected: int
    utterances: list[str] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)
    hits: list[bool] = field(default_factory=list)
    error: str | None = None


async def run_nova(
    cfg: Config, clip: ClipFile, data: bytes, key: str, keyterms: list[str], speech_end: float
) -> ClipResult:
    result = ClipResult(
        cfg.name, clip.name, clip.spec.id, clip.noise, clip.spec.pause, clip.spec.utterances
    )
    stt = DeepgramSTTProvider(
        api_key=key,
        model=cfg.model,
        language=cfg.language,
        endpointing_ms=cfg.endpointing_ms,
        keyterms=keyterms,
        smart_format=cfg.smart_format,
    )
    sid = f"bench-{uuid.uuid4().hex[:8]}"
    assembler = UtteranceAssembler(sid)
    await stt.start_stream(session_id=sid, encoding="linear16", sample_rate=cfg.rate)

    async def listen() -> None:
        async for event in stt.events():
            if event.kind == "error":
                result.error = event.detail
            u = assembler.feed(event)
            if u is not None:
                result.utterances.append(u.text)
                spoken = stt.sent_at(u.ended_at) if u.ended_at is not None else None
                if spoken is not None:
                    result.latencies_ms.append((u.completed_at - spoken) * 1000)

    listener = asyncio.create_task(listen())
    finalize_at = None if cfg.finalize_ms is None else speech_end + cfg.finalize_ms / 1000
    await stream_pcm(
        stt,
        data,
        cfg.rate,
        tail_silence_s=TAIL_S,
        tail_noise_dbfs=TAIL_DBFS,
        finalize_at_s=finalize_at,
    )
    await stt.close()
    await listener
    return result


async def run_flux(
    cfg: Config, clip: ClipFile, data: bytes, key: str, keyterms: list[str], speech_end: float
) -> ClipResult:
    result = ClipResult(
        cfg.name, clip.name, clip.spec.id, clip.noise, clip.spec.pause, clip.spec.utterances
    )
    params = [
        ("model", cfg.model),
        ("encoding", "linear16"),
        ("sample_rate", str(cfg.rate)),
        ("eot_threshold", str(cfg.eot_threshold)),
    ] + [("keyterm", k) for k in keyterms]
    ws = await connect(
        f"wss://api.deepgram.com/v2/listen?{urlencode(params)}",
        additional_headers={"Authorization": f"Token {key}"},
        open_timeout=5,
    )
    step = cfg.rate * 80 // 1000 * 2  # Deepgram recommends 80 ms frames for Flux
    tail = b"\0" * int(TAIL_S * cfg.rate) * 2
    if TAIL_DBFS is not None:
        rng = np.random.default_rng(0)
        noise = rng.standard_normal(int(TAIL_S * cfg.rate)) * 10 ** (TAIL_DBFS / 20)
        tail = pcm.float_to_pcm16(noise.astype(np.float32))
    audio = data + tail
    frames = [audio[i : i + step] for i in range(0, len(audio), step)]
    t0 = time.monotonic()

    async def listen() -> None:
        async for message in ws:
            msg = json.loads(message)
            if msg.get("type") == "Error":
                result.error = msg.get("description")
            if msg.get("type") != "TurnInfo" or msg.get("event") != "EndOfTurn":
                continue
            text = (msg.get("transcript") or "").strip()
            if not text:
                continue
            result.utterances.append(text)
            if msg.get("words"):
                spoken = t0 + float(msg["words"][-1]["end"])
                result.latencies_ms.append((time.monotonic() - spoken) * 1000)

    listener = asyncio.create_task(listen())
    for i, frame in enumerate(frames):
        await ws.send(frame)
        await asyncio.sleep(max(0.0, t0 + (i + 1) * 0.08 - time.monotonic()))
    await ws.send(json.dumps({"type": "CloseStream"}))
    try:
        await asyncio.wait_for(listener, 5)
    except TimeoutError:
        listener.cancel()
    await ws.close()
    return result


def pct(values: list[float], q: float) -> float:
    if not values:
        return float("nan")
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1]


def summarize(results: list[ClipResult]) -> dict[str, Any]:
    entities = [h for r in results for h in r.hits]
    lat = [x for r in results for x in r.latencies_ms]
    answer = [r for r in results if r.expected > 0]
    return {
        "clips": len(results),
        "entity_accuracy": sum(entities) / len(entities) if entities else float("nan"),
        "entities": f"{sum(entities)}/{len(entities)}",
        "clips_all_entities": sum(all(r.hits) for r in answer),
        "answer_clips": len(answer),
        "latency_p50_ms": pct(lat, 50),
        "latency_p95_ms": pct(lat, 95),
        "false_endpoints_pause": sum(
            max(0, len(r.utterances) - r.expected) for r in answer if r.pause
        ),
        "pause_clips": sum(r.pause for r in answer),
        "false_endpoints_other": sum(
            max(0, len(r.utterances) - r.expected) for r in answer if not r.pause
        ),
        "missed_clips": sum(not r.utterances for r in answer),
        "spurious": sum(len(r.utterances) for r in results if r.expected == 0),
        "errors": sum(r.error is not None for r in results),
    }


async def main_async(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.deepgram_api_key:
        print("DEEPGRAM_API_KEY is not set", file=sys.stderr)
        return 1
    key = settings.deepgram_api_key.get_secret_value()
    keyterms = [*default_keyterms(settings), *CLIP_KEYTERMS] if not args.no_keyterms else []
    configs = [c for c in CONFIGS if not args.configs or c.name in args.configs.split(",")]
    clips = [
        c
        for c in discover(tuple(args.sets.split(",")))
        if (not args.clips or any(p in c.name for p in args.clips.split(",")))
    ]
    if not clips:
        print("No clips found: run `make stt-clips` first (or record some).", file=sys.stderr)
        return 1
    global TAIL_DBFS
    TAIL_DBFS = None if args.tail_dbfs == "zero" else float(args.tail_dbfs)
    audio = {c.path: read_wav(c.path) for c in clips}

    def speech_end(clip: ClipFile) -> float:
        """From the clean version of the clip (the noisy one has noise past the speech)."""
        base = clip.path.with_name(f"{clip.spec.id}.wav")
        samples, rate = audio.get(base) or read_wav(base)
        return speech_end_s(samples, rate)

    limit = asyncio.Semaphore(args.concurrency)
    total = len(clips) * len(configs)
    done = 0
    print(f"{len(clips)} clips × {len(configs)} configurations, {args.concurrency} at a time")

    async def one(cfg: Config, clip: ClipFile) -> ClipResult:
        nonlocal done
        data = prepare(*audio[clip.path], cfg.rate)
        async with limit:
            runner = run_flux if cfg.kind == "flux" else run_nova
            try:
                r = await runner(cfg, clip, data, key, keyterms, speech_end(clip))
            except Exception as exc:
                r = ClipResult(
                    cfg.name,
                    clip.name,
                    clip.spec.id,
                    clip.noise,
                    clip.spec.pause,
                    clip.spec.utterances,
                    error=f"{type(exc).__name__}: {exc}",
                )
        r.hits = entity_hits(" ".join(r.utterances), clip.spec.entities)
        done += 1
        print(f"\r{done}/{total}", end="", flush=True)
        return r

    results = await asyncio.gather(*(one(cfg, c) for cfg in configs for c in clips))
    print()
    summary = {cfg.name: summarize([r for r in results if r.config == cfg.name]) for cfg in configs}

    print(
        "\n| Config | Entities | Clips fully right | Latency p50 / p95 | False endpoints "
        "(pause / other) | Missed | Spurious | Errors |"
    )
    print("|---|---|---|---|---|---|---|---|")
    for name, s in summary.items():
        print(
            f"| {name} | {s['entity_accuracy']:.1%} ({s['entities']}) | "
            f"{s['clips_all_entities']}/{s['answer_clips']} | "
            f"{s['latency_p50_ms']:.0f} / {s['latency_p95_ms']:.0f} ms | "
            f"{s['false_endpoints_pause']} / {s['false_endpoints_other']} | "
            f"{s['missed_clips']} | {s['spurious']} | {s['errors']} |"
        )
    if args.misses:
        print("\nMissed entities:")
        for r in results:
            if not all(r.hits) or r.error:
                print(f"  {r.config:14} {r.clip:45} {' | '.join(r.utterances)!r} {r.error or ''}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(
        json.dumps(
            {
                "configs": [asdict(c) for c in configs],
                "keyterms": keyterms,
                "summary": summary,
                "results": [asdict(r) for r in results],
            },
            indent=1,
        )
    )
    print(f"\nresults: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deepgram STT benchmark")
    parser.add_argument("--configs", help="comma-separated names (default: all)")
    parser.add_argument("--sets", default="synthetic", help="synthetic,real")
    parser.add_argument("--clips", help="only clip names containing one of these")
    parser.add_argument("--concurrency", type=int, default=int(os.getenv("BENCH_CONCURRENCY", "8")))
    parser.add_argument("--no-keyterms", action="store_true")
    parser.add_argument("--tail-dbfs", default="-60", help="noise floor after speech, or 'zero'")
    parser.add_argument("--misses", action="store_true", help="list every clip with a miss")
    args = parser.parse_args(argv)
    configure_logging("ERROR")
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
