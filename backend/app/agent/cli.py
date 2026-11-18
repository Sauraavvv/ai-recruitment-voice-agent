"""Text chat with the screening agent (P2-T11). Uses the real OpenAI API.

    python -m app.agent.cli                          # active job from the database
    python -m app.agent.cli --job-id <uuid> --name "Test Candidate"
    python -m app.agent.cli --job-file job.yaml      # no database needed
    python -m app.agent.cli --replay app/tests/agent_eval/scenarios/s14_happy_path.yaml

Type /quit to hang up, /silence to simulate a silence timeout, /state to print the state.
"""

import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

import yaml

from app.agent.conversation_manager import AgentReply, ConversationManager, SystemClock
from app.agent.prompts import CandidateContext, JobConfig
from app.agent.state import EndReason
from app.config import load_settings
from app.providers.llm import create_llm_provider
from app.services.summary_service import generate_summary
from app.utils.log import configure_logging


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


async def load_job(args: argparse.Namespace, database_url: str) -> JobConfig:
    if args.job_file:
        return JobConfig.from_dict(yaml.safe_load(Path(args.job_file).read_text()))
    from app.database.connection import dispose_engine, get_sessionmaker, init_engine
    from app.services import job_service

    init_engine(database_url)
    try:
        async with get_sessionmaker()() as session:
            job_id = uuid.UUID(args.job_id) if args.job_id else None
            return JobConfig.from_job(await job_service.resolve(session, job_id))
    finally:
        await dispose_engine()


def show(reply: AgentReply, *, verbose: bool) -> None:
    print(f"\n\033[1mAgent:\033[0m {reply.text}")
    if not verbose or reply.log is None:
        return
    lg = reply.log
    calls = lg.llm_calls
    meta = [f"phase={reply.phase.value}", f"action={reply.action}"]
    if reply.asked_field:
        meta.append(f"asks={reply.asked_field} ({reply.ask_kind.value if reply.ask_kind else ''})")
    if calls:
        meta.append(f"llm={'+'.join(str(c.latency_ms) for c in calls)}ms")
        meta.append(
            f"tokens={sum(c.input_tokens for c in calls)}/{sum(c.output_tokens for c in calls)}"
        )
        meta.append(f"cached={sum(c.cached_tokens for c in calls)}")
    if lg.guardrails:
        meta.append(f"guardrails={lg.guardrails}")
    print("\033[2m  " + "  ".join(meta) + "\033[0m")
    if reply.state_diff:
        print("\033[2m  diff: " + json.dumps(reply.state_diff, default=str) + "\033[0m")
    if lg.dropped or lg.invalid:
        print(f"\033[33m  dropped={lg.dropped} invalid={lg.invalid}\033[0m")


async def run(args: argparse.Namespace) -> int:
    settings = load_settings()
    configure_logging("WARNING")
    if args.model:
        settings = settings.model_copy(update={"openai_model": args.model})
    llm = create_llm_provider(settings)
    job = await load_job(args, settings.database_url.get_secret_value())

    scripted: list[str] | None = None
    now_text = args.now
    if args.replay:
        scenario = yaml.safe_load(Path(args.replay).read_text())
        scripted = [t["say"] for t in scenario["turns"]]
        now_text = now_text or scenario.get("now")
        args.name = scenario.get("candidate", {}).get("name", args.name)
    clock = FixedClock(datetime.fromisoformat(now_text)) if now_text else SystemClock()

    manager = ConversationManager(
        job,
        CandidateContext(name=args.name),
        llm,
        clock,
        timeout_s=settings.openai_timeout_s,
    )
    print(f"Job: {job.job_title} at {job.company_name}  |  model: {settings.openai_model}")
    show(await manager.start(), verbose=args.verbose)
    try:
        while not manager.state.ended:
            if scripted is not None:
                if not scripted:
                    break
                text = scripted.pop(0)
                print(f"\n\033[1mCandidate:\033[0m {text}")
            else:
                try:
                    text = input("\nYou: ")
                except EOFError:
                    break
            if text.strip() == "/quit":
                break
            if text.strip() == "/state":
                print(json.dumps(manager.state.plan_json(), indent=2, default=str))
                continue
            if text.strip() == "/silence":
                show(await manager.handle_silence(1), verbose=args.verbose)
                continue
            show(await manager.handle_utterance(text), verbose=args.verbose)
    finally:
        result = await manager.end(EndReason.HANGUP)
        print("\n--- result ---")
        print(f"end_reason={result.end_reason.value}  status={result.screening_status.value}")
        print(json.dumps(result.collected_data, indent=2, default=str))
        if result.callback.get("requested"):
            print(f"callback: {result.callback}")
        summary = await generate_summary(
            result, candidate_name=args.name, job_title=job.job_title, llm=llm
        )
        print(f"\nsummary ({summary.generated_by}): {summary.text}")
        await llm.aclose()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Text chat with the screening agent")
    parser.add_argument("--job-id")
    parser.add_argument("--job-file")
    parser.add_argument("--name", default="Test Candidate")
    parser.add_argument("--replay", help="scenario YAML to replay instead of typing")
    parser.add_argument("--model", help="override OPENAI_MODEL")
    parser.add_argument("--now", help="fixed ISO time for callback resolution")
    parser.add_argument("-q", "--quiet", dest="verbose", action="store_false")
    return asyncio.run(run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
