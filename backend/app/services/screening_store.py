"""Store a call's screening result (minimal version ahead of Phase 7).

- `conversations`: one row per attempt with the transcript, the summary and the full result.
- `candidates`: each answered standard field, its metadata (status, raw words, confidence) in
  `screening_field_meta`, `screening_status`, and `opted_out` when the candidate asked.

Phase 7 adds the post-call extraction pass, the Sheets outbox and field-level conflict rules.
"""

import uuid
from typing import Any

from sqlalchemy import select

from app.agent.conversation_manager import ScreeningResult
from app.agent.schemas import FieldName
from app.database.connection import get_sessionmaker
from app.database.models import Candidate, Conversation, ScreeningStatus
from app.providers.llm.base import LLMProvider
from app.services.summary_service import generate_summary
from app.utils.log import get_logger

logger = get_logger(__name__)

STANDARD_FIELDS = {f.value for f in FieldName}


async def save_result(
    *,
    attempt_id: uuid.UUID,
    candidate_id: uuid.UUID,
    result: ScreeningResult,
    job_title: str,
    candidate_name: str,
    llm: LLMProvider | None,
) -> Conversation:
    summary = await generate_summary(
        result, candidate_name=candidate_name, job_title=job_title, llm=llm
    )
    data = result.to_dict()
    data.pop("transcript", None)
    async with get_sessionmaker()() as db:
        conversation = (
            await db.execute(select(Conversation).where(Conversation.call_attempt_id == attempt_id))
        ).scalar_one_or_none()
        if conversation is None:
            conversation = Conversation(call_attempt_id=attempt_id)
            db.add(conversation)
        conversation.transcript = result.transcript
        conversation.summary = summary.text
        conversation.extracted_data = data | {"summary_sections": summary.model_dump(mode="json")}
        conversation.screening_completed = result.screening_status == ScreeningStatus.COMPLETED

        candidate = await db.get(Candidate, candidate_id, with_for_update=True)
        assert candidate is not None
        stored: dict[str, Any] = {}
        meta = dict(candidate.screening_field_meta or {})
        for key, value in result.collected_data.items():
            if key not in STANDARD_FIELDS or value is None:
                continue
            setattr(candidate, key, value)
            stored[key] = value
            meta[key] = {**result.fields.get(key, {}), "call_attempt_id": str(attempt_id)}
        candidate.screening_field_meta = meta
        candidate.screening_status = result.screening_status.value
        if result.opted_out:
            candidate.opted_out = True
        await db.commit()
        await db.refresh(conversation)
    logger.info(
        "screening_saved",
        call_attempt_id=str(attempt_id),
        candidate_id=str(candidate_id),
        screening_status=result.screening_status.value,
        fields_stored=sorted(stored),
        summary_by=summary.generated_by,
    )
    return conversation
