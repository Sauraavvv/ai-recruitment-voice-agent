"""Telephonic round for a requirement: questions (generate from the JD, edit, approve) and the
calls that ask them."""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import CurrentUser, EffectiveSettingsDep, SessionDep, SettingsDep
from app.api.responses import ok
from app.api.v1.calls import voice_ready
from app.providers.llm import create_question_llm
from app.providers.llm.base import LLMProvider
from app.schemas.call import StartCallResult
from app.schemas.common import DataResponse
from app.schemas.telephonic import (
    DraftUpdate,
    GenerateRequest,
    QuestionSetOut,
    RoundRoster,
    TelephonicCallsRequest,
    TelephonicOut,
)
from app.services import telephonic_calls, telephonic_service
from app.utils.queue import enqueue_initiate_call

router = APIRouter(prefix="/requirements/{requirement_id}/telephonic", tags=["telephonic"])


async def get_question_llm(settings: SettingsDep) -> AsyncIterator[LLMProvider | None]:
    """The AI that writes questions, or None when it isn't configured (tests replace this)."""
    if not settings.groq_keys:
        yield None
        return
    llm = create_question_llm(settings)
    try:
        yield llm
    finally:
        await llm.aclose()


QuestionLLM = Annotated[LLMProvider | None, Depends(get_question_llm)]


@router.get("", response_model=DataResponse[TelephonicOut])
async def get_telephonic(
    requirement_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> dict[str, Any]:
    """The draft (if any), the latest approved set, and whether questions can be generated."""
    return ok(await telephonic_service.get_state(session, user, requirement_id, settings))


@router.post("/generate", response_model=DataResponse[QuestionSetOut])
async def generate_questions(
    requirement_id: uuid.UUID,
    body: GenerateRequest,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    llm: QuestionLLM,
) -> dict[str, Any]:
    """Write questions from the JD with AI. They replace the current draft. Takes a while
    (the model reasons first). 422 no_jd, 503 ai_not_configured / ai_unavailable, 504 ai_timeout,
    502 ai_bad_output / ai_rejected."""
    draft = await telephonic_service.generate(session, user, requirement_id, body, llm, settings)
    return ok(QuestionSetOut.model_validate(draft))


@router.put("/draft", response_model=DataResponse[QuestionSetOut])
async def save_draft(
    requirement_id: uuid.UUID, body: DraftUpdate, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    """Save the questions as edited (in order). Creates a draft when there's none."""
    draft = await telephonic_service.save_draft(session, user, requirement_id, body.questions)
    return ok(QuestionSetOut.model_validate(draft))


@router.delete("/draft", response_model=DataResponse[None])
async def discard_draft(
    requirement_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    await telephonic_service.discard_draft(session, user, requirement_id)
    return ok(None)


@router.post("/approve", response_model=DataResponse[QuestionSetOut])
async def approve_questions(
    requirement_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> dict[str, Any]:
    """Freeze the draft as the set used on telephonic calls (a new version)."""
    approved = await telephonic_service.approve(session, user, requirement_id)
    return ok(QuestionSetOut.model_validate(approved))


@router.post(
    "/calls",
    response_model=DataResponse[list[StartCallResult]],
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_telephonic_calls(
    requirement_id: uuid.UUID,
    body: TelephonicCallsRequest,
    user: CurrentUser,
    session: SessionDep,
    settings: EffectiveSettingsDep,
    request: Request,
) -> dict[str, Any]:
    """Queue telephonic round calls: the listed candidates of this requirement, or (none listed)
    up to 20 interested candidates not called yet. Each call asks the latest approved question
    set, pinned now. One result per candidate (ok or a reason): not_interested,
    screening_not_completed, no_approved_questions, telephonic_done (send `call_again`),
    max_attempts_reached (send `override_limit`), and the screening call's reasons.
    `dry_run`: only the results, nothing queued."""
    results = await telephonic_calls.start(
        session,
        user,
        requirement_id,
        body,
        settings,
        enqueue_initiate_call,
        voice_ready=voice_ready(request, settings),
    )
    return ok([r.as_dict() for r in results])  # the sheet shows screening calls only


@router.get("/candidates", response_model=DataResponse[RoundRoster])
async def telephonic_candidates(
    requirement_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: EffectiveSettingsDep,
    request: Request,
) -> dict[str, Any]:
    """The requirement's interested candidates and where each stands in the round: status,
    latest round call (and the question set version it asked), whether they can be called."""
    return ok(
        await telephonic_calls.roster(
            session,
            user,
            requirement_id,
            settings,
            voice_ready=voice_ready(request, settings),
        )
    )
