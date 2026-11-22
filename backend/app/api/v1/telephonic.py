"""Telephonic round questions for a requirement: generate from the JD, edit, approve."""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.api.responses import ok
from app.providers.llm import create_question_llm
from app.providers.llm.base import LLMProvider
from app.schemas.common import DataResponse
from app.schemas.telephonic import DraftUpdate, GenerateRequest, QuestionSetOut, TelephonicOut
from app.services import telephonic_service

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
