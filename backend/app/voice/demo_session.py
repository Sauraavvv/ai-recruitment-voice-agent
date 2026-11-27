"""Browser demo call ("Try a demo call" on the home page).

The visitor talks to the screening agent in the browser: no phone, no provider, nothing stored.
The browser speaks the same messages as a phone stream, so the voice pipeline runs unchanged:

  browser → server   {"event": "start", "name": "Asha"}            first message
                     {"event": "media", "media": {"payload": …}}   16-bit PCM, mono, 8 kHz, base64
                     {"event": "mark", "mark": {"name": …}}        audio before the mark has played
                     {"event": "stop"}                             the visitor ended the call
  server → browser   {"event": "ready", "max_seconds": 150}
                     media / mark / clear                          the agent's voice (same format)
                     {"event": "transcript", "lines": […]}         whenever it changes
                     {"event": "answers", "fields": […]}           whenever it changes
                     {"event": "ended", "reason": …, "fields": […]}
                     {"event": "error", "code": …, "message": …}   then the socket closes

Limits: no phone, but not free, so a visitor (IP address) gets DEMO_CALLS_PER_IP calls (one by
default) in DEMO_IP_WINDOW_DAYS, at most DEMO_MAX_CONCURRENT run at once, and each lasts at most
DEMO_MAX_CALL_S. A call that fails on our side is given back.
"""

import asyncio
import contextlib
import hashlib
import json
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.agent.conversation_manager import ConversationManager
from app.agent.prompts import CandidateContext, JobConfig
from app.config import Settings
from app.providers.llm import create_demo_llm
from app.providers.llm.base import LLMError
from app.providers.stt import create_stt_provider
from app.providers.tts.base import TTSProvider
from app.schemas.job import default_screening_questions
from app.utils.log import get_logger
from app.utils.redis import KEY_PREFIX, get_redis
from app.voice import audio_converter as ac
from app.voice.audio_processor import InboundQueue
from app.voice.pipeline import CallContext, CallSession
from app.voice.playback import AudioSender, MarkTracker
from app.voice.websocket_handler import StreamCapture, _receive_loop, make_vad

logger = get_logger(__name__)

START_TIMEOUT_S = 15.0
PUSH_EVERY_S = 0.3
INBOUND_QUEUE_SECONDS = 2.0
MAX_NAME = 40
# A short call: the questions that show the product best
DEMO_QUESTIONS = ("interested", "total_experience", "notice_period", "current_ctc")
ACTIVE_KEY = KEY_PREFIX + "demo:active"


class DemoRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def demo_job() -> JobConfig:
    questions = [
        q.model_dump(exclude_none=True)
        for q in default_screening_questions()
        if q.key in DEMO_QUESTIONS
    ]
    return JobConfig.from_dict(
        {
            "id": "demo",
            "job_title": "Backend Developer",
            "company_name": "CallZest Demo",
            "location": "Pune",
            "job_description": "A demo role used for the CallZest website's try-it-out call.",
            "screening_questions": questions,
            "organization": "CallZest",
        }
    )


def clean_name(raw: Any) -> str:
    text = " ".join(str(raw or "").split())[:MAX_NAME]
    return "".join(ch for ch in text if ch.isalpha() or ch in " .'-").strip() or "there"


def _ip_key(client_ip: str) -> str:
    digest = hashlib.sha256(client_ip.encode()).hexdigest()[:32]
    return f"{KEY_PREFIX}demo:ip:{digest}"


async def claim(settings: Settings, client_ip: str) -> None:
    """This visitor's demo call (one per IP by default), and a free place among the running
    ones."""
    redis = get_redis()
    per_ip = _ip_key(client_ip)
    used = await redis.incr(per_ip)
    if used == 1:
        await redis.expire(per_ip, settings.demo_ip_window_days * 86400)
    if used > settings.demo_calls_per_ip:
        await redis.decr(per_ip)
        raise DemoRefused(
            "used",
            "You've already tried the demo call. Create an account to screen your own candidates.",
        )
    active = await redis.incr(ACTIVE_KEY)
    # A crashed process must not hold places forever
    await redis.expire(ACTIVE_KEY, settings.demo_max_call_s + 120)
    if active > settings.demo_max_concurrent:
        await redis.decr(ACTIVE_KEY)
        await redis.decr(per_ip)  # not their fault: don't count it
        raise DemoRefused("busy", "All demo lines are busy right now. Try again in a minute.")


async def give_back(client_ip: str) -> None:
    """The call failed on our side: the visitor keeps their demo."""
    with contextlib.suppress(Exception):
        redis = get_redis()
        if await redis.decr(_ip_key(client_ip)) <= 0:
            await redis.delete(_ip_key(client_ip))


async def release() -> None:
    with contextlib.suppress(Exception):
        redis = get_redis()
        if await redis.decr(ACTIVE_KEY) < 0:
            await redis.set(ACTIVE_KEY, 0)


def _fields(manager: ConversationManager) -> list[dict[str, Any]]:
    state = manager.state.model_dump(mode="json")
    fields = state.get("fields") or {}
    out = []
    for key in DEMO_QUESTIONS:
        record = fields.get(key) or {}
        out.append(
            {
                "key": key,
                "value": record.get("value"),
                "status": record.get("status", "missing"),
                "quote": record.get("raw_text"),
            }
        )
    return out


def _lines(manager: ConversationManager) -> list[dict[str, Any]]:
    return [
        {
            "seq": e.seq,
            "speaker": e.speaker,
            "text": e.text,
            "interrupted": e.interrupted,
        }
        for e in manager.transcript
    ]


async def _push_updates(ws: WebSocket, manager: ConversationManager) -> None:
    """Send the transcript and the answers whenever they change (the browser shows them live)."""
    last_lines: list[dict[str, Any]] = []
    last_fields: list[dict[str, Any]] = []
    while True:
        lines, fields = _lines(manager), _fields(manager)
        if lines != last_lines:
            await ws.send_text(json.dumps({"event": "transcript", "lines": lines}))
            last_lines = lines
        if fields != last_fields:
            await ws.send_text(json.dumps({"event": "answers", "fields": fields}))
            last_fields = fields
        await asyncio.sleep(PUSH_EVERY_S)


async def _refuse(ws: WebSocket, code: str, message: str) -> None:
    with contextlib.suppress(Exception):
        await ws.send_text(json.dumps({"event": "error", "code": code, "message": message}))
        await ws.close(code=1000)


async def handle_demo_stream(ws: WebSocket, settings: Settings, *, client_ip: str) -> None:
    await ws.accept()
    if not settings.demo_enabled:
        await _refuse(ws, "disabled", "The demo call is switched off right now.")
        return
    try:
        async with asyncio.timeout(START_TIMEOUT_S):
            first = json.loads(await ws.receive_text())
    except (TimeoutError, WebSocketDisconnect, ValueError):
        with contextlib.suppress(Exception):
            await ws.close(code=1008)
        return
    if not isinstance(first, dict) or first.get("event") != "start":
        await _refuse(ws, "bad_start", "The call didn't start properly. Please try again.")
        return

    tts: TTSProvider | None = getattr(ws.app.state, "tts", None)
    if tts is None or not tts.status().ready or not settings.deepgram_api_key:
        await _refuse(ws, "unavailable", "The demo voice isn't ready. Please try again shortly.")
        return
    try:
        llm = create_demo_llm(settings)  # Groq (not OpenAI): fast, strict output schema
    except LLMError:
        await _refuse(ws, "unavailable", "The demo isn't available right now.")
        return
    try:
        await claim(settings, client_ip)
    except DemoRefused as refused:
        await llm.aclose()
        await _refuse(ws, refused.code, refused.message)
        return

    demo_id = f"demo-{uuid.uuid4().hex[:12]}"
    log = logger.bind(demo_id=demo_id)
    call_settings = settings.for_demo_call()
    job = demo_job()
    candidate = CandidateContext(name=clean_name(first.get("name")), call_id=demo_id)
    ctx = CallContext(attempt_id=demo_id, job=job, candidate=candidate, keyterms=["CTC", "LPA"])
    sender = AudioSender(
        ws,
        "demo",
        encoding="slin",
        sample_rate=settings.telephony_sample_rate,
        frame_bytes=settings.telephony_frame_bytes,
        send_ahead_ms=settings.telephony_send_ahead_ms,
        session_id=demo_id,
    )
    inbound = InboundQueue(
        int(ac.bytes_per_second("slin", settings.telephony_sample_rate) * INBOUND_QUEUE_SECONDS)
    )
    marks = MarkTracker()
    manager = ConversationManager(job, candidate, llm, timeout_s=settings.groq_call_timeout_s)
    session = CallSession(
        ctx,
        settings=call_settings,
        sender=sender,
        inbound=inbound,
        marks=marks,
        stt=create_stt_provider(settings, keyterms=ctx.keyterms),
        tts=tts,
        manager=manager,
        vad=make_vad(settings),
    )
    capture = StreamCapture(keep_audio=False)
    tasks: list[asyncio.Task[Any]] = []
    reason = "error"
    try:
        await ws.send_text(json.dumps({"event": "ready", "max_seconds": settings.demo_max_call_s}))
        log.info("demo_call_started")
        main = asyncio.create_task(session.run(), name=demo_id)
        receiver = asyncio.create_task(
            _receive_loop(ws, capture, inbound, marks, session.caller_hung_up, "slin")
        )
        pusher = asyncio.create_task(_push_updates(ws, manager))
        tasks = [main, receiver, pusher]
        done, _ = await asyncio.wait({main, receiver}, return_when=asyncio.FIRST_COMPLETED)
        if main not in done:
            stopped = receiver.result() if not receiver.cancelled() else "disconnect"
            session.caller_hung_up(stopped)
            await asyncio.wait({main}, timeout=10)
        if main.done() and not main.cancelled() and main.exception() is None:
            reason = main.result().end_reason.value
        with contextlib.suppress(Exception):
            await ws.send_text(json.dumps({"event": "transcript", "lines": _lines(manager)}))
            await ws.send_text(
                json.dumps({"event": "ended", "reason": reason, "fields": _fields(manager)})
            )
            await ws.close(code=1000)
    except Exception:
        log.exception("demo_call_failed")
        await _refuse(ws, "error", "Something went wrong with the demo call.")
    finally:
        if reason in ("error", "technical_failure"):  # our side failed: they keep their demo
            await give_back(client_ip)
        for task in tasks:
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        with contextlib.suppress(Exception):
            await llm.aclose()
        tts.forget_call(demo_id)
        await release()
        log.info("demo_call_ended", reason=reason, turns=len(manager.transcript))
