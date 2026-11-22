"""Google Sheets synchronization: transactional outbox, drain, retries (phase-07 P7-T9, P7-T10).

PostgreSQL is the source of truth. Every candidate change adds a `sync_logs` row (`pending`) in
the same transaction (`record_change`); after the commit `request_sync` queues a drain. The
drain, under one Redis lock (`rcai:sheets:lock`):

  due rows (pending, or failed with next_attempt_at passed), up to BATCH candidates
    → snapshot their row ids → read the LATEST database state → one sheet upsert
    → success: those rows `success`; error: `failed` with backoff (transient) or
      `failed` + integration status `error` (permanent)
  repeat until nothing is due

Several pending rows for one candidate are satisfied by one sync. A Sheets outage only leaves
rows pending/failed: the database is never rolled back or blocked.
"""

import json
import random
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import (
    CallAttempt,
    CallPurpose,
    Candidate,
    Conversation,
    SyncLog,
    SyncStatus,
)
from app.services.sheet_mapping import Cell, counts_as_attempt, to_sheet_row
from app.services.sheets_service import SheetsError, UpsertResult
from app.services.summary_service import pick_summary_conversation
from app.utils.log import get_logger
from app.utils.redis import KEY_PREFIX

logger = get_logger(__name__)

PROVIDER = "google_sheets"
LOCK_KEY = f"{KEY_PREFIX}sheets:lock"
STATUS_KEY = f"{KEY_PREFIX}sheets:status"
CHECK_CACHE_KEY = f"{KEY_PREFIX}sheets:check"
LOCK_TIMEOUT_S = 300
LOCK_WAIT_S = 30
BATCH = 100
MAX_ROUNDS = 20  # per job; a bigger backlog continues in the next job
# Transient failures: retry after 1 min, 5 min, 15 min, 1 h, 6 h (+ jitter); then failed for good
BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(hours=1),
    timedelta(hours=6),
)
# Permanent failures (no permission, wrong sheet, header changed) are retried slowly, so fixing
# the sheet recovers on its own
PERMANENT_RETRY = timedelta(minutes=30)
JITTER = 0.2  # up to +20% on each wait, so retries of many rows don't arrive together


def jittered(delay: timedelta) -> timedelta:
    return delay * (1 + random.uniform(0, JITTER))  # noqa: S311 (not for security)


PENDING_STALE = timedelta(minutes=5)


# --- Outbox -----------------------------------------------------------------------------------


def record_change(session: AsyncSession, candidate_id: uuid.UUID) -> SyncLog:
    """Add a pending outbox row. Call before the commit that changes the candidate."""
    row = SyncLog(
        candidate_id=candidate_id, provider=PROVIDER, sync_status=SyncStatus.PENDING.value
    )
    session.add(row)
    return row


async def backfill(session: AsyncSession) -> int:
    """An outbox row for every active candidate (first fill of a new sheet), committed.
    Returns how many were queued."""
    ids = list(
        (
            await session.execute(select(Candidate.id).where(Candidate.deleted_at.is_(None)))
        ).scalars()
    )
    record_changes(session, ids)
    await session.commit()
    return len(ids)


def record_changes(session: AsyncSession, candidate_ids: Iterable[uuid.UUID]) -> None:
    for cid in dict.fromkeys(candidate_ids):
        record_change(session, cid)


class JobPool(Protocol):
    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> Any: ...


async def request_sync(settings: Settings, pool: JobPool | None = None) -> bool:
    """Queue a drain after a commit. Best effort: the reconciler catches anything missed.
    Returns whether a job was queued. Only the key file is checked here: the sheet itself may
    be set on the Settings page (the drain checks the effective settings)."""
    if not settings.google_service_account_json:
        return False
    try:
        if pool is None:
            from app.utils.queue import get_queue

            pool = get_queue()
        await pool.enqueue_job("sync_sheets")
    except Exception:
        logger.warning("sheets_sync_enqueue_failed", exc_info=True)
        return False
    return True


# --- Integration status (shared by the API and the worker through Redis) ---------------------


async def get_status(redis: Redis) -> dict[str, Any]:
    raw = await redis.get(STATUS_KEY)
    return json.loads(raw) if raw else {}


async def set_status(redis: Redis, **changes: Any) -> None:
    status = await get_status(redis)
    status.update(changes)
    await redis.set(STATUS_KEY, json.dumps(status, default=str))


# --- Drain ------------------------------------------------------------------------------------


class SheetWriter(Protocol):
    async def upsert(self, rows: dict[str, list[Cell]]) -> UpsertResult: ...


def _due(now: datetime) -> Any:
    return SyncLog.provider == PROVIDER, or_(
        SyncLog.sync_status == SyncStatus.PENDING.value,
        (SyncLog.sync_status == SyncStatus.FAILED.value) & (SyncLog.next_attempt_at <= now),
    )


async def due_candidates(
    session: AsyncSession, now: datetime, limit: int = BATCH
) -> list[uuid.UUID]:
    rows = await session.execute(
        select(SyncLog.candidate_id)
        .where(*_due(now))
        .group_by(SyncLog.candidate_id)
        .order_by(func.min(SyncLog.created_at))
        .limit(limit)
    )
    return [r[0] for r in rows]


async def build_rows(
    session: AsyncSession, candidate_ids: list[uuid.UUID], settings: Settings
) -> dict[str, list[Cell]]:
    """The sheet rows for these candidates from the current database state."""
    tz = ZoneInfo(settings.app_timezone)
    candidates = (
        (await session.execute(select(Candidate).where(Candidate.id.in_(candidate_ids))))
        .scalars()
        .all()
    )
    # The sheet is about screening: telephonic round calls don't change it (phase-11 step 6b)
    screening_only = CallAttempt.purpose == CallPurpose.SCREENING.value
    attempts = (
        (
            await session.execute(
                select(CallAttempt)
                .where(CallAttempt.candidate_id.in_(candidate_ids), screening_only)
                .order_by(CallAttempt.attempt_number)
            )
        )
        .scalars()
        .all()
    )
    latest: dict[uuid.UUID, CallAttempt] = {}
    count: dict[uuid.UUID, int] = {}
    for a in attempts:
        latest[a.candidate_id] = a  # ordered by attempt_number: the last one wins
        if counts_as_attempt(a.call_status):
            count[a.candidate_id] = count.get(a.candidate_id, 0) + 1
    conversations = await session.execute(
        select(Conversation, CallAttempt.candidate_id)
        .join(CallAttempt, CallAttempt.id == Conversation.call_attempt_id)
        .where(
            CallAttempt.candidate_id.in_(candidate_ids),
            Conversation.finalized_at.is_not(None),
            screening_only,
        )
        .order_by(Conversation.finalized_at)
    )
    by_candidate: dict[uuid.UUID, list[Conversation]] = {}
    for conv, cid in conversations:
        by_candidate.setdefault(cid, []).append(conv)
    # Call Summary: the latest call that collected data (phase-08 decision), else the latest
    last_conv = {cid: pick_summary_conversation(convs) for cid, convs in by_candidate.items()}
    return {
        str(c.id): to_sheet_row(
            c,
            latest.get(c.id),
            last_conv.get(c.id),
            count.get(c.id, 0),
            frontend_url=settings.frontend_url,
            tz=tz,
        )
        for c in candidates
    }


@dataclass
class DrainResult:
    synced: int = 0
    failed: int = 0
    rounds: int = 0
    outcome: str = "idle"  # idle | done | error | busy | not_configured | more


async def _mark_success(session: AsyncSession, ids: list[uuid.UUID], now: datetime) -> None:
    await session.execute(
        update(SyncLog)
        .where(SyncLog.id.in_(ids))
        .values(
            sync_status=SyncStatus.SUCCESS.value,
            synced_at=now,
            error_message=None,
            next_attempt_at=None,
            attempts=SyncLog.attempts + 1,
        )
    )


async def _mark_failed(
    session: AsyncSession, ids: list[uuid.UUID], error: SheetsError, now: datetime
) -> None:
    rows = (await session.execute(select(SyncLog).where(SyncLog.id.in_(ids)))).scalars().all()
    for row in rows:
        row.attempts = (row.attempts or 0) + 1
        row.sync_status = SyncStatus.FAILED.value
        row.error_message = error.message[:2000]
        if not error.transient:
            row.next_attempt_at = now + jittered(PERMANENT_RETRY)
        elif row.attempts <= len(BACKOFF):
            row.next_attempt_at = now + jittered(BACKOFF[row.attempts - 1])
        else:
            row.next_attempt_at = None  # gave up: visible in the dashboard, manual sync retries


async def drain(
    session_factory: Callable[[], Any],
    writer: SheetWriter,
    redis: Redis,
    settings: Settings,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> DrainResult:
    result = DrainResult()
    if not settings.sheets_configured:
        result.outcome = "not_configured"
        return result
    lock = redis.lock(LOCK_KEY, timeout=LOCK_TIMEOUT_S, blocking_timeout=LOCK_WAIT_S)
    if not await lock.acquire():
        result.outcome = "busy"
        return result
    try:
        while result.rounds < MAX_ROUNDS:
            result.rounds += 1
            async with session_factory() as session:
                cids = await due_candidates(session, now())
                if not cids:
                    result.outcome = "done" if result.synced or result.failed else "idle"
                    return result
                # Snapshot the rows BEFORE reading the state: whatever they recorded is
                # already committed, so the state read below includes it.
                row_ids = list(
                    (
                        await session.execute(
                            select(SyncLog.id).where(
                                SyncLog.provider == PROVIDER,
                                SyncLog.candidate_id.in_(cids),
                                SyncLog.sync_status != SyncStatus.SUCCESS.value,
                            )
                        )
                    ).scalars()
                )
                rows = await build_rows(session, cids, settings)
                await session.rollback()  # end the read transaction before the slow API calls
                try:
                    upserted = await writer.upsert(rows)
                except SheetsError as exc:
                    await _mark_failed(session, row_ids, exc, now())
                    await session.commit()
                    result.failed += len(cids)
                    result.outcome = "error"
                    await set_status(
                        redis,
                        state="degraded" if exc.transient else "error",
                        message=exc.message,
                        error_at=now().isoformat(),
                    )
                    logger.warning(
                        "sheets_sync_failed",
                        candidates=len(cids),
                        transient=exc.transient,
                        status=exc.status,
                        error=exc.message,
                    )
                    return result
                await _mark_success(session, row_ids, now())
                await session.commit()
            result.synced += len(cids)
            await set_status(redis, state="ok", message=None, last_success_at=now().isoformat())
            logger.info(
                "sheets_synced",
                updated=len(upserted.updated),
                appended=len(upserted.appended),
                outbox_rows=len(row_ids),
            )
            await lock.extend(LOCK_TIMEOUT_S, replace_ttl=True)
        result.outcome = "more"
        return result
    finally:
        try:
            await lock.release()
        except Exception:
            logger.warning("sheets_lock_release_failed", exc_info=True)


# --- Reconciler and status ---------------------------------------------------------------------


async def stale_count(session: AsyncSession, now: datetime) -> int:
    """Rows the reconciler should re-queue: pending > 5 min, or failed and due."""
    value = await session.scalar(
        select(func.count(SyncLog.id)).where(
            SyncLog.provider == PROVIDER,
            or_(
                (SyncLog.sync_status == SyncStatus.PENDING.value)
                & (SyncLog.created_at <= now - PENDING_STALE),
                (SyncLog.sync_status == SyncStatus.FAILED.value) & (SyncLog.next_attempt_at <= now),
            ),
        )
    )
    return int(value or 0)


async def counts(session: AsyncSession) -> dict[str, Any]:
    rows = await session.execute(
        select(SyncLog.sync_status, func.count(func.distinct(SyncLog.candidate_id)))
        .where(SyncLog.provider == PROVIDER, SyncLog.sync_status != SyncStatus.SUCCESS.value)
        .group_by(SyncLog.sync_status)
    )
    by_status = {status: int(n) for status, n in rows}
    last_success = await session.scalar(
        select(func.max(SyncLog.synced_at)).where(SyncLog.provider == PROVIDER)
    )
    return {
        "pending_candidates": by_status.get(SyncStatus.PENDING.value, 0),
        "failed_candidates": by_status.get(SyncStatus.FAILED.value, 0),
        "last_success_at": last_success,
    }


async def candidate_status(session: AsyncSession, candidate_id: uuid.UUID) -> SyncLog | None:
    """The latest outbox row for a candidate (what the dashboard shows)."""
    return (
        await session.execute(
            select(SyncLog)
            .where(SyncLog.provider == PROVIDER, SyncLog.candidate_id == candidate_id)
            .order_by(SyncLog.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
