"""What the candidate list and the candidate page show beyond the candidate row (phase-08).

- list rows: eligibility (`can_call` + the reason, for disabled buttons), the latest call
- the candidate's summary: the latest finalized call that collected data (else the latest)
- Google Sheets sync status of the candidate's row
- open data conflicts (phase-07 final pass), each with both values and the quotes
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.database.models import CallAttempt, Candidate, Conversation, SyncLog, SyncStatus
from app.repositories import call_repo
from app.services import call_service, sync_service
from app.services.call_state import is_terminal
from app.services.summary_service import collected_data, pick_summary_conversation


def open_conflicts(candidate: Candidate) -> list[dict[str, Any]]:
    """Fields whose stored value the final pass disputed and nobody has resolved yet."""
    out = []
    for field, meta in (candidate.screening_field_meta or {}).items():
        if not isinstance(meta, dict):
            continue
        conflict = meta.get("conflict")
        if not isinstance(conflict, dict):
            continue
        out.append(
            {
                "field": field,
                "stored_value": getattr(candidate, field, meta.get("value"))
                if hasattr(Candidate, field)
                else meta.get("value"),
                "stored_quote": meta.get("raw_text"),
                "stored_seq": meta.get("seq"),
                "other_value": conflict.get("final_value"),
                "other_quote": conflict.get("quote"),
                "other_seq": conflict.get("seq"),
                "reason": conflict.get("reason"),
                "call_attempt_id": meta.get("call_attempt_id"),
            }
        )
    return out


def _last_call(attempt: CallAttempt | None) -> dict[str, Any] | None:
    if attempt is None:
        return None
    return {
        "id": attempt.id,
        "attempt_number": attempt.attempt_number,
        "call_status": attempt.call_status,
        "end_reason": attempt.end_reason,
        "at": attempt.start_time or attempt.created_at,
        "terminal": is_terminal(attempt.call_status),
    }


async def list_rows(
    session: AsyncSession,
    candidates: list[Candidate],
    settings: Settings,
    *,
    voice_ready: bool,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    from app.schemas.candidate import CandidateOut

    eligibility = await call_service.eligibility_for(
        session, candidates, settings, now=now, voice_ready=voice_ready
    )
    latest = await call_repo.latest_for_candidates(session, [c.id for c in candidates])
    with_transcript = set()
    if latest:
        with_transcript = set(
            (
                await session.execute(
                    select(Conversation.call_attempt_id).where(
                        Conversation.call_attempt_id.in_([a.id for a in latest.values()]),
                    )
                )
            ).scalars()
        )
    rows = []
    for c in candidates:
        last = latest.get(c.id)
        row = CandidateOut.model_validate(c).model_dump()
        row["eligibility"] = call_service.eligibility_dict(eligibility.get(c.id))
        row["last_call"] = _last_call(last)
        row["last_call_has_transcript"] = bool(last and last.id in with_transcript)
        row["open_conflicts"] = len(open_conflicts(c))
        rows.append(row)
    return rows


async def summary(session: AsyncSession, candidate_id: uuid.UUID) -> dict[str, Any] | None:
    conversations = (
        await session.execute(
            select(Conversation, CallAttempt.attempt_number)
            .join(CallAttempt, CallAttempt.id == Conversation.call_attempt_id)
            .where(CallAttempt.candidate_id == candidate_id, Conversation.finalized_at.is_not(None))
            .order_by(Conversation.finalized_at)
        )
    ).all()
    numbers = {conv.id: n for conv, n in conversations}
    picked = pick_summary_conversation([conv for conv, _ in conversations])
    if picked is None:
        return None
    data = picked.extracted_data or {}
    sections = data.get("summary_sections") or {}
    final = data.get("final") or {}
    result = data.get("result") or {}
    latest = conversations[-1][0]
    return {
        "call_attempt_id": picked.call_attempt_id,
        "attempt_number": numbers.get(picked.id),
        "text": picked.summary,
        "generated_by": sections.get("generated_by"),
        "missing_information": sections.get("missing_information")
        or final.get("missing_fields")
        or [],
        "callback": sections.get("callback"),
        "callback_request": result.get("callback")
        if (result.get("callback") or {}).get("requested")
        else None,
        "finalized_at": picked.finalized_at,
        "collected_data": collected_data(data),
        # a newer call collected nothing: say so next to the older summary
        "newer_call_without_data": latest.id != picked.id,
    }


async def sync_status(session: AsyncSession, candidate_id: uuid.UUID) -> dict[str, Any]:
    row = await sync_service.candidate_status(session, candidate_id)
    if row is None:
        return {"status": "never", "synced_at": None, "error": None, "next_attempt_at": None}
    last_success = await session.scalar(
        select(func.max(SyncLog.synced_at)).where(
            SyncLog.provider == sync_service.PROVIDER,
            SyncLog.candidate_id == candidate_id,
            SyncLog.sync_status == SyncStatus.SUCCESS.value,
        )
    )
    return {
        "status": row.sync_status,
        "synced_at": last_success,
        "error": row.error_message if row.sync_status == SyncStatus.FAILED.value else None,
        "next_attempt_at": row.next_attempt_at,
    }
