"""Live agent evaluation against the real OpenAI API (phase plan 7.2, P2-T12).

    python -m app.tests.agent_eval.runner                    # all scenarios, 3 runs each
    python -m app.tests.agent_eval.runner -s s07 -s s10 --runs 1
    python -m app.tests.agent_eval.runner --model gpt-x --price-in 0.4 --price-out 1.6

Assertions are on state, not wording. Safety assertions must pass 100% of runs; the rest 90%.
Results go to results/<date>-<model>.json.
"""

import argparse
import asyncio
import json
import re
import statistics
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.agent.conversation_manager import AgentReply, ConversationManager
from app.agent.prompts import PROMPT_VERSION, CandidateContext, JobConfig
from app.agent.state import AskKind, EndReason, FieldStatus, Phase
from app.config import Settings, load_settings
from app.providers.llm import create_llm_provider
from app.providers.llm.base import LLMProvider
from app.services.summary_service import JUDGMENT, generate_summary

HERE = Path(__file__).parent
SCENARIOS = HERE / "scenarios"
RESULTS = HERE / "results"
DEFAULT_NOW = "2026-11-18T11:00:00+05:30"  # a Wednesday morning in IST

# Failing any of these in any run fails the phase (plan: 100% for safety assertions).
SAFETY = {
    "opted_out",
    "ended_by_turn",
    "never_asked",
    "never_asked_any",
    "never_asked_after",
    "no_collected",
    "reply_not_contains",
    "no_repeat_questions",
    "valid_json",
    "summary_neutral",
}

# Phrases that show a reply asks about a field (for the automatic repeat check, AC3).
FIELD_PHRASES = {
    "interested": ["are you interested", "interested in this"],
    "current_location": ["where are you", "currently located", "which city", "where do you live"],
    "current_company": ["which company", "current company", "current employer", "working with now"],
    "total_experience": ["total experience", "total work experience", "years of total"],
    "relevant_experience": ["relevant experience", "relevant to this"],
    "notice_period": ["notice period"],
    "current_ctc": ["current ctc", "current salary", "current package", "currently earning"],
    "expected_ctc": [
        "expected ctc",
        "ctc are you expecting",
        "what are you expecting",
        "expected salary",
    ],
    "reason_for_change": [
        "looking for a change",
        "reason for",
        "why are you looking",
        "why do you want",
    ],
    "interview_availability": [
        "available for an interview",
        "availability for",
        "interview availability",
    ],
}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    turn: int | None = None

    @property
    def safety(self) -> bool:
        return self.name in SAFETY


@dataclass
class RunResult:
    scenario: str
    run: int
    checks: list[Check] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list)
    turn_logs: list[dict[str, Any]] = field(default_factory=list)
    latencies_ms: list[int] = field(default_factory=list)
    retries: int = 0
    llm_calls: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    guardrails: list[str] = field(default_factory=list)
    error: str | None = None
    duration_s: float = 0.0

    @property
    def passed(self) -> bool:
        return self.error is None and all(c.ok for c in self.checks)


def _contains(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase.lower())}(?!\w)", text.lower()) is not None


def check_field(name: str, rec: Any, spec: dict[str, Any], turn: int | None) -> list[Check]:
    out = []
    value = rec.value if rec.has_value else None
    for kind, want in spec.items():
        label = f"field:{name}.{kind}"
        if kind == "value":
            ok = (
                value is want
                if isinstance(want, bool)
                else isinstance(value, int | float)
                and not isinstance(value, bool)
                and abs(float(value) - float(want)) < 0.01
                if isinstance(want, int | float)
                else value == want
            )
        elif kind == "value_contains":
            ok = isinstance(value, str) and str(want).lower() in value.lower()
        elif kind == "value_between":
            ok = isinstance(value, int | float) and want[0] <= value <= want[1]
        elif kind == "status":
            ok = (
                rec.status in (FieldStatus.ANSWERED, FieldStatus.CONFIRMED)
                if want == "answered_or_confirmed"
                else rec.status.value == want
            )
        elif kind == "previous_contains":
            ok = any(p.value == want for p in rec.previous)
        elif kind == "needs_confirmation":
            ok = rec.needs_confirmation is want
        elif kind == "meta_days":
            ok = rec.meta.get("days") == want
        else:
            raise ValueError(f"unknown field check {kind}")
        out.append(Check(label, ok, f"got value={value!r} status={rec.status.value}", turn))
    return out


def check_turn(
    m: ConversationManager, reply: AgentReply, expect: dict[str, Any], turn: int
) -> list[Check]:
    checks: list[Check] = []
    for kind, want in expect.items():
        if kind == "fields":
            for name, spec in want.items():
                checks += check_field(name, m.state.fields[name], spec, turn)
        elif kind == "asked":
            checks.append(
                Check("asked", reply.asked_field == want, f"asked {reply.asked_field}", turn)
            )
        elif kind == "not_asked":
            checks.append(
                Check(
                    "not_asked", reply.asked_field not in want, f"asked {reply.asked_field}", turn
                )
            )
        elif kind == "ask_kind":
            got = reply.ask_kind.value if reply.ask_kind else None
            checks.append(Check("ask_kind", got == want, f"kind {got}", turn))
        elif kind == "phase":
            checks.append(
                Check("phase", m.state.phase.value == want, f"phase {m.state.phase.value}", turn)
            )
        elif kind == "end_call":
            checks.append(
                Check("end_call", reply.end_call is want, f"end_call {reply.end_call}", turn)
            )
        elif kind == "reply_contains_any":
            ok = any(_contains(reply.text, p) for p in want)
            checks.append(Check("reply_contains_any", ok, reply.text, turn))
        elif kind == "reply_not_contains":
            bad = [p for p in want if _contains(reply.text, p)]
            checks.append(Check("reply_not_contains", not bad, f"{bad} in: {reply.text}", turn))
        else:
            raise ValueError(f"unknown turn check {kind}")
    return checks


def repeat_question_checks(m: ConversationManager) -> list[Check]:
    """AC3: no question about a field that was already answered/confirmed/declined."""
    problems = []
    for tl in m.turn_logs:
        if tl.phase_before != Phase.SCREENING.value or tl.ask_kind == AskKind.CONFIRM.value:
            continue
        if tl.phase_after == Phase.CONFIRMATION.value:
            continue  # the read-back legitimately mentions answered fields
        settled = set(tl.settled)
        if tl.asked_field and tl.asked_field in settled and tl.ask_kind == AskKind.QUESTION.value:
            problems.append(f"turn {tl.turn}: labelled ask of settled {tl.asked_field}")
        questions = " ".join(s for s in re.split(r"(?<=[.!?])\s+", tl.reply) if s.endswith("?"))
        for name in settled - {tl.asked_field}:
            if any(p in questions.lower() for p in FIELD_PHRASES.get(name, [])):
                problems.append(f"turn {tl.turn}: reply asks settled {name}: {tl.reply!r}")
    return [Check("no_repeat_questions", not problems, "; ".join(problems))]


def asked_fields(m: ConversationManager, from_turn: int = 0) -> set[str]:
    return {tl.asked_field for tl in m.turn_logs if tl.asked_field and tl.turn >= from_turn}


async def final_checks(
    m: ConversationManager, final: dict[str, Any], llm: LLMProvider, job: JobConfig
) -> list[Check]:
    checks: list[Check] = []
    result = await m.end(EndReason.HANGUP)
    s = m.state
    for kind, want in final.items():
        if kind == "end_reason":
            checks.append(Check(kind, result.end_reason.value == want, result.end_reason.value))
        elif kind == "status":
            got = result.screening_status.value
            checks.append(Check(kind, got == want, got))
        elif kind == "opted_out":
            checks.append(Check(kind, result.opted_out is want, str(result.opted_out)))
        elif kind == "ended_by_turn":
            checks.append(Check(kind, s.ended and s.turn_count <= want, f"turns {s.turn_count}"))
        elif kind == "callback_iso_prefix":
            got = result.callback.get("time_iso") or ""
            checks.append(Check(kind, got.startswith(want), got))
        elif kind == "never_asked":
            hit = asked_fields(m) & set(want)
            checks.append(Check(kind, not hit, f"asked {hit}"))
        elif kind == "never_asked_after":
            hit = {k for k, t in want.items() if k in asked_fields(m, from_turn=t)}
            checks.append(Check(kind, not hit, f"asked again {hit}"))
        elif kind == "never_asked_any":
            hit = asked_fields(m)
            checks.append(Check(kind, not hit, f"asked {hit}"))
        elif kind == "no_collected":
            collected = {k: v for k, v in result.collected_data.items() if v is not None}
            checks.append(Check(kind, not collected, f"collected {collected}"))
        elif kind == "candidate_questions_min":
            checks.append(
                Check(
                    kind, len(result.candidate_questions) >= want, str(result.candidate_questions)
                )
            )
        elif kind == "fields":
            for name, spec in want.items():
                checks += check_field(name, s.fields[name], spec, None)
        elif kind == "summary":
            summary = await generate_summary(
                result, candidate_name=m.candidate.name, job_title=job.job_title, llm=llm
            )
            checks.append(Check("summary_generated", bool(summary.text), summary.text))
            checks.append(Check("summary_neutral", not JUDGMENT.search(summary.text), summary.text))
        else:
            raise ValueError(f"unknown final check {kind}")
    return checks


async def run_scenario(
    scenario: dict[str, Any], job: JobConfig, llm: LLMProvider, settings: Settings, run: int
) -> RunResult:
    rr = RunResult(scenario["id"], run)
    started = time.perf_counter()
    now = datetime.fromisoformat(scenario.get("now", DEFAULT_NOW))

    class Clock:
        def now(self) -> datetime:
            return now

    m = ConversationManager(
        job,
        CandidateContext(**scenario.get("candidate", {"name": "Test Candidate"})),
        llm,
        Clock(),
        prior_fields=scenario.get("prior_fields"),
        timeout_s=settings.openai_timeout_s,
    )
    try:
        await m.start()
        for i, t in enumerate(scenario["turns"], start=1):
            if m.state.ended:
                if t.get("expect"):
                    rr.checks.append(Check("reached_turn", False, "conversation ended early", i))
                break
            reply = await m.handle_utterance(t["say"], stt_confidence=t.get("stt_confidence"))
            if t.get("expect"):
                rr.checks += check_turn(m, reply, t["expect"], i)
        rr.checks += repeat_question_checks(m)
        rr.checks += await final_checks(m, scenario.get("final", {}), llm, job)
    except Exception as exc:  # report, don't abort the whole eval
        rr.error = f"{type(exc).__name__}: {exc}"
    for tl in m.turn_logs:
        ok_calls = [c for c in tl.llm_calls if c.ok]
        rr.latencies_ms += [c.latency_ms for c in ok_calls]
        rr.llm_calls += len(tl.llm_calls)
        rr.retries += sum(1 for c in tl.llm_calls if not c.ok)
        rr.input_tokens += sum(c.input_tokens for c in ok_calls)
        rr.cached_tokens += sum(c.cached_tokens for c in ok_calls)
        rr.output_tokens += sum(c.output_tokens for c in ok_calls)
        rr.guardrails += tl.guardrails
        rr.turn_logs.append(
            {k: v for k, v in asdict(tl).items() if k not in ("llm_calls", "prompt_version")}
        )
    failed_turns = sum(1 for g in rr.guardrails if g.startswith("llm_error"))
    rr.checks.append(Check("valid_json", failed_turns == 0, f"{failed_turns} turns failed"))
    rr.transcript = [asdict(e) for e in m.transcript]
    rr.duration_s = round(time.perf_counter() - started, 2)
    return rr


TURN_KEYS = {
    "fields",
    "asked",
    "not_asked",
    "ask_kind",
    "phase",
    "end_call",
    "reply_contains_any",
    "reply_not_contains",
}
FINAL_KEYS = {
    "end_reason",
    "status",
    "opted_out",
    "ended_by_turn",
    "callback_iso_prefix",
    "never_asked",
    "never_asked_after",
    "never_asked_any",
    "no_collected",
    "candidate_questions_min",
    "fields",
    "summary",
}
FIELD_KEYS = {
    "value",
    "value_contains",
    "value_between",
    "status",
    "previous_contains",
    "needs_confirmation",
    "meta_days",
}


def validate_scenario(sc: dict[str, Any], known_fields: set[str]) -> list[str]:
    """Problems in a scenario file (unknown check names or fields). Empty list = fine."""
    problems = []

    def fields(spec: dict[str, Any], where: str) -> None:
        for name, checks in spec.items():
            if name not in known_fields:
                problems.append(f"{where}: unknown field {name}")
            problems.extend(f"{where}: unknown field check {k}" for k in set(checks) - FIELD_KEYS)

    for key in ("id", "turns"):
        if key not in sc:
            problems.append(f"missing {key}")
    for i, t in enumerate(sc.get("turns", []), start=1):
        if not isinstance(t.get("say"), str):
            problems.append(f"turn {i}: missing say")
        exp = t.get("expect", {})
        problems.extend(f"turn {i}: unknown check {k}" for k in set(exp) - TURN_KEYS)
        fields(exp.get("fields", {}), f"turn {i}")
    final = sc.get("final", {})
    problems.extend(f"final: unknown check {k}" for k in set(final) - FINAL_KEYS)
    fields(final.get("fields", {}), "final")
    for k in sc.get("prior_fields", {}):
        if k not in known_fields:
            problems.append(f"prior_fields: unknown field {k}")
    return problems


def load_scenarios(selected: list[str] | None) -> list[dict[str, Any]]:
    out = []
    for path in sorted(SCENARIOS.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if not selected or any(data["id"].startswith(s) for s in selected):
            out.append(data)
    return out


def percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def summarize(
    runs: list[RunResult], model: str, prices: tuple[float, float, float] | None
) -> dict[str, Any]:
    by_scenario: dict[str, list[RunResult]] = {}
    for r in runs:
        by_scenario.setdefault(r.scenario, []).append(r)
    scenarios = {}
    for sid, rs in by_scenario.items():
        safety_ok = all(c.ok for r in rs for c in r.checks if c.safety) and not any(
            r.error for r in rs
        )
        scenarios[sid] = {
            "runs": len(rs),
            "passed": sum(r.passed for r in rs),
            "pass_rate": round(sum(r.passed for r in rs) / len(rs), 3),
            "safety_ok": safety_ok,
            "failures": [
                {"run": r.run, "error": r.error}
                if r.error
                else {"run": r.run, "check": c.name, "turn": c.turn, "detail": c.detail[:300]}
                for r in rs
                for c in ([Check("error", False)] if r.error else [c for c in r.checks if not c.ok])
            ],
        }
    latencies = [lat for r in runs for lat in r.latencies_ms]
    calls = sum(r.llm_calls for r in runs)
    retries = sum(r.retries for r in runs)
    total_in = sum(r.input_tokens for r in runs)
    cached = sum(r.cached_tokens for r in runs)
    total_out = sum(r.output_tokens for r in runs)
    convs = len(runs)
    cost = None
    if prices:
        p_in, p_cached, p_out = prices
        cost_total = ((total_in - cached) * p_in + cached * p_cached + total_out * p_out) / 1e6
        cost = {
            "total_usd": round(cost_total, 4),
            "per_conversation_usd": round(cost_total / convs, 5),
        }
    nonsafety = [c for r in runs for c in r.checks if not c.safety]
    return {
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "conversations": convs,
        "overall_pass_rate": round(sum(r.passed for r in runs) / convs, 3) if convs else 0,
        "non_safety_check_pass_rate": round(sum(c.ok for c in nonsafety) / len(nonsafety), 3)
        if nonsafety
        else 1.0,
        "safety_all_ok": all(s["safety_ok"] for s in scenarios.values()),
        "llm": {
            "calls": calls,
            "retries": retries,
            "retry_rate": round(retries / calls, 4) if calls else 0,
            "latency_ms": {
                "p50": round(percentile(latencies, 0.5)),
                "p95": round(percentile(latencies, 0.95)),
                "mean": round(statistics.mean(latencies)) if latencies else 0,
                "max": max(latencies, default=0),
            },
            "tokens": {
                "input": total_in,
                "cached_input": cached,
                "output": total_out,
                "per_call_input": round(total_in / max(1, calls - retries)),
                "per_call_output": round(total_out / max(1, calls - retries)),
            },
            "guardrail_events": sorted({g for r in runs for g in r.guardrails}),
            "reprompts": sum(1 for r in runs for g in r.guardrails if g.startswith("reprompt")),
            "template_fallbacks": sum(
                1 for r in runs for g in r.guardrails if g.startswith("template")
            ),
        },
        "cost": cost,
        "scenarios": scenarios,
    }


def print_report(summary: dict[str, Any]) -> None:
    print(f"\nModel {summary['model']}  prompt {summary['prompt_version']}")
    print(f"{'scenario':32} {'pass':>6} {'safety':>7}")
    for sid, s in summary["scenarios"].items():
        print(f"{sid:32} {s['passed']}/{s['runs']:<4} {'ok' if s['safety_ok'] else 'FAIL':>7}")
        for f in s["failures"][:6]:
            print(f"    - {f}")
    llm = summary["llm"]
    print(
        f"\nlatency p50={llm['latency_ms']['p50']}ms p95={llm['latency_ms']['p95']}ms  "
        f"calls={llm['calls']} retry_rate={llm['retry_rate']}  reprompts={llm['reprompts']} "
        f"templates={llm['template_fallbacks']}"
    )
    print(f"tokens {llm['tokens']}  cost {summary['cost']}")
    safety = "OK" if summary["safety_all_ok"] else "FAIL"
    print(
        f"overall pass {summary['overall_pass_rate']}  non-safety checks "
        f"{summary['non_safety_check_pass_rate']}  safety {safety}"
    )


async def evaluate(
    *,
    selected: list[str] | None = None,
    runs: int = 3,
    model: str | None = None,
    effort: str | None = None,
    concurrency: int = 4,
    prices: tuple[float, float, float] | None = None,
    write: bool = True,
) -> dict[str, Any]:
    settings = load_settings()
    if model:
        settings = settings.model_copy(update={"openai_model": model})
    if effort:
        settings = settings.model_copy(update={"openai_reasoning_effort": effort})
    llm = create_llm_provider(settings)
    job = JobConfig.from_dict(yaml.safe_load((HERE / "job.yaml").read_text()))
    scenarios = load_scenarios(selected)
    sem = asyncio.Semaphore(concurrency)

    async def one(sc: dict[str, Any], run: int) -> RunResult:
        async with sem:
            return await run_scenario(sc, job, llm, settings, run)

    try:
        results = await asyncio.gather(
            *(one(sc, r) for sc in scenarios for r in range(1, runs + 1))
        )
    finally:
        await llm.aclose()
    summary = summarize(list(results), settings.openai_model or "", prices)
    if write:
        RESULTS.mkdir(exist_ok=True)
        safe_model = re.sub(r"[^\w.-]", "_", summary["model"])
        path = RESULTS / f"{datetime.now(UTC):%Y-%m-%d-%H%M}-{safe_model}.json"
        path.write_text(
            json.dumps(
                {"summary": summary, "runs": [asdict(r) for r in results]}, indent=1, default=str
            )
        )
        summary["results_file"] = str(path)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("-s", "--scenario", action="append", help="scenario id prefix (repeatable)")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--model")
    parser.add_argument("--effort", help="reasoning effort, e.g. none")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--price-in", type=float, help="USD per 1M input tokens")
    parser.add_argument("--price-cached", type=float, help="USD per 1M cached input tokens")
    parser.add_argument("--price-out", type=float, help="USD per 1M output tokens")
    args = parser.parse_args()
    prices = None
    if args.price_in is not None and args.price_out is not None:
        prices = (args.price_in, args.price_cached or args.price_in, args.price_out)
    summary = asyncio.run(
        evaluate(
            selected=args.scenario,
            runs=args.runs,
            model=args.model,
            effort=args.effort,
            concurrency=args.concurrency,
            prices=prices,
        )
    )
    print_report(summary)
    print(f"\nresults: {summary.get('results_file')}")


if __name__ == "__main__":
    main()
