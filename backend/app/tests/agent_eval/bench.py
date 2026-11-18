"""LLM latency benchmark for choosing OPENAI_MODEL (P2-T1).

    python -m app.tests.agent_eval.bench --models gpt-a,gpt-b [--turns 30] [--effort none]

Replays representative scenarios one conversation at a time (no concurrency, so latency isn't
inflated) until each model has made `--turns` agent calls. Target: p50 <= 1.2 s, p95 <= 2.5 s.
"""

import argparse
import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import yaml

from app.agent.prompts import JobConfig
from app.config import load_settings
from app.providers.llm import create_llm_provider
from app.tests.agent_eval.runner import HERE, RESULTS, load_scenarios, percentile, run_scenario

BENCH_SCENARIOS = ["s14", "s02", "s10", "s05", "s04", "s03", "s15"]


async def bench_model(model: str, turns: int, effort: str | None) -> dict[str, Any]:
    settings = load_settings().model_copy(
        update={"openai_model": model, "openai_reasoning_effort": effort}
    )
    llm = create_llm_provider(settings)
    job = JobConfig.from_dict(yaml.safe_load((HERE / "job.yaml").read_text()))
    scenarios = load_scenarios(BENCH_SCENARIOS)
    latencies: list[int] = []
    tokens_in = tokens_out = cached = retries = passed = convs = 0
    i = 0
    try:
        while len(latencies) < turns:
            rr = await run_scenario(scenarios[i % len(scenarios)], job, llm, settings, run=i)
            i += 1
            convs += 1
            passed += rr.passed
            latencies += rr.latencies_ms
            tokens_in += rr.input_tokens
            tokens_out += rr.output_tokens
            cached += rr.cached_tokens
            retries += rr.retries
            if rr.error:
                print(f"  {model}: {rr.scenario} error {rr.error}")
    finally:
        await llm.aclose()
    n = len(latencies)
    return {
        "model": model,
        "reasoning_effort": effort,
        "calls": n,
        "p50_ms": round(percentile(latencies, 0.5)),
        "p95_ms": round(percentile(latencies, 0.95)),
        "max_ms": max(latencies, default=0),
        "avg_input_tokens": round(tokens_in / max(1, n)),
        "avg_cached_tokens": round(cached / max(1, n)),
        "avg_output_tokens": round(tokens_out / max(1, n)),
        "retries": retries,
        "conversations": convs,
        "conversations_passed": passed,
    }


async def main_async(models: list[str], turns: int, effort: str | None) -> list[dict[str, Any]]:
    rows = []
    for model in models:
        print(f"benchmarking {model} ...")
        rows.append(await bench_model(model, turns, effort))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", required=True, help="comma-separated model ids")
    parser.add_argument("--turns", type=int, default=30)
    parser.add_argument("--effort", help="reasoning effort for reasoning models")
    args = parser.parse_args()
    rows = asyncio.run(main_async(args.models.split(","), args.turns, args.effort))
    print(
        f"\n{'model':28} {'calls':>5} {'p50':>6} {'p95':>6} {'max':>6} {'in':>6} {'cached':>6} "
        f"{'out':>5} {'pass':>6}"
    )
    for r in rows:
        print(
            f"{r['model']:28} {r['calls']:>5} {r['p50_ms']:>6} {r['p95_ms']:>6} {r['max_ms']:>6} "
            f"{r['avg_input_tokens']:>6} {r['avg_cached_tokens']:>6} {r['avg_output_tokens']:>5} "
            f"{r['conversations_passed']}/{r['conversations']}"
        )
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"bench-{datetime.now(UTC):%Y-%m-%d-%H%M}.json"
    path.write_text(json.dumps(rows, indent=1))
    print(f"\nresults: {path}")


if __name__ == "__main__":
    main()
