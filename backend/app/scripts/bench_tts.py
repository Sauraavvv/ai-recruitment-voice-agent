"""TTS latency benchmark (phase-03 plan, P3-T7).

    python -m app.scripts.bench_tts [--runs 50] [--threads 1,2,4] [--json out.json]

Reports, per thread setting: cold load, warm latency for short/medium/long sentences (p50/p95),
real-time factor, two concurrent syntheses vs one, and event-loop lag during synthesis.
Prints a Markdown table for docs/benchmarks/tts.md.
"""

import argparse
import asyncio
import json
import os
import platform
import statistics
import time
from pathlib import Path
from typing import Any

from app.providers.tts.kitten_provider import MODEL_NAME, KittenTTSProvider, resolve_model_dir

SENTENCES = {
    "short": "Got it, thank you.",  # ~5 words, the first chunk of most replies
    "medium": "Thanks, Rahul. What is your current notice period at your company, in days?",
    "long": (
        "Thanks. Just to confirm, you have 5.5 years of experience, a current CTC of 12.5 lakhs, "
        "and an expected CTC of 18 lakhs. Is that correct?"
    ),
}


def cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.lower().startswith(("model name", "hardware", "cpu model")):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    if platform.system() == "Darwin":
        import subprocess

        out = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            check=False,
        )
        return out.stdout.strip() or platform.processor()
    return platform.processor() or platform.machine()


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


async def lag_during(work: Any) -> tuple[float, float]:
    """Run `work` while a 5 ms ticker measures how late the event loop wakes it (p99, max ms)."""
    lags: list[float] = []
    stop = asyncio.Event()

    async def ticker() -> None:
        while not stop.is_set():
            t = time.perf_counter()
            await asyncio.sleep(0.005)
            lags.append((time.perf_counter() - t - 0.005) * 1000)

    task = asyncio.create_task(ticker())
    await work
    stop.set()
    await task
    return pct(lags, 0.99), max(lags)


async def bench(threads: int, runs: int) -> dict[str, Any]:
    provider = KittenTTSProvider(model_dir=resolve_model_dir(os.getenv("KITTEN_MODEL_PATH")),
                                 voice=os.getenv("KITTEN_VOICE") or "Iris",
                                 threads=threads, max_workers=2, timeout_s=30)  # fmt: skip
    started = time.perf_counter()
    await provider.initialize()
    result: dict[str, Any] = {"threads": threads, "load_s": round(time.perf_counter() - started, 2)}

    for name, text in SENTENCES.items():
        times, audio_ms = [], 0
        for _ in range(runs):
            t = time.perf_counter()
            clip = await provider.synthesize(text, cache=False)
            times.append((time.perf_counter() - t) * 1000)
            audio_ms = clip.duration_ms
        p50 = statistics.median(times)
        result[name] = {
            "p50_ms": round(p50),
            "p95_ms": round(pct(times, 0.95)),
            "audio_ms": audio_ms,
            "rtf": round(p50 / audio_ms, 3),
        }

    medium = SENTENCES["medium"]
    pairs = []
    for _ in range(max(5, runs // 5)):
        t = time.perf_counter()
        await asyncio.gather(
            provider.synthesize(medium, cache=False), provider.synthesize(medium, cache=False)
        )
        pairs.append((time.perf_counter() - t) * 1000)
    result["concurrent2_p50_ms"] = round(statistics.median(pairs))
    result["concurrent2_ratio"] = round(statistics.median(pairs) / result["medium"]["p50_ms"], 2)

    async def repeated() -> None:
        for _ in range(max(5, runs // 5)):
            await provider.synthesize(medium, cache=False)

    lag_p99, lag_max = await lag_during(repeated())
    result["loop_lag_p99_ms"], result["loop_lag_max_ms"] = round(lag_p99, 1), round(lag_max, 1)
    await provider.close()
    return result


def markdown(env: dict[str, Any], results: list[dict[str, Any]]) -> str:
    head = (
        f"**{env['where']}**: {env['cpu']}, {env['cores']} cores, {env['system']}, "
        f"{env['model']}, {env['runs']} runs per sentence\n\n"
        "| Threads | Cold load | Short p50 / p95 | Medium p50 / p95 | Long p50 / p95 | RTF (m) "
        "| 2 concurrent (× single) | Loop lag p99 / max |\n|---|---|---|---|---|---|---|---|\n"
    )
    rows = [
        f"| {r['threads']} | {r['load_s']} s | {r['short']['p50_ms']} / {r['short']['p95_ms']} ms "
        f"| {r['medium']['p50_ms']} / {r['medium']['p95_ms']} ms "
        f"| {r['long']['p50_ms']} / {r['long']['p95_ms']} ms | {r['medium']['rtf']} "
        f"| {r['concurrent2_p50_ms']} ms ({r['concurrent2_ratio']}×) "
        f"| {r['loop_lag_p99_ms']} / {r['loop_lag_max_ms']} ms |"
        for r in results
    ]
    audio = results[0]
    sizes = ", ".join(f"{k} {audio[k]['audio_ms']} ms" for k in SENTENCES)
    return head + "\n".join(rows) + f"\n\nAudio lengths: {sizes}.\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--runs", type=int, default=50)
    parser.add_argument("--threads", default="2", help="comma-separated, e.g. 1,2,4")
    parser.add_argument("--where", default="Docker" if Path("/.dockerenv").exists() else "Host")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    env = {
        "where": args.where,
        "cpu": cpu_model(),
        "cores": os.cpu_count(),
        "system": f"{platform.system()} {platform.machine()}",
        "model": MODEL_NAME,
        "runs": args.runs,
    }
    results = [asyncio.run(bench(int(t), args.runs)) for t in args.threads.split(",")]
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"env": env, "results": results}, indent=1) + "\n")
    print(markdown(env, results))


if __name__ == "__main__":
    main()
