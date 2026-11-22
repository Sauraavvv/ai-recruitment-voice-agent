"""Telephonic round: how fast (and how right) the live-turn model is, before a real call.

    python -m app.scripts.round_bench [--runs 3] [--requirement <uuid>]

Sends the turns a call would send (identity, permission, a full answer, a thin answer, a
question about the role, a refusal, a callback, the goodbye) with the requirement's approved
questions and JD, through the same provider and settings the call uses (GROQ_CALL_*). No phone
call is placed and nothing is written. Prints each turn's latency and kind, then p50 / p95 and
how many turns would have hit the call's time limit (GROQ_CALL_TIMEOUT_S + 1 s: the agent says
a filler and moves on).
"""

import argparse
import asyncio
import sys
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.agent.telephonic_manager import MAX_OUTPUT_TOKENS
from app.agent.telephonic_prompts import Stage, TelephonicContext, TelephonicTurn, build_messages
from app.config import get_settings
from app.database.connection import dispose_engine, get_sessionmaker, init_engine
from app.database.models import QuestionSet, Requirement
from app.database.models.enums import QuestionSetStatus
from app.providers.llm import create_call_llm
from app.providers.llm.base import LLMError
from app.services import telephonic_call

BENCH_TIMEOUT_S = 20.0  # generous: the point is to see the real spread


def turns(ctx: TelephonicContext) -> list[tuple[Stage, str, str]]:
    """(stage, what the candidate says, the kind we expect)"""
    total = len(ctx.questions)
    q1, q2, q3 = (ctx.questions + ctx.questions + ctx.questions)[:3]

    def ask(q: object, n: int, follow_up: bool = False) -> Stage:
        assert hasattr(q, "text") and hasattr(q, "rubric")
        return Stage(
            phase="question",
            question=q.text,
            rubric=q.rubric or None,
            question_number=n,
            total_questions=total,
            follow_up_allowed=not follow_up,
        )

    return [
        (Stage(phase="identity", total_questions=total), "Yes, speaking.", "identity"),
        (Stage(phase="permission", total_questions=total), "Yes sure, go ahead.", "permission"),
        (
            ask(q1, 1),
            "I would split the documents into chunks, create embeddings, store them in a "
            "vector database like Pinecone, and at query time fetch the closest chunks and "
            "give them to the model along with the question.",
            "answer",
        ),
        (ask(q1, 1), "Yes, I have done that before.", "partial"),
        (ask(q2, 2), "Before that, what is the salary for this role?", "asks_question"),
        (ask(q2, 2), "I'd rather not answer that one.", "declined"),
        (ask(q3, 3), "Sorry, I don't know the answer to that.", "dont_know"),
        (ask(q3, 3), "I'm driving right now, can you call me tomorrow at 5 pm?", "callback"),
        (Stage(phase="closing", total_questions=total), "No, that's all. Thank you.", "any"),
    ]


def matches(expected: str, turn: TelephonicTurn) -> bool:
    if expected == "identity":
        return turn.identity_confirmed is True
    if expected == "permission":
        return turn.permission_granted is True
    if expected == "partial":
        return turn.kind == "partial" and bool(turn.follow_up)
    if expected == "callback":
        return turn.kind == "callback" and bool(turn.callback_time_iso)
    return expected == "any" or turn.kind == expected


async def load(requirement_id: str | None) -> TelephonicContext:
    async with get_sessionmaker()() as session:
        stmt = (
            select(QuestionSet)
            .where(QuestionSet.status == QuestionSetStatus.APPROVED.value)
            .order_by(QuestionSet.approved_at.desc())
        )
        if requirement_id:
            stmt = stmt.where(QuestionSet.requirement_id == uuid.UUID(requirement_id))
        question_set = (await session.execute(stmt)).scalars().first()
        if question_set is None:
            raise SystemExit("No approved question set: approve the questions first")
        requirement = await session.get(Requirement, question_set.requirement_id)
        assert requirement is not None
        return await telephonic_call.for_question_set(session, requirement, question_set)


async def main(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.groq_keys:
        print("GROQ_API_KEYS is not set")
        return 2
    init_engine(settings.database_url.get_secret_value())
    try:
        ctx = await load(args.requirement)
    finally:
        await dispose_engine()
    limit_s = settings.groq_call_timeout_s + 1
    print(
        f"{ctx.job_title}: {len(ctx.questions)} questions (v{ctx.version}), JD "
        f"{len(ctx.job_description)} chars · model {settings.groq_model} · effort "
        f"{settings.groq_call_reasoning_effort} · call limit {limit_s:.0f} s · runs {args.runs}"
    )
    llm = create_call_llm(settings)
    latencies: list[float] = []
    right = total = failed = 0
    try:
        for run in range(1, args.runs + 1):
            for stage, said, expected in turns(ctx):
                messages = build_messages(ctx, stage, [], said, datetime.now(UTC))
                started = time.perf_counter()
                try:
                    result = await llm.structured(
                        messages,
                        TelephonicTurn,
                        timeout_s=BENCH_TIMEOUT_S,
                        max_tokens=MAX_OUTPUT_TOKENS,
                    )
                except LLMError as exc:
                    failed += 1
                    print(f"run {run} {expected:<14} FAILED {type(exc).__name__}")
                    continue
                ms = (time.perf_counter() - started) * 1000
                latencies.append(ms)
                ok = matches(expected, result.value)
                right += ok
                total += 1
                extra = result.value.follow_up or result.value.reply or ""
                print(
                    f"run {run} {expected:<14} {ms:6.0f} ms  kind={result.value.kind:<14} "
                    f"{'ok ' if ok else 'MISS'} out={result.output_tokens:<4} {extra[:70]}"
                )
    finally:
        await llm.aclose()
    if latencies:
        values = sorted(latencies)
        p50 = values[len(values) // 2]
        p95 = values[min(len(values) - 1, round(0.95 * (len(values) - 1)))]
        over = sum(v > limit_s * 1000 for v in values)
        print(
            f"\nlatency p50 {p50:.0f} ms · p95 {p95:.0f} ms · max {values[-1]:.0f} ms · "
            f"over the {limit_s:.0f} s limit: {over}/{len(values)}"
        )
    print(f"right kind: {right}/{total} · failed calls: {failed}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--requirement", help="requirement id (default: latest approved set)")
    sys.exit(asyncio.run(main(parser.parse_args())))
