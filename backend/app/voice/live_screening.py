"""Live screening over a real call: a preview of Phase 6 on top of the Phase 5 stream.

    caller audio (8 kHz PCM) → Deepgram STT → UtteranceAssembler → ConversationManager
    → reply text → TTS stream → 24 kHz→8 kHz → paced frames → mark → listen again

Reuses the Phase 4 `VoiceLoop` unchanged. Not here yet (Phase 6): barge-in, local VAD end of
turn, acknowledgement masking, merging split utterances. At the end, the result is stored
(`services/screening_store.py`).
"""

import asyncio
import contextlib
import time
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from app.agent.conversation_manager import ConversationManager, ScreeningResult
from app.agent.prompts import CandidateContext, JobConfig
from app.config import Settings
from app.database.connection import get_sessionmaker
from app.database.models import CallAttempt, Candidate, Job
from app.providers.llm import create_llm_provider
from app.providers.stt import create_stt_provider
from app.providers.tts.base import TTSError, TTSProvider
from app.services import screening_store
from app.utils.log import get_logger
from app.voice import audio_converter as ac
from app.voice.local_loop import VoiceLoop

if TYPE_CHECKING:
    from app.voice.websocket_handler import CallSession

logger = get_logger(__name__)

SILENCE_TIMEOUT_S = 10.0
MARK_GRACE_S = 5.0


def job_config(job: Job) -> JobConfig:
    return JobConfig.from_dict(
        {
            "id": str(job.id),
            "job_title": job.job_title,
            "company_name": job.company_name,
            "job_description": job.job_description,
            "location": job.location,
            "required_experience": job.required_experience,
            "skills": job.skills,
            "screening_questions": job.screening_questions,
            "agent_instructions": job.agent_instructions,
        }
    )


async def _load(attempt_id: uuid.UUID) -> tuple[CallAttempt, Candidate, Job]:
    async with get_sessionmaker()() as db:
        attempt = await db.get(CallAttempt, attempt_id)
        assert attempt is not None
        candidate = await db.get(Candidate, attempt.candidate_id)
        assert candidate is not None
        job = await db.get(Job, candidate.job_id)
        assert job is not None
        return attempt, candidate, job


class LiveScreening:
    def __init__(self, session: "CallSession", settings: Settings, tts: TTSProvider) -> None:
        self.session = session
        self.settings = settings
        self.tts = tts
        self.loop: VoiceLoop | None = None
        self._replies = 0
        self.result: ScreeningResult | None = None

    def caller_hung_up(self) -> None:
        if self.loop is not None:
            self.loop.hangup()

    async def _frames(self) -> AsyncIterator[bytes]:
        while True:
            yield await self.session.inbound.get()

    async def _speak(self, text: str) -> None:
        """Stream the reply into the call and return once Exotel says it has been played."""
        from app.voice.websocket_handler import _send_mark, _wait_mark

        sender = self.session.sender
        resampler: ac.StreamResampler | None = None
        started = time.monotonic()
        first_audio_ms: float | None = None
        try:
            async for clip in self.tts.stream(text, call_attempt_id=self.session.attempt_id):
                if resampler is None:
                    resampler = ac.StreamResampler(clip.sample_rate, sender.rate)
                if first_audio_ms is None:
                    first_audio_ms = (time.monotonic() - started) * 1000
                await sender.push(resampler.process(clip.pcm))
        except TTSError as exc:
            logger.warning("live_tts_failed", error=str(exc))
            clip = self.tts.apology_clip(call_attempt_id=self.session.attempt_id)
            resampler = ac.StreamResampler(clip.sample_rate, sender.rate)
            await sender.push(resampler.process(clip.pcm))
        await sender.play(resampler.flush() if resampler else b"")
        self._replies += 1
        name = f"reply-{self._replies}"
        await _send_mark(self.session, name)
        await _wait_mark(self.session, name, timeout=sender.buffered_s + MARK_GRACE_S)
        logger.info(
            "live_reply_played",
            reply=self._replies,
            tts_first_audio_ms=None if first_audio_ms is None else int(first_audio_ms),
            total_ms=int((time.monotonic() - started) * 1000),
        )
        # The candidate's words while the agent was talking aren't barge-in yet (Phase 6)
        self.session.capture.note(f"agent: {text}")

    async def run(self) -> None:
        settings = self.settings
        attempt_id = uuid.UUID(self.session.attempt_id)
        attempt, candidate, job = await _load(attempt_id)
        config = job_config(job)
        llm = create_llm_provider(settings)
        stt = create_stt_provider(
            settings, keyterms=[k for k in (job.company_name, job.location) if k]
        )
        manager = ConversationManager(
            config,
            CandidateContext(
                name=candidate.name, candidate_id=str(candidate.id), call_id=str(attempt.id)
            ),
            llm,
            timeout_s=settings.openai_timeout_s,
        )
        self.loop = VoiceLoop(
            stt,
            manager,
            session_id=self.session.attempt_id,
            encoding="linear16",
            sample_rate=settings.telephony_sample_rate,
            speak=self._speak,
            silence_timeout_s=SILENCE_TIMEOUT_S,
            out=lambda _line: None,  # turns are logged as `voice_turn`
            drop_stale=True,
        )
        watchdog = asyncio.create_task(self._limit_duration())
        try:
            self.result = await self.loop.run(self._frames())
        finally:
            watchdog.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watchdog
        try:
            await screening_store.save_result(
                attempt_id=attempt_id,
                candidate_id=candidate.id,
                result=self.result,
                job_title=job.job_title,
                candidate_name=candidate.name,
                llm=llm,
            )
        finally:
            await llm.aclose()
        if not self.session.stop_reason:  # the agent finished: hang up from our side
            self.session.hangup_requested = True

    async def _limit_duration(self) -> None:
        await asyncio.sleep(self.settings.max_call_duration_s)
        logger.warning("live_call_max_duration", call_attempt_id=self.session.attempt_id)
        self.caller_hung_up()


def describe(result: ScreeningResult) -> dict[str, Any]:
    return {
        "end_reason": result.end_reason.value,
        "screening_status": result.screening_status.value,
        "answers": {k: v for k, v in result.collected_data.items() if v is not None},
        "missing": result.missing_fields,
        "turns": result.turns,
    }
