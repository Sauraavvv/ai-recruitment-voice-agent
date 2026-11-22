"""Telephonic round calls for a requirement (phase-11 step 6b).

- `start`: the rules are in `call_service` (purpose telephonic): interested on a completed
  screening, an approved question set, not already done unless the recruiter confirms. This
  scopes the request to one requirement (access follows it) and picks "everyone not called".
- `roster`: the requirement's interested candidates with where each stands in the round.
- `call_answers`: what one round call recorded, question by question, with its AI evaluation.
- `reevaluate`: a recruiter asks for the AI evaluation again (step 6c).
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import AppError
from app.config import Settings
from app.database.models import (
    CallAttempt,
    CallAttemptType,
    CallEndReason,
    CallPurpose,
    CallStatus,
    Candidate,
    Conversation,
    QuestionSet,
    ScreeningStatus,
    User,
)
from app.repositories import call_repo, candidate_repo
from app.schemas.candidate import Eligibility
from app.schemas.telephonic import (
    MAX_TELEPHONIC_BATCH,
    CallAnswers,
    EvaluationBadge,
    RoundAnswer,
    RoundCall,
    RoundRoster,
    RoundRow,
    RoundStatus,
    TelephonicCallsRequest,
)
from app.services import (
    call_service,
    call_state,
    requirement_service,
    telephonic_evaluation,
    telephonic_service,
)
from app.services.call_service import Ineligible, StartResult

Enqueue = Callable[[str], Awaitable[None]]


async def not_called_interested(
    session: AsyncSession,
    user: User,
    requirement_id: uuid.UUID,
    *,
    limit: int = MAX_TELEPHONIC_BATCH,
) -> list[uuid.UUID]:
    """Candidates of the requirement (that `user` sees) who finished screening interested and
    have no telephonic round call yet (cancelled ones don't count), oldest first."""
    had_round = exists().where(
        CallAttempt.candidate_id == Candidate.id,
        CallAttempt.purpose == CallPurpose.TELEPHONIC.value,
        CallAttempt.call_status != CallStatus.CANCELLED.value,
    )
    stmt = (
        select(Candidate.id)
        .where(
            Candidate.requirement_id == requirement_id,
            candidate_repo.visible_to(user),
            Candidate.deleted_at.is_(None),
            Candidate.opted_out.is_(False),
            Candidate.interested.is_(True),
            Candidate.screening_status == ScreeningStatus.COMPLETED.value,
            ~had_round,
        )
        .order_by(Candidate.created_at, Candidate.id)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars())


async def start(
    session: AsyncSession,
    user: User,
    requirement_id: uuid.UUID,
    body: TelephonicCallsRequest,
    settings: Settings,
    enqueue: Enqueue,
    *,
    voice_ready: bool,
) -> list[StartResult]:
    requirement, _client = await requirement_service.get_requirement(session, user, requirement_id)
    ids = list(dict.fromkeys(body.candidate_ids)) or await not_called_interested(
        session, user, requirement.id
    )
    if not ids:
        return []
    mine = set(
        (
            await session.execute(
                select(Candidate.id).where(
                    Candidate.id.in_(ids),
                    Candidate.requirement_id == requirement.id,
                    candidate_repo.visible_to(user),
                )
            )
        ).scalars()
    )
    started = {
        r.candidate_id: r
        for r in await call_service.start_calls(
            session,
            [i for i in ids if i in mine],
            settings,
            enqueue,
            attempt_type=CallAttemptType.MANUAL,
            voice_ready=voice_ready,
            dry_run=body.dry_run,
            override_limit=body.override_limit,
            purpose=CallPurpose.TELEPHONIC,
            call_again=body.call_again,
        )
    }
    # Another recruiter's candidate, or another opening's: not found here
    return [started.get(i) or StartResult(i, error=Ineligible.NOT_FOUND) for i in ids]


# --- Where each interested candidate stands ---------------------------------------------------

_ON_CALL = {CallStatus.INITIATING, CallStatus.RINGING, CallStatus.IN_PROGRESS}
_UNANSWERED = {CallEndReason.NO_ANSWER.value, CallEndReason.BUSY.value}
# An answered call, by how it ended; anything else is "incomplete" (hung up, out of time, …)
_ENDED: dict[str, RoundStatus] = {
    CallEndReason.AGENT_COMPLETED.value: "done",
    CallEndReason.DECLINED.value: "declined",
    CallEndReason.WRONG_PERSON.value: "declined",
    CallEndReason.OPTED_OUT.value: "opted_out",
    CallEndReason.CALLBACK_SCHEDULED.value: "callback",
}


def round_status(attempt: CallAttempt | None) -> RoundStatus:
    """From the candidate's latest telephonic call that wasn't cancelled."""
    if attempt is None:
        return "not_called"
    status = attempt.call_status
    if status in (CallStatus.PENDING, CallStatus.QUEUED):
        return "queued"
    if status in _ON_CALL:
        return "on_call"
    if status == CallStatus.RETRY_SCHEDULED:
        return "retry_scheduled"
    if status == CallStatus.CALLBACK_REQUESTED:
        return "callback"
    if status in (CallStatus.NO_ANSWER, CallStatus.BUSY):
        return "no_answer"
    if status == CallStatus.EXHAUSTED:
        return "no_answer" if attempt.end_reason in _UNANSWERED else "failed"
    if status != CallStatus.COMPLETED:
        return "failed"
    return _ENDED.get(attempt.end_reason or "", "incomplete")


def _answers(conv: Conversation | None) -> list[dict[str, Any]]:
    stored = ((conv.extracted_data or {}) if conv else {}).get("telephonic") or {}
    return [a for a in stored.get("answers") or [] if isinstance(a, dict)]


async def roster(
    session: AsyncSession,
    user: User,
    requirement_id: uuid.UUID,
    settings: Settings,
    *,
    voice_ready: bool,
) -> RoundRoster:
    requirement, _client = await requirement_service.get_requirement(session, user, requirement_id)
    candidates = list(
        (
            await session.execute(
                select(Candidate)
                .where(
                    Candidate.requirement_id == requirement.id,
                    candidate_repo.visible_to(user),
                    Candidate.deleted_at.is_(None),
                    Candidate.interested.is_(True),
                )
                .order_by(Candidate.created_at, Candidate.id)
            )
        ).scalars()
    )
    ids = [c.id for c in candidates]
    eligibility = await call_service.eligibility_for(
        session, candidates, settings, voice_ready=voice_ready, purpose=CallPurpose.TELEPHONIC
    )
    done = await call_repo.completed_rounds(session, ids)
    latest = {
        a.candidate_id: a
        for a in (
            await session.execute(
                select(CallAttempt)
                .where(
                    CallAttempt.candidate_id.in_(ids),
                    CallAttempt.purpose == CallPurpose.TELEPHONIC.value,
                    CallAttempt.call_status != CallStatus.CANCELLED.value,
                )
                .ext(distinct_on(CallAttempt.candidate_id))
                .order_by(CallAttempt.candidate_id, CallAttempt.attempt_number.desc())
            )
        ).scalars()
    }
    set_ids = {a.question_set_id for a in latest.values() if a.question_set_id}
    versions = dict(
        (
            await session.execute(
                select(QuestionSet.id, QuestionSet.version).where(QuestionSet.id.in_(set_ids))
            )
        ).all()
    )
    convs = {
        c.call_attempt_id: c
        for c in (
            await session.execute(
                select(Conversation).where(
                    Conversation.call_attempt_id.in_([a.id for a in latest.values()])
                )
            )
        ).scalars()
    }
    approved = await telephonic_service.latest_approved_id(session, requirement.id)
    badges = await latest_badges(session, ids)
    rows = []
    for c in candidates:
        attempt = latest.get(c.id)
        code = eligibility.get(c.id)
        if code is None and c.id in done:
            code = Ineligible.TELEPHONIC_DONE  # a second round needs the recruiter's "yes"
        last = None
        if attempt is not None:
            conv = convs.get(attempt.id)
            answers = _answers(conv)
            last = RoundCall(
                id=attempt.id,
                attempt_number=attempt.attempt_number,
                call_status=CallStatus(attempt.call_status),
                end_reason=CallEndReason(attempt.end_reason) if attempt.end_reason else None,
                at=attempt.start_time or attempt.next_retry_at or attempt.created_at,
                terminal=call_state.is_terminal(attempt.call_status),
                next_retry_at=attempt.next_retry_at,
                question_set_id=attempt.question_set_id,
                version=versions.get(attempt.question_set_id) if attempt.question_set_id else None,
                finalized=bool(conv and conv.finalized_at),
                has_transcript=bool(conv and conv.transcript),
                answered=sum(a.get("status") in ("answered", "partial") for a in answers),
                questions=len(answers),
            )
        rows.append(
            RoundRow(
                candidate_id=c.id,
                name=c.name,
                phone=c.phone,
                status=round_status(attempt),
                last_call=last,
                done_before=c.id in done,
                eligibility=Eligibility.model_validate(call_service.eligibility_dict(code)),
                evaluation=badges.get(c.id),
            )
        )
    approved_version = None
    if approved is not None:
        approved_set = await session.get(QuestionSet, approved)
        approved_version = approved_set.version if approved_set else None
    return RoundRoster(approved_version=approved_version, rows=rows)


async def latest_badges(
    session: AsyncSession, candidate_ids: list[uuid.UUID]
) -> dict[uuid.UUID, EvaluationBadge]:
    """Candidate → the evaluation of their latest evaluated round call (a scheduled callback has
    no answers yet, so the score of the call before it stays on the row)."""
    if not candidate_ids:
        return {}
    rows = await session.execute(
        select(CallAttempt.candidate_id, CallAttempt.id, Conversation.extracted_data)
        .join(Conversation, Conversation.call_attempt_id == CallAttempt.id)
        .where(
            CallAttempt.candidate_id.in_(candidate_ids),
            CallAttempt.purpose == CallPurpose.TELEPHONIC.value,
            Conversation.extracted_data["telephonic"].has_key("evaluation"),
        )
        .order_by(CallAttempt.candidate_id, CallAttempt.attempt_number.desc())
    )
    out: dict[uuid.UUID, EvaluationBadge] = {}
    for candidate_id, attempt_id, data in rows.all():
        if candidate_id in out:
            continue
        evaluation = ((data or {}).get("telephonic") or {}).get("evaluation")
        found = telephonic_evaluation.badge(
            attempt_id, evaluation if isinstance(evaluation, dict) else {}
        )
        if found is not None:
            out[candidate_id] = found
    return out


async def call_badges(
    session: AsyncSession, attempt_ids: list[uuid.UUID]
) -> dict[uuid.UUID, EvaluationBadge]:
    """Call attempt → its own evaluation (the calls list)."""
    if not attempt_ids:
        return {}
    rows = await session.execute(
        select(Conversation.call_attempt_id, Conversation.extracted_data).where(
            Conversation.call_attempt_id.in_(attempt_ids),
            Conversation.extracted_data["telephonic"].has_key("evaluation"),
        )
    )
    out: dict[uuid.UUID, EvaluationBadge] = {}
    for attempt_id, data in rows.all():
        evaluation = ((data or {}).get("telephonic") or {}).get("evaluation")
        found = telephonic_evaluation.badge(
            attempt_id, evaluation if isinstance(evaluation, dict) else {}
        )
        if found is not None:
            out[attempt_id] = found
    return out


async def call_answers(session: AsyncSession, user: User, attempt_id: uuid.UUID) -> CallAnswers:
    """What a telephonic round call recorded. 404 for a call whose candidate the user doesn't
    see (another company's, or another recruiter's), 409 for a screening call."""
    attempt = await session.get(CallAttempt, attempt_id)
    candidate = await session.get(Candidate, attempt.candidate_id) if attempt else None
    if (
        attempt is None
        or candidate is None
        or candidate.requirement_id is None
        or not candidate_repo.can_see(user, candidate)
    ):
        raise AppError(404, "call_not_found", "Call attempt not found")
    await requirement_service.get_requirement(session, user, candidate.requirement_id)
    if attempt.purpose != CallPurpose.TELEPHONIC:
        raise AppError(409, "not_telephonic", "This is a screening call, not a telephonic round")
    conv = await session.scalar(
        select(Conversation)
        .where(Conversation.call_attempt_id == attempt.id)
        .execution_options(populate_existing=True)
    )
    stored = ((conv.extracted_data or {}) if conv else {}).get("telephonic") or {}
    version = stored.get("version")
    if version is None and attempt.question_set_id:
        question_set = await session.get(QuestionSet, attempt.question_set_id)
        version = question_set.version if question_set else None
    return CallAnswers(
        call_attempt_id=attempt.id,
        candidate_id=attempt.candidate_id,
        question_set_id=attempt.question_set_id,
        version=version,
        answers=[RoundAnswer.model_validate(a) for a in _answers(conv)],
        candidate_questions=[str(q) for q in stored.get("candidate_questions") or []],
        summary=conv.summary if conv else None,
        finalized=bool(conv and conv.finalized_at),
        call_status=CallStatus(attempt.call_status),
        end_reason=CallEndReason(attempt.end_reason) if attempt.end_reason else None,
        start_time=attempt.start_time,
        duration_seconds=attempt.duration_seconds,
        evaluation=telephonic_evaluation.to_out(telephonic_evaluation.stored(conv)),
    )


EnqueueEvaluation = Callable[[str, str | None], Awaitable[None]]


async def reevaluate(
    session: AsyncSession,
    user: User,
    attempt_id: uuid.UUID,
    settings: Settings,
    enqueue: EnqueueEvaluation,
) -> CallAnswers:
    """Queue the AI evaluation of a finished round call again (e.g. after a rubric was
    sharpened). The previous result stays visible until the new one is saved."""
    answers = await call_answers(session, user, attempt_id)  # access; 409 for a screening call
    if not answers.finalized:
        raise AppError(409, "not_finalized", "The call's answers aren't saved yet. Try again soon.")
    if not settings.groq_keys:
        raise AppError(503, "ai_not_configured", "The evaluating AI isn't set up yet.")
    token = datetime.now(UTC).isoformat()
    await telephonic_evaluation.mark_pending(session, attempt_id, token, user.id)
    await enqueue(str(attempt_id), token)
    return await call_answers(session, user, attempt_id)
