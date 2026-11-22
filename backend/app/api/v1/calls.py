"""Call attempts (plan.md Module F, phase-08 §5.3). Recruiter-only.

start (and dry run) · list with filters · detail · transcript · retry · cancel · hangup.
Starting and retrying use the effective settings: the Settings page's calling window and the
global pause apply at once.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, EffectiveSettingsDep, RedisDep, SessionDep, SettingsDep
from app.api.responses import ok
from app.config import Settings
from app.database.models import (
    CallAttemptType,
    CallPurpose,
    CallStatus,
    Conversation,
    QuestionSet,
    Requirement,
)
from app.repositories import call_repo
from app.schemas.call import (
    CallAttemptOut,
    CallListItem,
    CallTranscript,
    HangupResult,
    RetryCallRequest,
    StartCallResult,
    StartCallsRequest,
)
from app.schemas.common import DataResponse, PageResponse
from app.schemas.telephonic import CallAnswers
from app.services import call_service, sync_service, telephonic_calls
from app.services.errors import conflict, not_found
from app.utils.queue import enqueue_evaluate_round, enqueue_initiate_call
from app.voice.session_registry import REGISTRY

router = APIRouter(prefix="/calls", tags=["calls"])


def voice_ready(request: Request, settings: Settings) -> bool:
    """Calls need the AI voice loaded in this process (it speaks on the stream).
    tts_preload off = tests: there is no voice to wait for."""
    tts = getattr(request.app.state, "tts", None)
    return not settings.tts_preload or bool(tts and tts.status().ready)


@router.post(
    "/start",
    response_model=DataResponse[list[StartCallResult]],
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_calls(
    body: StartCallsRequest, session: SessionDep, settings: EffectiveSettingsDep, request: Request
) -> dict[str, Any]:
    """Queue a screening call per candidate. Each candidate gets its own result (ok or a
    reason). `dry_run`: only the results, nothing queued (the confirmation dialog)."""
    results = await call_service.start_calls(
        session,
        body.candidate_ids,
        settings,
        enqueue_initiate_call,
        attempt_type=CallAttemptType.MANUAL,
        voice_ready=voice_ready(request, settings),
        dry_run=body.dry_run,
        override_limit=body.override_limit,
    )
    if any(r.attempt_id for r in results):
        await sync_service.request_sync(settings)
    return ok([r.as_dict() for r in results])


@router.get("", response_model=PageResponse[CallListItem])
async def list_calls(
    session: SessionDep,
    candidate_id: uuid.UUID | None = None,
    call_status: Annotated[list[CallStatus] | None, Query()] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    q: Annotated[str | None, Query(max_length=200, description="Candidate name or phone")] = None,
    purpose: Annotated[CallPurpose | None, Query(description="screening | telephonic")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> dict[str, Any]:
    rows, total = await call_repo.search(
        session,
        candidate_id=candidate_id,
        status=[s.value for s in call_status] if call_status else None,
        created_from=created_from,
        created_to=created_to,
        q=q,
        purpose=purpose,
        page=page,
        page_size=page_size,
    )
    ids = [a.id for a, _, _ in rows]
    with_transcript = set(
        (
            await session.execute(
                select(Conversation.call_attempt_id).where(
                    Conversation.call_attempt_id.in_(ids),
                    func.jsonb_array_length(Conversation.transcript) > 0,
                )
            )
        ).scalars()
    )
    set_ids = {a.question_set_id for a, _, _ in rows if a.question_set_id}
    rounds = {
        set_id: {
            "requirement_id": requirement_id,
            "client_id": client_id,
            "title": title,
            "version": version,
        }
        for set_id, version, requirement_id, client_id, title in (
            await session.execute(
                select(
                    QuestionSet.id,
                    QuestionSet.version,
                    Requirement.id,
                    Requirement.client_id,
                    Requirement.title,
                )
                .join(Requirement, Requirement.id == QuestionSet.requirement_id)
                .where(QuestionSet.id.in_(set_ids))
            )
        ).all()
    }
    badges = await telephonic_calls.call_badges(
        session, [a.id for a, _, _ in rows if a.purpose == CallPurpose.TELEPHONIC]
    )
    items = [
        CallAttemptOut.model_validate(a).model_dump()
        | {
            "candidate_name": name,
            "applied_role": role,
            "has_transcript": a.id in with_transcript,
            "round": rounds.get(a.question_set_id) if a.question_set_id else None,
            "evaluation": badges.get(a.id),
        }
        for a, name, role in rows
    ]
    return ok(items, {"page": page, "page_size": page_size, "total": total})


@router.get("/{call_attempt_id}", response_model=DataResponse[CallAttemptOut])
async def get_call(call_attempt_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    return ok(await call_service.get(session, call_attempt_id))


def _entry(e: dict[str, Any]) -> dict[str, Any] | None:
    text = e.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    speaker = "assistant" if e.get("speaker") in ("assistant", "agent") else "candidate"
    return {
        "seq": e.get("seq"),
        "speaker": speaker,
        "text": text,
        "timestamp": e.get("timestamp"),
        "interrupted": bool(e.get("interrupted")),
        "heard_text": e.get("heard_text"),
    }


@router.get("/{call_attempt_id}/transcript", response_model=DataResponse[CallTranscript])
async def get_transcript(call_attempt_id: uuid.UUID, session: SessionDep) -> dict[str, Any]:
    """The call's transcript (empty for a call nobody answered), and its summary."""
    attempt = await call_service.get(session, call_attempt_id)
    conv = (
        await session.execute(
            select(Conversation).where(Conversation.call_attempt_id == attempt.id)
        )
    ).scalar_one_or_none()
    entries = [x for e in (conv.transcript if conv else []) if (x := _entry(e))]
    session_info = ((conv.extracted_data or {}).get("session") or {}) if conv else {}
    return ok(
        {
            "call_attempt_id": attempt.id,
            "candidate_id": attempt.candidate_id,
            "attempt_number": attempt.attempt_number,
            "call_status": attempt.call_status,
            "end_reason": attempt.end_reason,
            "start_time": attempt.start_time,
            "duration_seconds": attempt.duration_seconds,
            "entries": entries,
            "summary": conv.summary if conv else None,
            "finalized": bool(conv and conv.finalized_at),
            "voice_engine": session_info.get("engine") or "pipeline",
            "estimated_cost_usd": session_info.get("estimated_cost_usd"),
        }
    )


@router.get("/{call_attempt_id}/answers", response_model=DataResponse[CallAnswers])
async def get_answers(
    call_attempt_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    """A telephonic round call's answers, question by question, with its summary. 409
    not_telephonic for a screening call."""
    return ok(await telephonic_calls.call_answers(session, user, call_attempt_id))


@router.post(
    "/{call_attempt_id}/evaluate",
    response_model=DataResponse[CallAnswers],
    status_code=status.HTTP_202_ACCEPTED,
)
async def reevaluate(
    call_attempt_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    """Evaluate a finished telephonic round call again with the AI (e.g. after editing a
    rubric). Returns the answers with the evaluation pending; the previous result stays until
    the new one is saved. 409 not_finalized / not_telephonic, 503 ai_not_configured."""
    return ok(
        await telephonic_calls.reevaluate(
            session, user, call_attempt_id, settings, enqueue_evaluate_round
        )
    )


@router.post(
    "/{call_attempt_id}/retry",
    response_model=DataResponse[StartCallResult],
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_call(
    call_attempt_id: uuid.UUID,
    session: SessionDep,
    settings: EffectiveSettingsDep,
    request: Request,
    body: RetryCallRequest | None = None,
) -> dict[str, Any]:
    """Call this attempt's candidate again (a new `manual` attempt) when eligible.
    `max_attempts_reached` → ask the recruiter, then send `override_limit: true`."""
    result = await call_service.retry(
        session,
        call_attempt_id,
        settings,
        enqueue_initiate_call,
        voice_ready=voice_ready(request, settings),
        override_limit=bool(body and body.override_limit),
        call_again=bool(body and body.call_again),
    )
    if result.attempt_id:
        await sync_service.request_sync(settings)
    return ok(result.as_dict())


@router.post("/{call_attempt_id}/cancel", response_model=DataResponse[CallAttemptOut])
async def cancel_call(
    call_attempt_id: uuid.UUID,
    session: SessionDep,
    redis: RedisDep,
    settings: EffectiveSettingsDep,
    user: CurrentUser,
) -> dict[str, Any]:
    """Cancel a call that hasn't dialed yet (pending, queued, retry or callback scheduled)."""
    attempt = await call_service.cancel(session, redis, call_attempt_id, settings, user_id=user.id)
    await sync_service.request_sync(settings)
    return ok(attempt)


@router.post("/{call_attempt_id}/hangup", response_model=DataResponse[HangupResult])
async def hangup_call(
    call_attempt_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> dict[str, Any]:
    """Safety control: end a call in progress. The agent says its closing line and hangs up
    (the flow's Hangup step ends the call). Only a call this server is handling."""
    attempt = await call_service.get(session, call_attempt_id)
    if attempt.call_status != CallStatus.IN_PROGRESS:
        raise conflict(
            "call_not_in_progress",
            "Only a call in progress can be ended",
            {"call_status": attempt.call_status},
        )
    live = REGISTRY.get(str(attempt.id))
    end = getattr(live, "end_by_recruiter", None)
    if end is None:
        raise not_found("call_session_not_found", "This call isn't connected to the AI right now")
    return ok({"call_attempt_id": attempt.id, "ending": bool(end())})
