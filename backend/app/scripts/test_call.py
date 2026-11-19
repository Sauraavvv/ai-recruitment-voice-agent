"""Place one real test call and follow it (phase-05 PoC, phase-06 screening calls).

    python -m app.scripts.test_call --phone +9198XXXXXXXX [--mode screen|full|listen]
    python -m app.scripts.test_call --candidate-id <uuid>

Only call testers who agreed to it, whose numbers are verified in the Exotel dashboard.
`--phone` creates (or reuses) a candidate for the tester under the active job, with the tester's
consent recorded as a manual entry. The calling window is skipped for these test calls.

Modes (what the stream does once answered):
  screen  the screening conversation (default; what every real call does)
  full    PoC line check: clip → beep → 15 s echo → stop (`clear`) test → goodbye → hang up
  listen  PoC: clip, then record until the caller hangs up

After a screening call it prints the transcript, the stored fields, the summary (written by the
worker's `finalize_call` a few seconds later) and the per-turn latency table.
"""

import argparse
import asyncio
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from app.database.connection import dispose_engine, get_sessionmaker, init_engine
from app.database.models import CallAttemptType, Candidate, ConsentSource
from app.repositories import call_repo, candidate_repo
from app.services import call_service, call_state, job_service
from app.utils.phone import normalize_phone
from app.utils.queue import close_queue, enqueue_initiate_call, init_queue
from app.utils.redis import close_redis, get_redis, init_redis
from app.voice.websocket_handler import POC_MODE_KEY, POC_MODES

WATCH_LIMIT_S = 20 * 60


async def _candidate_for_phone(phone: str, name: str) -> uuid.UUID:
    e164 = normalize_phone(phone).e164
    if e164 is None:
        raise SystemExit(f"Not a valid phone number: {phone}")
    async with get_sessionmaker()() as session:
        existing = await candidate_repo.get_by_phone(session, e164)
        if existing is not None:
            if existing.deleted_at is not None:
                raise SystemExit("That number belongs to a deleted candidate")
            return existing.id
        job = await job_service.get_active(session)
        candidate = Candidate(
            name=name,
            phone=e164,
            job_id=job.id,
            applied_role=job.job_title,
            source="phase-5 test call",
            recruiter_notes="Telephony PoC tester; agreed to receive test calls.",
            consent_source=ConsentSource.MANUAL,
            consent_at=datetime.now(UTC),
        )
        session.add(candidate)
        await session.commit()
        print(f"Created tester candidate {candidate.id}")
        return candidate.id


async def _watch(attempt_id: uuid.UUID) -> int:
    settings = get_settings()
    seen: tuple[str | None, ...] = ()
    started = time.monotonic()
    while time.monotonic() - started < WATCH_LIMIT_S:
        async with get_sessionmaker()() as session:
            attempt = await call_repo.get(session, attempt_id)
        assert attempt is not None
        state = (
            attempt.call_status,
            attempt.provider_status,
            attempt.provider_call_id,
            attempt.end_reason,
        )
        if state != seen:
            seen = state
            print(
                f"{time.monotonic() - started:7.1f}s  status={attempt.call_status:<12} "
                f"provider={attempt.provider_status or '-':<12} "
                f"sid={attempt.provider_call_id or '-'} "
                f"end_reason={attempt.end_reason or '-'} failure={attempt.failure_reason or '-'}"
            )
        if call_state.is_terminal(attempt.call_status):
            print(f"duration={attempt.duration_seconds}s recording={attempt.recording_url or '-'}")
            capture = Path(settings.telephony_capture_dir or "") / f"{attempt_id}_stream.json"
            for _ in range(10):
                if capture.exists():
                    break
                await asyncio.sleep(1)
            await _print_screening(attempt_id)
            if capture.exists():
                summary = json.loads(capture.read_text())["summary"]
                print(json.dumps(summary, indent=2))
                print(f"capture: {capture} and {capture.with_name(f'{attempt_id}_in.wav')}")
            else:
                print("no stream capture (the stream never connected?)")
            return 0
        await asyncio.sleep(1)
    print("still not finished; check `make logs`")
    return 1


async def _print_screening(attempt_id: uuid.UUID) -> None:
    from sqlalchemy import select

    from app.agent.schemas import FieldName
    from app.database.models import Conversation

    async with get_sessionmaker()() as session:
        conv = (
            await session.execute(
                select(Conversation).where(Conversation.call_attempt_id == attempt_id)
            )
        ).scalar_one_or_none()
        attempt = await call_repo.get(session, attempt_id)
        if conv is None or attempt is None:
            return
        candidate = await session.get(Candidate, attempt.candidate_id)
        assert candidate is not None
        print("\n--- transcript ---")
        for entry in conv.transcript:
            print(f"{entry.get('speaker', '?'):>9}: {entry.get('text', '')}")
        print(f"\n--- stored on the candidate (screening_status={candidate.screening_status}) ---")
        for f in FieldName:
            print(f"  {f.value:<24} {getattr(candidate, f.value)!r}")
        print(f"\nend_reason={attempt.end_reason} failure={attempt.failure_reason or '-'}")
        metrics = (conv.extracted_data or {}).get("turn_metrics") or []
        if metrics:
            print("\n--- latency per turn (ms) ---")
            cols = ("turn", "ack", "stt_ms", "llm_ms", "tts_ms", "ack_ms", "total_ms", "merged")
            print("  ".join(f"{c:>8}" for c in cols))
            for m in metrics:
                cells = ("-" if m.get(c) is None else str(m.get(c)) for c in cols)
                print("  ".join(f"{cell:>8}" for cell in cells))
            print_percentiles(metrics)
        stats = (conv.extracted_data or {}).get("session") or {}
        if stats:
            keys = ("merges", "barge_ins", "backchannels_ignored", "clears", "max_loop_lag_ms")
            print({k: stats.get(k) for k in keys})
    for _ in range(15):  # the worker writes the summary just after the call
        async with get_sessionmaker()() as session_db:
            conv2 = (
                await session_db.execute(
                    select(Conversation).where(Conversation.call_attempt_id == attempt_id)
                )
            ).scalar_one_or_none()
        if conv2 is not None and conv2.summary:
            print(f"\n--- summary ---\n{conv2.summary}\n")
            return
        await asyncio.sleep(1)
    print("\n(no summary yet: is the worker running?)")


def print_percentiles(metrics: list[dict[str, object]]) -> None:
    for key in ("first_sound_ms", "total_ms", "stt_ms", "llm_ms", "tts_ms"):
        values = sorted(float(v) for m in metrics if isinstance(v := m.get(key), int | float))
        if values:
            p50 = values[len(values) // 2]
            p95 = values[min(len(values) - 1, round(0.95 * (len(values) - 1)))]
            print(f"  {key:<15} p50 {p50:6.0f}  p95 {p95:6.0f}  (n={len(values)})")


async def main(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.exotel_configured:
        print("Telephony is not configured: set EXOTEL_* and PUBLIC_BACKEND_URL in .env")
        return 2
    init_engine(settings.database_url.get_secret_value())
    init_redis(settings.redis_url.get_secret_value())
    await init_queue(settings.redis_url.get_secret_value())
    try:
        if args.candidate_id:
            candidate_id = uuid.UUID(args.candidate_id)
        else:
            candidate_id = await _candidate_for_phone(args.phone, args.name)

        async def enqueue(attempt_id: str) -> None:
            await get_redis().set(POC_MODE_KEY.format(attempt_id=attempt_id), args.mode, ex=3600)
            await enqueue_initiate_call(attempt_id, ignore_window=True)

        async with get_sessionmaker()() as session:
            (result,) = await call_service.start_calls(
                session,
                [candidate_id],
                settings,
                enqueue,
                attempt_type=CallAttemptType.MANUAL,
                ignore_window=True,
            )
        if not result.ok or result.attempt_id is None:
            print(f"Not started: {result.as_dict()['error']}")
            return 1
        print(f"Queued call attempt {result.attempt_id} (mode={args.mode})")
        return await _watch(result.attempt_id) if not args.no_watch else 0
    finally:
        await close_queue()
        await close_redis()
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--phone", help="tester's phone (verified in Exotel)")
    who.add_argument("--candidate-id")
    parser.add_argument("--name", default="Test Candidate")
    parser.add_argument("--mode", choices=POC_MODES, default="screen")
    parser.add_argument("--no-watch", action="store_true")
    sys.exit(asyncio.run(main(parser.parse_args())))
