"""Dry run of the post-call final pass on stored conversations (phase-07 P7-T1). Writes nothing.

    python -m app.scripts.final_pass_check [--attempt <uuid>] [--limit 10]

For each conversation with a stored result: run the LLM final pass over its transcript, reconcile
with the live state, and print what finalization would store (changes, conflicts, rejected
values, screening status). Calls the real OpenAI API (about a cent per conversation).
"""

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import select

from app.agent.conversation_manager import ScreeningResult
from app.agent.final_pass import finalize, run_final_pass
from app.config import get_settings
from app.database.connection import dispose_engine, get_sessionmaker, init_engine
from app.database.models import CallAttempt, Candidate, Conversation, Job
from app.providers.llm import create_llm_provider
from app.services.finalization_service import job_questions


async def main(attempt: str | None, limit: int) -> int:
    settings = get_settings()
    init_engine(settings.database_url.get_secret_value())
    llm = create_llm_provider(settings)
    try:
        async with get_sessionmaker()() as session:
            query = (
                select(Conversation, CallAttempt, Candidate, Job)
                .join(CallAttempt, CallAttempt.id == Conversation.call_attempt_id)
                .join(Candidate, Candidate.id == CallAttempt.candidate_id)
                .join(Job, Job.id == Candidate.job_id)
                .where(Conversation.extracted_data.has_key("result"))
                .order_by(Conversation.created_at.desc())
                .limit(limit)
            )
            if attempt:
                query = query.where(CallAttempt.id == uuid.UUID(attempt))
            rows = (await session.execute(query)).all()
        changed = 0
        for conv, att, _candidate, job in rows:
            result = ScreeningResult.from_dict(conv.extracted_data["result"])
            result.transcript = list(conv.transcript or [])
            questions = job_questions(job)
            output = await run_final_pass(llm, result.transcript, questions)
            out = finalize(result, questions, output)
            print(f"\n=== attempt {att.id} ({att.created_at:%Y-%m-%d %H:%M} UTC) ===")
            print(
                f"live status: {result.screening_status.value} → final: "
                f"{out.status.value if out.status else 'unchanged'}"
                f"   final pass ran: {out.final_pass_ran}"
            )
            for key, f in out.fields.items():
                live = (result.fields.get(key) or {}).get("value")
                mark = "  " if f.source != "final_pass" else "→ "
                if f.source == "final_pass":
                    changed += 1
                print(f"  {mark}{key:<24} live={live!r:<28} final={f.value!r} [{f.status}]")
            for key, c in out.conflicts.items():
                print(f"  CONFLICT {key}: final pass {c['final_value']!r} — {c['reason']}")
            for key, why in out.rejected.items():
                print(f"  rejected {key}: {why}")
        print(f"\n{len(rows)} conversations, {changed} values taken from the final pass")
        return 0
    finally:
        await llm.aclose()
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.attempt, args.limit)))
