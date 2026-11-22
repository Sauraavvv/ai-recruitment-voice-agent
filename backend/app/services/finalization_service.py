"""Post-call finalization (phase-07 §5): final extraction → one transaction → summary → Sheets.

    load conversation ──► already finalized? ──yes──► (summary missing? write it) stop
            │ no
            ▼
    final pass (LLM over the full transcript) ─► reconcile with live state ─► validate
            ▼
    ONE TRANSACTION:
      conversations   extracted_data.final, screening_completed, finalized_at
      candidates      merged fields, screening_field_meta, screening_status, opted_out
      call_attempts   end data; scheduled attempts cancelled on opt-out
      sync_logs       pending row (outbox)
            ▼ commit
    summary (LLM, retried, deterministic fallback) ─► save (+ outbox row) ─► queue the sync

Idempotent: `finalized_at` is checked again under SELECT … FOR UPDATE. A failing LLM never
blocks persistence: without the final pass the live state is used as it is, and without the
summary LLM the facts-only summary is stored.
"""

import uuid
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.conversation_manager import ScreeningResult
from app.agent.final_pass import FinalOutcome, finalize, run_final_pass
from app.agent.prompts import JobConfig
from app.agent.schemas import FieldName
from app.agent.state import EndReason, QuestionSpec
from app.config import Settings
from app.database.connection import get_sessionmaker
from app.database.models import (
    CallAttempt,
    CallEndReason,
    CallPurpose,
    Candidate,
    Conversation,
    Job,
    ScreeningStatus,
)
from app.providers.llm.base import LLMProvider
from app.services import (
    call_service,
    retry_service,
    screening_job,
    sync_service,
    telephonic_finalization,
)
from app.services.summary_service import generate_summary

__all__ = ["finalize_attempt", "generate_summary", "merge_candidate", "save_final"]
from app.utils.log import get_logger

logger = get_logger(__name__)

STANDARD_FIELDS = tuple(f.value for f in FieldName)
_END_REASON = {
    EndReason.COMPLETED: CallEndReason.AGENT_COMPLETED,
    EndReason.CALLBACK: CallEndReason.CALLBACK_SCHEDULED,
    EndReason.DECLINED: CallEndReason.DECLINED,
    EndReason.OPTED_OUT: CallEndReason.OPTED_OUT,
    EndReason.WRONG_PERSON: CallEndReason.WRONG_PERSON,
    EndReason.ESCALATED: CallEndReason.ESCALATED,
    EndReason.NO_RESPONSE: CallEndReason.SILENCE_TIMEOUT,
    EndReason.HANGUP: CallEndReason.CANDIDATE_HANGUP,
    EndReason.MAX_TURNS: CallEndReason.MAX_DURATION,
    EndReason.ERROR: CallEndReason.TECHNICAL_FAILURE,
}


def job_questions(job: Job | None) -> list[QuestionSpec]:
    """The job's questions as the call used them (the defaults when the job has none)."""
    if job is None:
        return JobConfig.from_dict({"job_title": "", "company_name": ""}).questions
    return JobConfig.from_dict(
        {
            "job_title": job.job_title,
            "company_name": job.company_name,
            "screening_questions": job.screening_questions,
        }
    ).questions


def merge_candidate(
    candidate: Candidate, outcome: FinalOutcome, attempt_id: uuid.UUID, *, fill_only: bool = False
) -> list[str]:
    """Newer non-null values overwrite; null never overwrites (plan.md state rules). The
    metadata of a field without a value records its status only when there's no older value.
    `fill_only` (a newer call was already finalized): only fields still empty are filled.
    Returns the fields whose value was written."""
    meta = dict(candidate.screening_field_meta or {})
    written = []
    for key, f in outcome.fields.items():
        entry = {**asdict(f), "call_attempt_id": str(attempt_id)}
        standard = key in STANDARD_FIELDS
        current = getattr(candidate, key) if standard else (meta.get(key) or {}).get("value")
        if fill_only and current is not None:
            continue
        if f.value is not None:
            if standard:
                setattr(candidate, key, f.value)
            meta[key] = entry
            written.append(key)
        elif current is None:
            meta[key] = entry  # e.g. declined: shows why there's no value
        elif f.conflict:
            meta.setdefault(key, {})["conflict"] = f.conflict
    candidate.screening_field_meta = meta
    return written


async def save_final(
    session: AsyncSession, attempt_id: uuid.UUID, result: ScreeningResult, outcome: FinalOutcome
) -> bool:
    """The one finalization transaction. False if another run finalized it first."""
    conv = (
        await session.execute(
            select(Conversation).where(Conversation.call_attempt_id == attempt_id).with_for_update()
        )
    ).scalar_one()
    if conv.finalized_at is not None:
        await session.rollback()
        return False
    attempt = await session.get(CallAttempt, attempt_id, with_for_update=True)
    assert attempt is not None
    candidate = await session.get(Candidate, attempt.candidate_id, with_for_update=True)
    assert candidate is not None

    # Finalized out of order (e.g. a backlog after a worker outage): a newer call already wrote
    # the candidate, so this older one must not overwrite it
    newer = await session.scalar(
        select(func.count())
        .select_from(Conversation)
        .join(CallAttempt, CallAttempt.id == Conversation.call_attempt_id)
        .where(
            CallAttempt.candidate_id == candidate.id,
            CallAttempt.attempt_number > attempt.attempt_number,
            Conversation.finalized_at.is_not(None),
        )
    )
    superseded = bool(newer)

    now = datetime.now(UTC)
    final = outcome.to_json() | {"superseded": superseded}
    conv.extracted_data = dict(conv.extracted_data or {}) | {"final": final}
    conv.screening_completed = outcome.status == ScreeningStatus.COMPLETED
    conv.finalized_at = now

    written = merge_candidate(candidate, outcome, attempt_id, fill_only=superseded)
    previous_status = candidate.screening_status
    if outcome.status is not None and not superseded:
        candidate.screening_status = outcome.status.value
    cancelled = 0
    if result.opted_out and not candidate.opted_out:
        candidate.opted_out = True  # only ever false → true
    if candidate.opted_out:
        cancelled = await call_service.cancel_scheduled(
            session, candidate.id, reason="opted_out", keep=attempt_id
        )

    if attempt.end_reason is None:
        attempt.end_reason = _END_REASON.get(result.end_reason, CallEndReason.AGENT_COMPLETED).value

    sync_service.record_change(session, candidate.id)
    await session.commit()
    logger.info(
        "call_finalized",
        call_attempt_id=str(attempt_id),
        candidate_id=str(candidate.id),
        screening_status=candidate.screening_status,
        previous_status=previous_status,
        fields_written=sorted(written),
        final_pass=outcome.final_pass_ran,
        conflicts=sorted(outcome.conflicts) or None,
        rejected=sorted(outcome.rejected) or None,
        cancelled_attempts=cancelled or None,
        superseded=superseded or None,
    )
    return True


def summary_input(result: ScreeningResult, final: dict[str, Any]) -> ScreeningResult:
    """The stored result with the finalized values (what the summary must describe)."""
    fields = final.get("fields") or {}
    return replace(
        result,
        collected_data={k: f.get("value") for k, f in fields.items()},
        fields={
            k: {"status": f.get("status"), "raw_text": f.get("raw_text")} for k, f in fields.items()
        },
        missing_fields=list(final.get("missing_fields") or []),
    )


async def save_summary(
    attempt_id: uuid.UUID,
    result: ScreeningResult,
    final: dict[str, Any],
    *,
    candidate_name: str,
    job_title: str,
    llm: LLMProvider | None,
    note: str | None = None,
) -> str | None:
    """`note`: a scheduling note (a callback moved into calling hours) added to the text."""
    summary = await generate_summary(
        summary_input(result, final), candidate_name=candidate_name, job_title=job_title, llm=llm
    )
    async with get_sessionmaker()() as session:
        conv = (
            await session.execute(
                select(Conversation)
                .where(Conversation.call_attempt_id == attempt_id)
                .with_for_update()
            )
        ).scalar_one()
        if conv.summary:
            await session.rollback()
            return None
        conv.summary = f"{summary.text} {note}." if note else summary.text
        conv.extracted_data = dict(conv.extracted_data or {}) | {
            "summary_sections": summary.model_dump(mode="json")
        }
        attempt = await session.get(CallAttempt, attempt_id)
        assert attempt is not None
        sync_service.record_change(session, attempt.candidate_id)  # Call Summary column
        await session.commit()
    logger.info("summary_saved", call_attempt_id=str(attempt_id), summary_by=summary.generated_by)
    return summary.text


async def finalize_attempt(
    attempt_id: uuid.UUID,
    *,
    settings: Settings,
    llm: LLMProvider | None,
    pool: sync_service.JobPool | None = None,
) -> str:
    """Run the pipeline for one attempt. Returns no_result | already_done | finalized |
    summarized (finalized earlier, only the summary was missing). A telephonic round call
    goes its own way (`telephonic_finalization`)."""
    async with get_sessionmaker()() as session:
        conv = (
            await session.execute(
                select(Conversation).where(Conversation.call_attempt_id == attempt_id)
            )
        ).scalar_one_or_none()
        if conv is None or not (conv.extracted_data or {}).get("result"):
            return "no_result"
        if conv.finalized_at is not None and conv.summary:
            await _evaluate_retry(attempt_id, settings)  # idempotent; e.g. a retried job
            return "already_done"
        attempt = await session.get(CallAttempt, attempt_id)
        assert attempt is not None
        round_call = attempt.purpose == CallPurpose.TELEPHONIC
        already = conv.finalized_at is not None
    if round_call:
        return await _finalize_round(attempt_id, already=already, settings=settings)

    async with get_sessionmaker()() as session:
        attempt = await session.get(CallAttempt, attempt_id)
        assert attempt is not None
        conv = (
            await session.execute(
                select(Conversation).where(Conversation.call_attempt_id == attempt_id)
            )
        ).scalar_one()
        candidate = await session.get(Candidate, attempt.candidate_id)
        assert candidate is not None
        job = await screening_job.for_candidate(session, candidate)
        result = ScreeningResult.from_dict(conv.extracted_data["result"])
        result.transcript = list(conv.transcript or [])
        final = (conv.extracted_data or {}).get("final")
        candidate_name, job_title = candidate.name, job.job_title if job else ""

    outcome = "summarized"
    if not already:
        questions = job_questions(job)
        output = await run_final_pass(llm, result.transcript, questions) if llm else None
        final_outcome = finalize(result, questions, output)
        async with get_sessionmaker()() as session:
            if not await save_final(session, attempt_id, result, final_outcome):
                return "already_done"
        final = final_outcome.to_json()
        outcome = "finalized"
        await sync_service.request_sync(settings, pool)

    # Phase 9: retry or callback, now that the conversation's outcome is known
    note = await _evaluate_retry(attempt_id, settings)

    try:
        await save_summary(
            attempt_id,
            result,
            final or {},
            candidate_name=candidate_name,
            job_title=job_title,
            llm=llm,
            note=note,
        )
    except Exception:
        # Never undoes or blocks the saved data; the reconciler retries a missing summary
        logger.exception("summary_failed", call_attempt_id=str(attempt_id))
    else:
        await sync_service.request_sync(settings, pool)
    return outcome


async def _finalize_round(attempt_id: uuid.UUID, *, already: bool, settings: Settings) -> str:
    """A telephonic round call: answers kept as stored, no screening fields, no Sheet."""
    outcome = "summarized"
    if not already:
        if not await telephonic_finalization.save_final(attempt_id):
            return "already_done"
        outcome = "finalized"
    note = await _evaluate_retry(attempt_id, settings)
    try:
        await telephonic_finalization.save_summary(attempt_id, note)
    except Exception:
        logger.exception("summary_failed", call_attempt_id=str(attempt_id))
    return outcome


async def _evaluate_retry(attempt_id: uuid.UUID, settings: Settings) -> str | None:
    """The retry decision for a finalized call (phase-09). Never raises. Returns the note to
    add to the summary (a callback moved into calling hours), if any."""
    async with get_sessionmaker()() as session:
        evaluation = await retry_service.evaluate_safely(session, attempt_id, settings)
    if evaluation is None or evaluation.decision != "callback_scheduled":
        return None
    return evaluation.note
