"""Exotel Voicebot media stream → screening conversation (phase-06; protocol from phase-05).

Lifecycle of one stream:
  accept → `connected` → `start` (resolve + verify the attempt, check the media format) →
  build the conversation (`voice/pipeline.CallSession`) and register it → receive loop
  (media → inbound queue, mark → MarkTracker, stop → caller hung up) alongside `session.run()`
  → the agent hangs up (we close the socket; the flow's Hangup step drops the call) or the caller
  does → cleanup: tasks cancelled, session unregistered, voice state forgotten, the attempt's
  end_reason set, the concurrency slot released, `finalize_call` queued.

The PoC line checks from Phase 5 (`voice/telephony_poc.py`) still run when a test call asks for
mode `full` or `listen` (`make test-call mode=…`).
"""

import asyncio
import base64
import binascii
import contextlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from fastapi import WebSocket, WebSocketDisconnect

from app.agent.conversation_manager import ConversationManager
from app.agent.prompts import CandidateContext, JobConfig
from app.config import Settings
from app.database.connection import get_sessionmaker
from app.database.models import CallAttempt, CallEndReason, Candidate, Job
from app.providers.llm import create_llm_provider
from app.providers.llm.base import LLMError
from app.providers.realtime import OpenAIRealtimeClient
from app.providers.stt import create_stt_provider
from app.providers.telephony import exotel_models as em
from app.providers.tts.base import TTSProvider
from app.services import call_service, screening_store, settings_service, transcript_service
from app.utils.log import get_logger
from app.utils.queue import enqueue_finalize_call
from app.utils.redis import KEY_PREFIX, get_redis
from app.voice import audio_converter as ac
from app.voice import pcm as pcm_utils
from app.voice.audio_processor import InboundQueue
from app.voice.pipeline import CallContext, CallSession, SessionOutcome
from app.voice.playback import AudioSender, MarkTracker
from app.voice.realtime_session import RealtimeCallSession
from app.voice.session_registry import REGISTRY, SessionExistsError, live_task_count
from app.voice.telephony_poc import PocSession, run_poc
from app.voice.vad import SpeechDetector, default_classifier

logger = get_logger(__name__)

START_TIMEOUT_S = 10.0
INBOUND_QUEUE_SECONDS = 2.0
POC_MODE_KEY = KEY_PREFIX + "call:{attempt_id}:poc_mode"
POC_MODES = ("full", "listen", "screen")  # screen = the normal conversation
SAVE_GRACE_S = 30.0  # after the caller hangs up, time to finish and store the conversation
MAX_LOGGED_MEDIA = 30  # media messages kept in the capture's message log

SESSIONS = REGISTRY  # live sessions in this process, by call_attempt_id


# --- Capture (debugging, testers' phones only) ------------------------------------------------


@dataclass
class StreamCapture:
    """What came in on the stream: counts, timing, first message of each type, audio."""

    started: float = field(default_factory=time.monotonic)
    counts: dict[str, int] = field(default_factory=dict)
    first_shapes: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    media_bytes: int = 0
    media_sizes: dict[int, int] = field(default_factory=dict)
    first_media_at: float | None = None
    last_media_at: float | None = None
    last_sequence: int | None = None
    sequence_gaps: int = 0
    audio: bytearray = field(default_factory=bytearray)
    keep_audio: bool = False
    notes: list[str] = field(default_factory=list)

    def t(self) -> float:
        return round(time.monotonic() - self.started, 3)

    def note(self, text: str) -> None:
        self.notes.append(f"{self.t():8.3f}s {text}")

    def record(self, message: dict[str, Any], payload_len: int | None) -> None:
        kind = str(message.get("event", "?"))
        self.counts[kind] = self.counts.get(kind, 0) + 1
        if kind not in self.first_shapes:
            self.first_shapes[kind] = em.message_shape(message)
            logger.info("stream_first_message", message_type=kind, shape=self.first_shapes[kind])
        seq = message.get("sequence_number")
        try:
            seq_i = int(seq) if seq is not None else None
        except (TypeError, ValueError):
            seq_i = None
        if seq_i is not None and self.last_sequence is not None and seq_i != self.last_sequence + 1:
            self.sequence_gaps += 1
        if seq_i is not None:
            self.last_sequence = seq_i
        if kind != "media" or self.counts[kind] <= MAX_LOGGED_MEDIA:
            self.messages.append({"t": self.t(), "message": sanitize(message)})
        if payload_len is not None:
            now = time.monotonic()
            self.first_media_at = self.first_media_at or now
            self.last_media_at = now
            self.media_bytes += payload_len
            self.media_sizes[payload_len] = self.media_sizes.get(payload_len, 0) + 1

    def inbound_rate(self) -> float | None:
        if not (self.first_media_at and self.last_media_at) or self.counts.get("media", 0) < 10:
            return None
        span = self.last_media_at - self.first_media_at
        n = self.counts["media"]
        # n chunks span n-1 intervals; scale bytes accordingly
        return self.media_bytes * (n - 1) / n / span if span > 0 else None

    def summary(self) -> dict[str, Any]:
        return {
            "counts": self.counts,
            "media_bytes": self.media_bytes,
            "media_chunk_sizes": self.media_sizes,
            "inbound_bytes_per_second": round(self.inbound_rate() or 0, 1),
            "sequence_gaps": self.sequence_gaps,
            "notes": self.notes,
        }


_SENSITIVE = {"from", "to", "account_sid"}


def sanitize(message: Any) -> Any:
    """Copy of a stream message safe to keep: audio replaced by its length, numbers masked."""
    if isinstance(message, dict):
        out: dict[str, Any] = {}
        for k, v in message.items():
            if k == "payload" and isinstance(v, str):
                out[k] = f"<base64 {len(v)} chars>"
            elif k in _SENSITIVE and isinstance(v, str):
                out[k] = ("…" + v[-2:]) if len(v) > 5 else "…"
            else:
                out[k] = sanitize(v)
        return out
    if isinstance(message, list):
        return [sanitize(v) for v in message]
    return message


# --- Building the conversation ----------------------------------------------------------------


def job_config(job: Job, settings: Settings | None = None) -> JobConfig:
    """The job as the agent uses it; `settings` (effective) adds the Settings page's
    introduction template and organization name."""
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
            "introduction_template": settings.agent_introduction if settings else None,
            "organization": settings.organization_name if settings else None,
        }
    )


async def load_context(
    attempt_id: uuid.UUID, provider_call_id: str | None, settings: Settings
) -> CallContext:
    async with get_sessionmaker()() as db:
        attempt = await db.get(CallAttempt, attempt_id)
        assert attempt is not None
        candidate = await db.get(Candidate, attempt.candidate_id)
        assert candidate is not None
        job = await db.get(Job, candidate.job_id)
        assert job is not None
        effective = await settings_service.effective(db, settings)
    return CallContext(
        attempt_id=str(attempt_id),
        job=job_config(job, effective),
        candidate=CandidateContext(
            name=candidate.name, candidate_id=str(candidate.id), call_id=str(attempt_id)
        ),
        candidate_id=candidate.id,
        provider_call_id=provider_call_id,
        keyterms=[k for k in (job.company_name, job.location) if k],
    )


def make_vad(settings: Settings) -> SpeechDetector:
    classifier, name = default_classifier(
        settings.telephony_sample_rate, settings.vad_aggressiveness
    )
    return SpeechDetector(
        classifier,
        start_ms=settings.vad_speech_start_ms,
        end_silence_ms=settings.vad_end_silence_ms,
        min_dbfs=settings.vad_min_dbfs,
        echo_margin_db=settings.vad_echo_margin_db,
        name=name,
    )


async def store_outcome(ctx: CallContext, outcome: SessionOutcome) -> None:
    """At the end of the conversation: final transcript and result, then queue the summary."""
    assert ctx.candidate_id is not None
    await screening_store.store_outcome(
        attempt_id=uuid.UUID(ctx.attempt_id),
        candidate_id=ctx.candidate_id,
        result=outcome.result,
        extra={
            "turn_metrics": outcome.metrics,
            "session": {k: v for k, v in outcome.stats.items() if k != "turn_history"},
            "end_reason": outcome.end_reason.value,
        },
    )
    try:
        await enqueue_finalize_call(ctx.attempt_id)
    except Exception:
        logger.exception("finalize_enqueue_failed", call_attempt_id=ctx.attempt_id)


class _Closable(Protocol):
    async def aclose(self) -> None: ...


@dataclass
class Conversation:
    session: CallSession | RealtimeCallSession
    llm: _Closable  # closed when the stream ends


class _RealtimeCloser:
    def __init__(self, client: OpenAIRealtimeClient) -> None:
        self.client = client

    async def aclose(self) -> None:
        await self.client.close()


async def build_conversation(
    settings: Settings,
    attempt_id: str,
    provider_call_id: str | None,
    *,
    tts: TTSProvider | None,
    sender: AudioSender,
    inbound: InboundQueue,
    marks: MarkTracker,
) -> Conversation | str:
    """The session for a real call, or why there can't be one. The engine comes from the
    effective settings (Settings page, else VOICE_ENGINE)."""
    effective = await settings_service.effective_new_session(settings)
    if effective.voice_engine == "realtime":
        return await build_realtime_conversation(
            effective, attempt_id, provider_call_id, sender=sender, inbound=inbound, marks=marks
        )
    if tts is None or not tts.status().ready:
        return "voice_unavailable"
    try:
        llm = create_llm_provider(settings)
    except LLMError:
        return "llm_not_configured"
    ctx = await load_context(uuid.UUID(attempt_id), provider_call_id, settings)
    manager = ConversationManager(ctx.job, ctx.candidate, llm, timeout_s=settings.openai_timeout_s)
    await transcript_service.open_conversation(uuid.UUID(attempt_id))
    session = CallSession(
        ctx,
        settings=settings,
        sender=sender,
        inbound=inbound,
        marks=marks,
        stt=create_stt_provider(settings, keyterms=ctx.keyterms),
        tts=tts,
        manager=manager,
        vad=make_vad(settings),
        writer=transcript_service.TranscriptWriter(uuid.UUID(attempt_id)),
        on_end=lambda outcome: store_outcome(ctx, outcome),
    )
    return Conversation(session, llm)


async def build_realtime_conversation(
    settings: Settings,
    attempt_id: str,
    provider_call_id: str | None,
    *,
    sender: AudioSender,
    inbound: InboundQueue,
    marks: MarkTracker,
) -> Conversation | str:
    """Trial engine: OpenAI Realtime speech-to-speech (voice/realtime_session.py)."""
    if settings.openai_api_key is None:
        return "llm_not_configured"
    ctx = await load_context(uuid.UUID(attempt_id), provider_call_id, settings)
    await transcript_service.open_conversation(uuid.UUID(attempt_id))
    client = OpenAIRealtimeClient(
        settings.openai_api_key.get_secret_value(), settings.openai_realtime_model
    )
    session = RealtimeCallSession(
        ctx,
        settings=settings,
        sender=sender,
        inbound=inbound,
        marks=marks,
        client=client,
        writer=transcript_service.TranscriptWriter(uuid.UUID(attempt_id)),
        on_end=lambda outcome: store_outcome(ctx, outcome),
    )
    logger.info("conversation_engine", call_attempt_id=attempt_id, engine="realtime")
    return Conversation(session, _RealtimeCloser(client))


# --- Stream entry point -----------------------------------------------------------------------


async def _receive_json(ws: WebSocket) -> dict[str, Any]:
    raw = await ws.receive_text()
    message = json.loads(raw)
    return message if isinstance(message, dict) else {"event": "?", "_raw": message}


async def handle_exotel_stream(ws: WebSocket, settings: Settings) -> None:
    await ws.accept()
    capture = StreamCapture(keep_audio=bool(settings.telephony_capture_dir))
    tasks_before = live_task_count()
    try:
        start_msg: dict[str, Any] | None = None
        async with asyncio.timeout(START_TIMEOUT_S):
            while start_msg is None:
                message = await _receive_json(ws)
                capture.record(message, None)
                if message.get("event") == "start":
                    start_msg = message
    except (TimeoutError, WebSocketDisconnect, ValueError) as exc:
        logger.warning("stream_no_start", error=type(exc).__name__)
        with contextlib.suppress(Exception):
            await ws.close(code=1008)
        return

    start = em.parse_stream_start(start_msg)
    if not em.media_format_matches(
        start, encoding=settings.telephony_encoding, sample_rate=settings.telephony_sample_rate
    ):
        logger.error(
            "stream_media_format_mismatch",
            announced_encoding=start.encoding,
            announced_rate=start.sample_rate,
            configured_encoding=settings.telephony_encoding,
            configured_rate=settings.telephony_sample_rate,
        )
        await ws.close(code=1003)
        return

    async with get_sessionmaker()() as db:
        attempt = await call_service.attach_stream(db, start)
    if attempt is None:
        logger.warning("stream_unknown_call", provider_call_id=start.call_sid)
        await ws.close(code=1008)
        return

    attempt_id = str(attempt.id)
    log = logger.bind(call_attempt_id=attempt_id, provider_call_id=start.call_sid)
    log.info(
        "stream_started",
        stream_sid=start.stream_sid,
        encoding=start.encoding,
        sample_rate=start.sample_rate,
        custom_parameters=sorted(start.custom_parameters),
    )
    sender = AudioSender(
        ws,
        start.stream_sid or "",
        encoding=settings.telephony_encoding,
        sample_rate=settings.telephony_sample_rate,
        frame_bytes=settings.telephony_frame_bytes,
        send_ahead_ms=settings.telephony_send_ahead_ms,
        session_id=attempt_id,
    )
    max_inbound = int(
        ac.bytes_per_second("slin", settings.telephony_sample_rate) * INBOUND_QUEUE_SECONDS
    )
    inbound = InboundQueue(max_inbound)
    marks = MarkTracker()
    tts: TTSProvider | None = getattr(ws.app.state, "tts", None)

    mode = "screen"
    with contextlib.suppress(Exception):
        mode = await get_redis().get(POC_MODE_KEY.format(attempt_id=attempt_id)) or "screen"

    conversation: Conversation | None = None
    poc: PocSession | None = None
    end_reason: str | None = None
    failure: str | None = None
    ended_by = "error"
    on_stop: Callable[[str], None]
    main: asyncio.Task[Any]
    try:
        if mode in ("full", "listen"):
            poc = PocSession(attempt_id, sender, inbound, marks, capture.notes)
            main = asyncio.create_task(run_poc(poc, mode, tts, settings), name="poc")
            on_stop = lambda _reason: inbound.close()  # noqa: E731
        else:
            built = await build_conversation(
                settings,
                attempt_id,
                start.call_sid,
                tts=tts,
                sender=sender,
                inbound=inbound,
                marks=marks,
            )
            if isinstance(built, str):
                log.error("conversation_unavailable", reason=built)
                end_reason, failure = CallEndReason.TECHNICAL_FAILURE.value, built
                await ws.close(code=1011)
                await _stream_closed(settings, attempt_id, "error", end_reason, failure, log)
                return
            conversation = built
            main = asyncio.create_task(conversation.session.run(), name=f"call:{attempt_id[:8]}")
            on_stop = conversation.session.caller_hung_up
        REGISTRY.register(attempt_id, conversation.session if conversation else poc)
    except SessionExistsError:
        log.error("stream_duplicate_session")
        await ws.close(code=1008)
        return
    except Exception:
        log.exception("conversation_setup_failed")
        end_reason, failure = CallEndReason.TECHNICAL_FAILURE.value, "setup_failed"
        with contextlib.suppress(Exception):
            await ws.close(code=1011)
        await _stream_closed(settings, attempt_id, "error", end_reason, failure, log)
        return

    receiver = asyncio.create_task(
        _receive_loop(ws, capture, inbound, marks, on_stop, settings.telephony_encoding)
    )
    try:
        done, _ = await asyncio.wait({receiver, main}, return_when=asyncio.FIRST_COMPLETED)
        if main in done and (conversation is not None or (poc and poc.hangup_requested)):
            ended_by = "agent"
            with contextlib.suppress(Exception):
                await ws.close(code=1000)
        else:
            if receiver not in done:  # PoC listen mode: wait for the caller
                await receiver
            stopped = receiver.result() if not receiver.cancelled() else "disconnect"
            ended_by = "caller" if stopped == "stop" else "error"
            on_stop(stopped)
            await asyncio.wait({main}, timeout=SAVE_GRACE_S)
        if conversation is not None and main.done() and not main.cancelled():
            if main.exception() is not None:
                log.error("session_crashed", error=repr(main.exception()))
                end_reason, failure = CallEndReason.TECHNICAL_FAILURE.value, "session_crashed"
            else:
                outcome: SessionOutcome = main.result()
                ended_by = outcome.ended_by if ended_by == "agent" else ended_by
                end_reason, failure = outcome.end_reason.value, outcome.failure_reason
    finally:
        for task in (receiver, main):
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        REGISTRY.unregister(attempt_id)
        if conversation is not None:
            with contextlib.suppress(Exception):
                await conversation.llm.aclose()
        if tts is not None:
            tts.forget_call(attempt_id)
        await asyncio.sleep(0)
        summary = capture.summary() | {
            "mode": mode,
            "ended_by": ended_by,
            "end_reason": end_reason,
            "failure_reason": failure,
            "frames_sent": sender.frames_sent,
            "clears": sender.clears,
            "mark_latency_s": marks.latencies(),
            "dropped_inbound_bytes": inbound.dropped_bytes,
            "tasks_before": tasks_before,
            "tasks_after": live_task_count(),
        }
        _save_capture(settings, attempt_id, capture, summary)
        log.info(
            "stream_ended",
            **{
                k: summary[k]
                for k in (
                    "mode",
                    "ended_by",
                    "end_reason",
                    "failure_reason",
                    "counts",
                    "inbound_bytes_per_second",
                    "frames_sent",
                    "tasks_before",
                    "tasks_after",
                    "dropped_inbound_bytes",
                )
            },
        )
        await _stream_closed(settings, attempt_id, ended_by, end_reason, failure, log)


async def _stream_closed(
    settings: Settings,
    attempt_id: str,
    ended_by: str,
    end_reason: str | None,
    failure: str | None,
    log: Any,
) -> None:
    try:
        async with get_sessionmaker()() as db:
            await call_service.stream_ended(
                db,
                get_redis(),
                settings,
                uuid.UUID(attempt_id),
                ended_by=ended_by,
                end_reason=end_reason,
                failure_reason=failure,
            )
    except Exception:
        log.exception("stream_end_update_failed")


async def _receive_loop(
    ws: WebSocket,
    capture: StreamCapture,
    inbound: InboundQueue,
    marks: MarkTracker,
    on_stop: Callable[[str], None],
    encoding: ac.Encoding,
) -> str:
    """Returns "stop" when Exotel ended the stream, "disconnect" when the socket dropped."""
    while True:
        try:
            message = await _receive_json(ws)
        except WebSocketDisconnect:
            capture.note("websocket closed by Exotel")
            return "disconnect"
        except ValueError:
            capture.note("non-JSON message ignored")
            continue
        kind = message.get("event")
        if kind == "media":
            payload = (message.get("media") or {}).get("payload") or ""
            try:
                raw = base64.b64decode(payload)
            except (binascii.Error, ValueError):
                capture.record(message, 0)
                continue
            capture.record(message, len(raw))
            pcm = ac.from_telephony(raw, encoding=encoding)
            if capture.keep_audio:
                capture.audio.extend(pcm)
            inbound.put(pcm)
        elif kind == "mark":
            capture.record(message, None)
            name = str((message.get("mark") or {}).get("name", ""))
            marks.note_returned(name)
        elif kind == "stop":
            capture.record(message, None)
            reason = str((message.get("stop") or {}).get("reason") or "stop")
            capture.note(f"stop received: {reason}")
            on_stop("stop")
            return "stop"
        else:  # dtmf, clear acks, anything new
            capture.record(message, None)


def _save_capture(
    settings: Settings, attempt_id: str, capture: StreamCapture, summary: dict[str, Any]
) -> None:
    """Testers' phones only: inbound WAV + message log (gitignored artifacts/)."""
    if not settings.telephony_capture_dir:
        return
    try:
        folder = Path(settings.telephony_capture_dir)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{attempt_id}_in.wav").write_bytes(
            pcm_utils.wav_bytes(bytes(capture.audio), settings.telephony_sample_rate)
        )
        (folder / f"{attempt_id}_stream.json").write_text(
            json.dumps(
                {
                    "summary": summary,
                    "first_shapes": capture.first_shapes,
                    "messages": capture.messages,
                },
                indent=2,
                default=str,
            )
        )
    except OSError:
        logger.exception("stream_capture_save_failed", call_attempt_id=attempt_id)
