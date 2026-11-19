"""Transcript persistence while the call happens (phase-06 §5.7, plan.md Module G).

- `open_conversation`: the `conversations` row is created when the stream starts.
- `save_turns`: after every turn, the new or changed entries are merged into
  `conversations.transcript` **by `seq`** in one UPDATE (entries with the same seq are replaced,
  others appended, order by seq), and the conversation state snapshot goes into
  `extracted_data.live`. Re-sending the same entries changes nothing, so it's idempotent, and a
  later change to an entry (the agent's turn was interrupted) overwrites it.

A crash mid-call keeps everything up to the last saved turn (plan.md: partial calls preserve
information). The final result is written by `screening_store.store_outcome` at the end.
"""

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from app.database.connection import get_sessionmaker
from app.database.models import Conversation
from app.utils.log import get_logger

logger = get_logger(__name__)

_MERGE = text(
    """
    UPDATE conversations SET
      transcript = (
        SELECT COALESCE(jsonb_agg(e ORDER BY (e->>'seq')::int), '[]'::jsonb) FROM (
          SELECT x AS e FROM jsonb_array_elements(conversations.transcript) x
           WHERE NOT EXISTS (
             SELECT 1 FROM jsonb_array_elements(CAST(:entries AS jsonb)) n
              WHERE (n->>'seq')::int = (x->>'seq')::int)
          UNION ALL
          SELECT n FROM jsonb_array_elements(CAST(:entries AS jsonb)) n
        ) merged
      ),
      extracted_data = conversations.extracted_data || CAST(:data AS jsonb)
    WHERE call_attempt_id = :attempt_id
    """
)


def compact(entry: dict[str, Any]) -> dict[str, Any]:
    """Drop empty optional keys (None, False) from a transcript entry."""
    return {k: v for k, v in entry.items() if k == "seq" or (v is not None and v is not False)}


async def open_conversation(attempt_id: uuid.UUID) -> None:
    async with get_sessionmaker()() as db:
        await db.execute(
            insert(Conversation)
            .values(call_attempt_id=attempt_id)
            .on_conflict_do_nothing(index_elements=["call_attempt_id"])
        )
        await db.commit()


async def save_turns(
    attempt_id: uuid.UUID, entries: list[dict[str, Any]], *, live: dict[str, Any] | None = None
) -> None:
    """Merge `entries` (each with a `seq`) and store the live snapshot."""
    data = {"live": live} if live is not None else {}
    async with get_sessionmaker()() as db:
        await db.execute(
            _MERGE,
            {
                "attempt_id": attempt_id,
                "entries": json.dumps([compact(e) for e in entries], default=str),
                "data": json.dumps(data, default=str),
            },
        )
        await db.commit()


class TranscriptWriter:
    """Per-session: remembers what it has saved and sends only new or changed entries."""

    def __init__(self, attempt_id: uuid.UUID) -> None:
        self.attempt_id = attempt_id
        self._saved: dict[int, dict[str, Any]] = {}
        self.writes = 0
        self.failures = 0

    def pending(self, transcript: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for entry in transcript:
            entry = compact(entry)
            if self._saved.get(int(entry["seq"])) != entry:
                out.append(entry)
        return out

    async def save(
        self, transcript: list[dict[str, Any]], *, live: dict[str, Any] | None = None
    ) -> int:
        """Save what changed. Never raises: a failed write is logged and retried next turn."""
        entries = self.pending(transcript)
        if not entries and live is None:
            return 0
        try:
            await save_turns(self.attempt_id, entries, live=live)
        except Exception:
            self.failures += 1
            logger.exception("transcript_save_failed", call_attempt_id=str(self.attempt_id))
            return 0
        for entry in entries:
            self._saved[int(entry["seq"])] = entry
        self.writes += 1
        return len(entries)
