"""Finalizing a telephonic round call (phase-11 step 6b, build step 3).

    stored result + answers (screening_store.store_telephonic_outcome)
            ▼
    ONE TRANSACTION: conversation finalized_at; attempt end reason; on opt-out the candidate's
                     scheduled calls cancelled
            ▼
    retry decision (per purpose: a telephonic callback resumes the round)
            ▼
    a facts-only summary (no model: counts and what happened, never a judgement)

Unlike a screening call it never touches the candidate's screening fields or screening status:
the answers stay in extracted_data["telephonic"], where 6c adds the scores.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.agent.state import EndReason
from app.database.connection import get_sessionmaker
from app.database.models import CallAttempt, CallEndReason, Candidate, Conversation
from app.services import call_service
from app.utils.log import get_logger

logger = get_logger(__name__)

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

_ENDINGS = {
    "completed": "The round was completed.",
    "declined": "The candidate said they are no longer interested.",
    "opted_out": "The candidate asked not to be called again.",
    "wrong_person": "The person who answered was not the candidate.",
    "escalated": "It wasn't clear who answered, so the round didn't start.",
    "no_response": "Nobody responded on the line.",
    "hangup": "The call ended before the round finished.",
    "error": "The call ended because of a technical problem on our side.",
}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def summary_text(result: dict[str, Any], note: str | None = None) -> str:
    """What happened on the call, from the stored result only: how many questions got an
    answer, what the candidate asked, and how the call ended. No judgement of the answers."""
    answers = [a for a in result.get("answers") or [] if isinstance(a, dict)]
    count = {
        s: sum(a.get("status") == s for a in answers)
        for s in ("answered", "partial", "declined", "dont_know", "not_asked")
    }
    left = count["not_asked"]
    parts = [f"Telephonic round (questions v{result.get('version', '?')})."]
    if answers and left < len(answers):
        got = f"{count['answered']} of {_plural(len(answers), 'question')} answered"
        extra = [
            f"{count['partial']} partly" if count["partial"] else "",
            f"{count['dont_know']} didn't know" if count["dont_know"] else "",
            f"{count['declined']} refused" if count["declined"] else "",
            f"{left} not asked" if left else "",
        ]
        parts.append(", ".join([got, *[e for e in extra if e]]) + ".")
    unchecked = sum(1 for a in answers if a.get("checked") is False)
    if unchecked:
        parts.append(
            f"{_plural(unchecked, 'answer')} kept as said, without the AI's check (it was busy)."
        )
    asked = [q for q in result.get("candidate_questions") or [] if q]
    if asked:
        parts.append(f"The candidate asked about: {'; '.join(asked[:3])}.")
    end = str(result.get("end_reason") or "")
    callback = result.get("callback") or {}
    if end == "callback":
        when = callback.get("time_text")
        parts.append(
            f"They asked to be called back ({when})." if when else "They asked to be called back."
        )
    elif end == "max_turns":
        parts.append(
            f"The call ran out of time; {_plural(left, 'question')} left for another call."
            if left
            else "The call ran out of time."
        )
    elif end in _ENDINGS:
        parts.append(_ENDINGS[end])
    text = " ".join(parts)
    return f"{text} {note}." if note else text


async def save_final(attempt_id: uuid.UUID) -> bool:
    """The one finalization transaction. False if another run finalized it first."""
    async with get_sessionmaker()() as session:
        conv = (
            await session.execute(
                select(Conversation)
                .where(Conversation.call_attempt_id == attempt_id)
                .with_for_update()
            )
        ).scalar_one()
        if conv.finalized_at is not None:
            await session.rollback()
            return False
        attempt = await session.get(CallAttempt, attempt_id, with_for_update=True)
        assert attempt is not None
        candidate = await session.get(Candidate, attempt.candidate_id, with_for_update=True)
        assert candidate is not None
        result = (conv.extracted_data or {}).get("result") or {}

        conv.finalized_at = datetime.now(UTC)
        conv.screening_completed = False
        if attempt.end_reason is None:
            try:
                reason = _END_REASON.get(EndReason(str(result.get("end_reason"))))
            except ValueError:
                reason = None
            attempt.end_reason = (reason or CallEndReason.AGENT_COMPLETED).value
        if result.get("opted_out") and not candidate.opted_out:
            candidate.opted_out = True  # only ever false → true; screening status untouched
        cancelled = 0
        if candidate.opted_out:
            cancelled = await call_service.cancel_scheduled(
                session, candidate.id, reason="opted_out", keep=attempt_id
            )
        await session.commit()
    logger.info(
        "telephonic_call_finalized",
        call_attempt_id=str(attempt_id),
        end_reason=result.get("end_reason"),
        cancelled_attempts=cancelled or None,
    )
    return True


async def save_summary(attempt_id: uuid.UUID, note: str | None) -> str | None:
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
        result = (conv.extracted_data or {}).get("result") or {}
        conv.summary = summary_text(result, note)
        conv.extracted_data = dict(conv.extracted_data or {}) | {
            "summary_sections": {"generated_by": "facts"}
        }
        await session.commit()
        return conv.summary
