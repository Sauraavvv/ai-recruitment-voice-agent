"""Store a call's result at the end of the conversation (no LLM, before finalization).

`conversations` gets the final transcript and the live result. The candidate record is NOT
changed here: finalization (finalization_service, the `finalize_call` job a few seconds later)
reconciles, validates and writes it in one transaction with the Sheets outbox row.

One exception: an opt-out is written at once (it only ever changes false → true), so no other
call can be placed to someone who asked not to be called while finalization is still queued.
"""

import uuid
from typing import Any

from sqlalchemy import select

from app.agent.conversation_manager import ScreeningResult
from app.database.connection import get_sessionmaker
from app.database.models import Candidate, Conversation, ScreeningStatus
from app.services import sync_service
from app.services.transcript_service import compact
from app.utils.log import get_logger

logger = get_logger(__name__)


async def store_outcome(
    *,
    attempt_id: uuid.UUID,
    candidate_id: uuid.UUID,
    result: ScreeningResult,
    extra: dict[str, Any] | None = None,
) -> Conversation:
    data = result.to_dict()
    data.pop("transcript", None)
    async with get_sessionmaker()() as db:
        conversation = (
            await db.execute(
                select(Conversation)
                .where(Conversation.call_attempt_id == attempt_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if conversation is None:
            conversation = Conversation(call_attempt_id=attempt_id)
            db.add(conversation)
        conversation.transcript = [compact(e) for e in result.transcript]
        conversation.extracted_data = {**(conversation.extracted_data or {}), **(extra or {})} | {
            "result": data,
        }
        conversation.screening_completed = result.screening_status == ScreeningStatus.COMPLETED

        if result.opted_out:
            candidate = await db.get(Candidate, candidate_id, with_for_update=True)
            if candidate is not None and not candidate.opted_out:
                candidate.opted_out = True
                candidate.screening_status = ScreeningStatus.OPTED_OUT.value
                sync_service.record_change(db, candidate_id)
        await db.commit()
        await db.refresh(conversation)
    logger.info(
        "screening_result_stored",
        call_attempt_id=str(attempt_id),
        candidate_id=str(candidate_id),
        live_status=result.screening_status.value,
        opted_out=result.opted_out or None,
    )
    return conversation
