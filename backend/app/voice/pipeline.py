"""One screening conversation over one phone call (phase-06 §5.1): `CallSession`.

    WS in ─► InboundQueue ─► reader ─┬─► SpeechDetector (VAD) ─► end of speech: STT finalize()
                                     │                          └► barge-in (interruption.py)
                                     └─► STT stream ─► UtteranceAssembler ─► UTTERANCE events
    events ─► driver ─► TurnManager table ─► actions: agent task, ack, Player, timers
    Player ─► TTS stream ─► 24→8 kHz ─► AudioSender (paced) ─► WS out ─► mark ─► events

Everything that happens becomes a `TurnEvent` on the session's own queue and only the driver
acts on them, so the turn rules in `turn_manager.TABLE` are the one place decisions are made.
Tasks run in one `asyncio.TaskGroup`; when the call ends (agent hang-up, caller hang-up or a
failure) the group is cancelled and `run()` cleans up: STT closed, transcript flushed, result
handed to `on_end`. Every queue, buffer, timer and provider stream belongs to this session.
"""

import asyncio
import contextlib
import random
import time
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

from app.agent import prompts
from app.agent.conversation_manager import (
    LOW_CONFIDENCE,
    AgentReply,
    Checkpoint,
    ConversationManager,
    ScreeningResult,
    TranscriptEntry,
)
from app.agent.prompts import CandidateContext, JobConfig
from app.agent.state import AskKind, EndReason, Phase
from app.config import Settings
from app.database.models import CallEndReason
from app.providers.stt.base import STTError, STTProvider
from app.providers.tts import ACKNOWLEDGEMENTS, HOLD_PHRASE, fixed_phrases
from app.providers.tts.base import TTSError, TTSProvider
from app.services.transcript_service import TranscriptWriter
from app.utils.log import get_logger
from app.voice.audio_processor import InboundFramer, InboundQueue
from app.voice.interruption import BargeInPolicy, heard_portion, is_backchannel, words
from app.voice.playback import (
    PLAYOUT_LAG_MS,
    AudioSender,
    MarkTracker,
    Player,
    SpeechResult,
    split_for_prefetch,
)
from app.voice.turn_manager import Act, TurnEvent, TurnManager, TurnState
from app.voice.utterance import Utterance, UtteranceAssembler
from app.voice.vad import SpeechDetector, VadEvent

logger = get_logger(__name__)

SHORT_ANSWER_PHASES = {Phase.IDENTITY_CHECK, Phase.PERMISSION, Phase.CONFIRMATION}
NO_ACK_PHASES = {Phase.GREETING, Phase.IDENTITY_CHECK}  # the next line is a template anyway
# Said before the greeting starts: an answer to nothing, dropped
HELLO_WORDS = frozenset({"hello", "hi", "hey", "haan", "han", "ha", "ji", "yes", "yeah", "ok"})
GREETING_NOISE = frozenset({"hello", "hi", "hey"})  # said over the greeting: dropped too
GREETING_EXTRA_WAIT_S = 2.0  # the candidate is still saying hello at the deadline
MS_PER_WORD = 400.0  # speaking rate for the heard-portion estimate while TTS still streams
HEARD_ALL = 0.85  # heard this share of a reply → the candidate answered at its end, no barge-in
TIME_UP_MARGIN_S = 20.0  # closing line this long before MAX_CALL_DURATION_S
HANGUP_GRACE_S = 4.0  # caller hung up mid-turn: let the agent finish extracting their answer
# Never start a reply while the candidate is talking: wait for this much quiet (at most
# FLOOR_MAX_WAIT_S). LLM replies take 2+ s anyway; this holds back instant template replies, so a
# continuation ("Total work… four years") merges instead of being talked over (real call P6).
FLOOR_GAP_S = 0.7
FLOOR_MAX_WAIT_S = 2.5
# Said at the start of many replies; with the job's questions, synthesized during the greeting
WARM_PHRASES = ("Thanks.", "Great, thank you.", "Got it.")

END_REASONS = {
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


class _Ended(Exception):
    """Raised by the driver to stop the session's task group."""


@dataclass
class CallContext:
    attempt_id: str
    job: JobConfig
    candidate: CandidateContext
    candidate_id: uuid.UUID | None = None
    provider_call_id: str | None = None
    keyterms: list[str] = field(default_factory=list)


@dataclass
class TurnMetrics:
    """Per-turn latency (phase-06 §5.8). Times are monotonic seconds."""

    turn: int
    utterance: str
    t0: float | None = None  # candidate stopped speaking (last word's audio reached STT)
    t1: float | None = None  # utterance complete
    t2: float | None = None  # agent reply ready
    t3: float | None = None  # first TTS audio of the reply
    t4: float | None = None  # first reply frame sent
    t_ack: float | None = None  # first acknowledgement frame sent
    ack: str | None = None
    merged: int = 0  # utterances merged into this turn
    interrupted: bool = False
    hold: bool = False  # "One moment." was played

    def segments(self) -> dict[str, int | None]:
        def ms(a: float | None, b: float | None) -> int | None:
            return None if a is None or b is None else round((b - a) * 1000)

        first_sound = min((t for t in (self.t_ack, self.t4) if t is not None), default=None)
        return {
            "stt_ms": ms(self.t0, self.t1),
            "llm_ms": ms(self.t1, self.t2),
            "tts_ms": ms(self.t2, self.t3),
            "send_ms": ms(self.t3, self.t4),
            "total_ms": ms(self.t0, self.t4),
            "ack_ms": ms(self.t0, self.t_ack),
            "first_sound_ms": ms(self.t0, first_sound),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "utterance_words": len(self.utterance.split()),
            "ack": self.ack,
            "merged": self.merged,
            "interrupted": self.interrupted,
            "hold": self.hold,
            **self.segments(),
        }


@dataclass
class SessionOutcome:
    result: ScreeningResult
    end_reason: CallEndReason
    ended_by: str  # agent | caller | error
    failure_reason: str | None
    metrics: list[dict[str, Any]]
    stats: dict[str, Any]


class CallSession:
    def __init__(
        self,
        ctx: CallContext,
        *,
        settings: Settings,
        sender: AudioSender,
        inbound: InboundQueue,
        marks: MarkTracker,
        stt: STTProvider,
        tts: TTSProvider,
        manager: ConversationManager,
        vad: SpeechDetector,
        writer: TranscriptWriter | None = None,
        on_end: Callable[[SessionOutcome], Awaitable[None]] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.ctx = ctx
        self.id = ctx.attempt_id
        self.settings = settings
        self.sender = sender
        self.inbound = inbound
        self.marks = marks
        self.stt = stt
        self.tts = tts
        self.manager = manager
        self.vad = vad
        self.writer = writer
        self.on_end = on_end
        self.rng = rng or random.Random()  # noqa: S311  (which "Okay." to say)
        self.log = logger.bind(
            call_attempt_id=ctx.attempt_id,
            candidate_id=str(ctx.candidate_id) if ctx.candidate_id else None,
            provider_call_id=ctx.provider_call_id,
        )

        self.turns = TurnManager()
        self.assembler = UtteranceAssembler(self.id)
        self.policy = BargeInPolicy(
            min_ms=settings.barge_in_min_ms, backchannel_max_ms=settings.backchannel_max_ms
        )
        self.player = Player(
            sender, tts, marks, session_id=self.id, no_split=frozenset(fixed_phrases())
        )
        self.player.on_first_frame = lambda result: self._post(TurnEvent.FIRST_AUDIO, result)
        self.framer = InboundFramer(settings.telephony_sample_rate)
        self._events: asyncio.Queue[tuple[TurnEvent, Any]] = asyncio.Queue()
        self._tg: asyncio.TaskGroup | None = None
        self._stt_open = False

        # the current turn
        self._agent_task: asyncio.Task[None] | None = None
        self._speak_task: asyncio.Task[None] | None = None
        self._ack_task: asyncio.Task[None] | None = None
        self._hold_task: asyncio.Task[None] | None = None
        self._silence_task: asyncio.Task[None] | None = None
        self._checkpoint: Checkpoint | None = None
        self._pending_text = ""
        self._pending_conf: float | None = None
        self._reply_label: str | None = None  # the playback whose events count
        self._reply_entry: TranscriptEntry | None = None
        self._ack_played: str | None = None
        self._last_ack: str | None = None
        self._held: list[Utterance] = []
        self._late_answers: set[int] = set()
        self._metrics: TurnMetrics | None = None
        self._barged_this_run = False
        self._long_run_finalized = False
        self._greeting_started = False
        self._greeted = False
        self._silences = 0

        # outcome
        self.metrics: list[TurnMetrics] = []
        self.ended_by = "error"
        self.failure_reason: str | None = None
        self.caller_gone = False
        self.barge_ins: list[dict[str, Any]] = []
        self.backchannels_ignored = 0
        self.merges = 0
        self.max_loop_lag_ms = 0.0
        self.started_at = time.monotonic()

    # --- public ---------------------------------------------------------------------------------

    def caller_hung_up(self, reason: str = "stop") -> None:
        """The stream ended from Exotel's side: `stop` message, or the socket dropped."""
        if not self.caller_gone:
            self.caller_gone = True
            self.inbound.close()
            self._post(TurnEvent.CALLER_HANGUP, reason)

    async def run(self) -> SessionOutcome:
        structlog.contextvars.bind_contextvars(session_id=self.id)
        self.log.info("session_started", vad=self.vad.name)
        try:
            try:
                async with asyncio.TaskGroup() as tg:
                    self._tg = tg
                    tg.create_task(self._guard(self._open_stt(), "stt_open"))
                    tg.create_task(self._guard(self._read_inbound(), "reader"))
                    tg.create_task(self._guard(self._listen_stt(), "stt_listen"))
                    tg.create_task(self._guard(self._watch_time(), "timer"))
                    tg.create_task(self._guard(self._watch_loop_lag(), "lag"))
                    tg.create_task(self._drive())
                    self._post(TurnEvent.STREAM_STARTED)
            except* _Ended:
                pass
        finally:
            self._tg = None
            with contextlib.suppress(Exception):
                await self.stt.close()
        try:
            return await self._finish()
        finally:
            structlog.contextvars.unbind_contextvars("session_id")

    # --- plumbing -------------------------------------------------------------------------------

    def _post(self, event: TurnEvent, payload: Any = None) -> None:
        self._events.put_nowait((event, payload))

    def _spawn(self, coro: Coroutine[Any, Any, None], name: str) -> asyncio.Task[None]:
        assert self._tg is not None, "session not running"
        task = self._tg.create_task(self._guard(coro, name), name=f"{name}:{self.id[:8]}")
        # Cancelled before it ever ran (a timer stopped at once): close the inner coroutine
        task.add_done_callback(lambda t: coro.close() if t.cancelled() else None)
        return task

    async def _guard(self, coro: Coroutine[Any, Any, None], name: str) -> None:
        """A failing task never takes the session down silently: it becomes FAILURE."""
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except TTSError as exc:
            self.log.warning("session_tts_failed", task=name, error=str(exc))
            self._post(TurnEvent.FAILURE, "tts_failed")
        except STTError as exc:
            self.log.warning("session_stt_failed", task=name, error=str(exc))
            self._post(TurnEvent.FAILURE, "stt_unavailable")
        except Exception:
            self.log.exception("session_task_failed", task=name)
            self._post(TurnEvent.FAILURE, f"{name}_error")

    @staticmethod
    def _running(task: asyncio.Task[None] | None) -> bool:
        return task is not None and not task.done()

    # --- inputs ---------------------------------------------------------------------------------

    async def _open_stt(self) -> None:
        self._stt_open = True  # the provider buffers audio while it connects
        await self.stt.start_stream(
            session_id=self.id,
            encoding="linear16",
            sample_rate=self.settings.telephony_sample_rate,
            keyterms=self.ctx.keyterms,
        )

    async def _read_inbound(self) -> None:
        while True:
            try:
                chunk = await self.inbound.get()
            except EOFError:
                return
            if self._stt_open:
                await self.stt.send_audio(chunk)
            now = time.monotonic()
            # Our own voice may echo back while it plays (and a little after)
            self.vad.echo = now < self.sender.playhead + PLAYOUT_LAG_MS / 1000 + 0.2
            for frame in self.framer.push(chunk):
                event = self.vad.process(frame, now)
                if event is not None:
                    await self._on_vad(event)
            self._check_barge_in(now)
            self._check_long_utterance(now)

    async def _on_vad(self, event: VadEvent) -> None:
        if event.kind == "speech_start":
            self._barged_this_run = False
            self._long_run_finalized = False
            self._post(TurnEvent.SPEECH_STARTED, event)
        elif self._stt_open:
            # End of speech: ask for the transcript now rather than wait for STT's endpointing
            await self._finalize_stt()

    async def _finalize_stt(self) -> None:
        finalize = getattr(self.stt, "finalize", None)
        if finalize is not None:
            await finalize()

    def _check_barge_in(self, now: float) -> None:
        if self.turns.state is not TurnState.SPEAKING or self._barged_this_run:
            return
        if not self.vad.in_speech or not self._greeted:
            return  # the greeting always plays to the end
        current = self.player.current
        if current is None or current.label != self._reply_label or not current.first_frame_at:
            return
        audible_at = current.first_frame_at + PLAYOUT_LAG_MS / 1000
        if (self.vad.speech_started_at or 0.0) < audible_at:
            # They started talking before they could hear the reply ("Hello?" into the pause):
            # not an interruption. If it turns into real words, the utterance interrupts.
            return
        decision = self.policy.check(self.vad.run_ms(now), self.assembler.preview)
        if decision.interrupt:
            self._barged_this_run = True
            self._post(
                TurnEvent.BARGE_IN,
                {"reason": decision.reason, "speech_started_at": self.vad.speech_started_at},
            )

    def _check_long_utterance(self, now: float) -> None:
        limit_ms = self.settings.max_utterance_s * 1000
        if self.vad.in_speech and not self._long_run_finalized and self.vad.run_ms(now) >= limit_ms:
            self._long_run_finalized = True
            self.log.info("utterance_max_length", seconds=self.settings.max_utterance_s)
            self._spawn(self._finalize_stt(), "finalize")

    async def _listen_stt(self) -> None:
        async for event in self.stt.events():
            if event.kind == "error":
                self.log.warning("session_stt_error", detail=event.detail)
                self._post(TurnEvent.FAILURE, "stt_unavailable")
            utterance = self.assembler.feed(event)
            if utterance is not None:
                self._post(TurnEvent.UTTERANCE, utterance)
            if event.kind == "closed":
                return

    async def _watch_time(self) -> None:
        def elapsed() -> float:
            return time.monotonic() - self.started_at

        wrap_at = self.settings.call_wrap_up_s
        stop_at = max(wrap_at, self.settings.max_call_duration_s - TIME_UP_MARGIN_S)
        await asyncio.sleep(max(0.0, wrap_at - elapsed()))
        self.log.info("session_wrap_up", seconds=round(elapsed()))
        self.manager.request_wrap_up()
        await asyncio.sleep(max(0.0, stop_at - elapsed()))
        self.log.warning("session_time_up", seconds=round(elapsed()))
        self._post(TurnEvent.TIME_UP)

    async def _watch_loop_lag(self) -> None:
        while True:
            start = time.monotonic()
            await asyncio.sleep(0.5)
            lag = (time.monotonic() - start - 0.5) * 1000
            self.max_loop_lag_ms = max(self.max_loop_lag_ms, lag)
            if lag > 100:
                self.log.warning("event_loop_lag", lag_ms=round(lag))

    # --- driver ---------------------------------------------------------------------------------

    async def _drive(self) -> None:
        while True:
            event, payload = await self._events.get()
            try:
                await self._dispatch(event, payload)
            except Exception:
                self.log.exception("session_driver_failed", turn_event=event.value)
                self.failure_reason = self.failure_reason or "driver_error"
                raise _Ended from None
            if self.turns.state is TurnState.ENDED:
                raise _Ended

    async def _dispatch(self, event: TurnEvent, payload: Any) -> None:
        refined = self._classify(event, payload)
        if refined is None:
            return
        before = self.turns.state
        acts = self.turns.handle(refined)
        if acts != (Act.IGNORE,):
            self.log.debug(
                "turn_event",
                turn_event=refined.value,
                before=before.value,
                after=self.turns.state.value,
            )
        for act in acts:
            await getattr(self, f"_act_{act.value}")(refined, payload)

    def _classify(self, event: TurnEvent, payload: Any) -> TurnEvent | None:
        """Refine a raw event with what the table can't see. None = drop it."""
        if event in (TurnEvent.FIRST_AUDIO, TurnEvent.PLAYBACK_DONE):
            label = payload.label if isinstance(payload, SpeechResult) else payload
            if label is None or label != self._reply_label:
                return None  # an acknowledgement, or a playback that was cancelled
            if event is TurnEvent.FIRST_AUDIO:
                if self._metrics is not None and isinstance(payload, SpeechResult):
                    self._metrics.t3 = payload.first_chunk_at
                    self._metrics.t4 = payload.first_frame_at
                if self.turns.state is not TurnState.THINKING:
                    return None
        if event is TurnEvent.UTTERANCE and not self._greeted:
            utterance: Utterance = payload
            said = set(words(utterance.text))
            if said <= (GREETING_NOISE if self._greeting_started else HELLO_WORDS):
                self.log.info("utterance_before_greeting_dropped", text=utterance.text)
            else:
                self._held.append(utterance)  # answered over the greeting: used once it ends
            return None
        if (
            event is TurnEvent.UTTERANCE
            and self.turns.state is TurnState.SPEAKING
            and is_backchannel(payload.text)
        ):
            return TurnEvent.BACKCHANNEL
        return event

    # --- actions: greeting and agent turns ------------------------------------------------------

    async def _act_ignore(self, event: TurnEvent, payload: Any) -> None:
        if event is TurnEvent.UTTERANCE and self.turns.state is TurnState.ENDING:
            self.log.info("utterance_while_ending", text=payload.text)

    async def _act_wait_hello_then_greet(self, event: TurnEvent, payload: Any) -> None:
        reply = await self.manager.start()
        self._reply_entry = self.manager.transcript[-1]
        self._expect_answer(reply)
        self._spawn(self._greet(reply.text), "greeting")

    async def _greet(self, text: str) -> None:
        # Synthesize while we wait (up to GREETING_WAIT_MS) for the candidate's "Hello?"
        audio = asyncio.ensure_future(self.tts.synthesize(text, call_attempt_id=self.id))
        try:
            deadline = time.monotonic() + self.settings.greeting_wait_ms / 1000
            # Polled: the VAD runs frame by frame in the reader and has no events to wait on
            while time.monotonic() < deadline and not self._hello_heard():  # noqa: ASYNC110
                await asyncio.sleep(0.02)
            extra = time.monotonic() + GREETING_EXTRA_WAIT_S
            while self.vad.in_speech and time.monotonic() < extra:  # noqa: ASYNC110
                await asyncio.sleep(0.02)
            clip = await audio
        finally:
            audio.cancel()
        label = self.player.new_label("greeting")
        self._reply_label = label
        self._greeting_started = True
        if self.settings.voice_tts_warm:
            self._spawn(self._warm_voice(), "tts_warm")
        result = await self.player.play_clip(clip, kind="greeting", label=label, wait=False)
        await self.player.wait_played(result)
        self._post(TurnEvent.PLAYBACK_DONE, result)

    async def _warm_voice(self) -> None:
        """The agent usually asks the job's questions word for word: synthesize them now, so
        the reply's audio comes from the cache instead of a ~1 s request (measured P6)."""
        job, candidate = self.ctx.job, self.ctx.candidate
        questions = self.manager.state.questions
        texts = [
            prompts.introduction(candidate, job),  # the next line after "yes, speaking"
            *([prompts.ask(questions[0], prefix=prompts.role_line(job))] if questions else []),
            *WARM_PHRASES,
            *(q.prompt for q in questions),
        ]
        # The player asks for a reply's first sentence and the rest separately
        phrases = [part for text in texts for part in split_for_prefetch(text)]
        started = time.monotonic()
        for phrase in dict.fromkeys(phrases):
            try:
                await self.tts.synthesize(phrase, call_attempt_id=self.id)
            except TTSError:
                self.log.info("tts_warm_failed")
                return
        self.log.info(
            "tts_warmed", phrases=len(phrases), ms=round((time.monotonic() - started) * 1000)
        )

    def _hello_heard(self) -> bool:
        return self.vad.stats.speech_runs > 0 and not self.vad.in_speech

    async def _act_run_agent(self, event: TurnEvent, payload: Any) -> None:
        utterance: Utterance = payload
        self._silences = 0
        self._pending_text, self._pending_conf = utterance.text, utterance.confidence
        self._metrics = TurnMetrics(
            turn=len(self.metrics) + 1,
            utterance=utterance.text,
            t0=self._speech_end(utterance),
            t1=utterance.completed_at,
        )
        self._ack_played = None
        self._start_agent(self._handle_text(utterance.text, utterance.confidence))

    def _speech_end(self, utterance: Utterance) -> float | None:
        if utterance.ended_at is not None:
            sent = self.stt.sent_at(utterance.ended_at)
            if sent is not None:
                return sent
        return self.vad.last_voice_at

    def _handle_text(self, text: str, conf: float | None) -> Callable[[], Awaitable[AgentReply]]:
        return lambda: self.manager.handle_utterance(text, stt_confidence=conf)

    def _start_agent(self, handler: Callable[[], Awaitable[AgentReply]]) -> None:
        self._checkpoint = self.manager.checkpoint()
        self._reply_label = None
        metrics = self._metrics

        async def run() -> None:
            reply = await handler()
            if metrics is not None:
                metrics.t2 = time.monotonic()
            last = self.manager.transcript[-1] if self.manager.transcript else None
            self._reply_entry = last if last is not None and last.speaker == "assistant" else None
            self._post(TurnEvent.END_REPLY if reply.end_call else TurnEvent.AGENT_REPLY, reply)

        self._agent_task = self._spawn(run(), "agent")
        if self._hold_task is not None:
            self._hold_task.cancel()
        hold_ms = self.settings.voice_hold_after_ms
        if metrics is not None and metrics.t1 is not None and hold_ms > 0:
            self._hold_task = self._spawn(self._hold(metrics, metrics.t1 + hold_ms / 1000), "hold")

    async def _hold(self, metrics: TurnMetrics, at: float) -> None:
        """The reply is slow (LLM p95 ~4 s): say "One moment." once so the line isn't dead."""
        await asyncio.sleep(max(0.0, at - time.monotonic()))
        if (
            self.turns.state is not TurnState.THINKING
            or metrics is not self._metrics
            or metrics.t4 is not None
            or self.vad.in_speech
        ):
            return
        if self._ack_task is not None:
            await asyncio.wait({self._ack_task})
        clip = await self.tts.synthesize(HOLD_PHRASE, call_attempt_id=self.id)
        if self.turns.state is TurnState.THINKING and metrics.t4 is None:
            self.log.info("hold_phrase_played")
            metrics.hold = True
            await self.player.play_clip(clip, kind="hold", wait=False)

    async def _act_play_ack(self, event: TurnEvent, payload: Any) -> None:
        utterance: Utterance = payload
        if not self.settings.voice_acknowledgements or self._running(self._ack_task):
            return
        if self.manager.state.phase in NO_ACK_PHASES or self.manager.state.ended:
            return
        if utterance.confidence is not None and utterance.confidence < LOW_CONFIDENCE:
            return  # the reply will be "sorry, could you say that again?"
        choices = [a for a in ACKNOWLEDGEMENTS if a != self._last_ack] or list(ACKNOWLEDGEMENTS)
        ack = self.rng.choice(choices)
        self._last_ack = self._ack_played = ack
        metrics = self._metrics

        async def play() -> None:
            clip = await self.tts.synthesize(ack, call_attempt_id=self.id)
            result = await self.player.play_clip(clip, kind="ack", wait=False)
            if metrics is not None:
                metrics.ack, metrics.t_ack = ack, result.first_frame_at

        self._ack_task = self._spawn(play(), "ack")

    async def _act_cancel_agent(self, event: TurnEvent, payload: Any) -> None:
        """Stop the turn in flight. A cancelled `handle_utterance` undoes itself; a reply that
        was already playing is stopped and recorded as interrupted."""
        if self._running(self._agent_task):
            assert self._agent_task is not None
            self._agent_task.cancel()
        if self._running(self._speak_task):
            await self._stop_reply(payload, reason="cancelled")

    async def _act_merge_and_rerun(self, event: TurnEvent, payload: Any) -> None:
        """The candidate kept talking before the reply started: one turn from both utterances."""
        utterance: Utterance = payload
        if self._agent_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._agent_task  # let the cancellation (and its rollback) finish
        if self._checkpoint is not None:
            self.manager.restore(self._checkpoint)  # also undoes a reply that was ready
        merged = f"{self._pending_text} {utterance.text}".strip()
        confs = [c for c in (self._pending_conf, utterance.confidence) if c is not None]
        conf = min(confs) if confs else None
        self.merges += 1
        self.log.info("utterances_merged", words_first=len(self._pending_text.split()))
        self._pending_text, self._pending_conf = merged, conf
        self._silences = 0
        if self._metrics is None:
            self._metrics = TurnMetrics(turn=len(self.metrics) + 1, utterance=merged)
        m = self._metrics
        m.merged += 1
        m.utterance = merged
        m.t0, m.t1 = self._speech_end(utterance), utterance.completed_at
        m.t2 = m.t3 = m.t4 = None
        if m.t_ack is not None and m.t0 is not None and m.t_ack < m.t0:
            m.t_ack = None  # that acknowledgement belonged to the first part
        self._start_agent(self._handle_text(merged, conf))
        if self._ack_played is None:
            await self._act_play_ack(event, utterance)

    async def _act_speak_reply(self, event: TurnEvent, payload: Any) -> None:
        reply: AgentReply = payload
        text = strip_leading_ack(reply.text) if self._ack_played else reply.text
        self._expect_answer(reply)
        if self._reply_entry is not None and self._ack_played:
            self._reply_entry.ack = self._ack_played
        ack_task, hold_task = self._ack_task, self._hold_task
        holding = self.player.current is not None and self.player.current.label.startswith("hold")
        if hold_task is not None and not holding:
            hold_task.cancel()  # the reply is ready: no "One moment." now
            hold_task = None
        label = self.player.new_label("reply")
        self._reply_label = label

        async def speak() -> None:
            if ack_task is not None:
                await asyncio.wait({ack_task})  # never talk over our own "Okay."
            if hold_task is not None:
                await asyncio.wait({hold_task})  # or over "One moment."
            await self._wait_for_floor()
            if not text:
                self._post(TurnEvent.PLAYBACK_DONE, label)
                return
            result = await self.player.speak(text, label=label, wait=True)
            self._post(TurnEvent.PLAYBACK_DONE, result)

        self._speak_task = self._spawn(speak(), "speak")

    async def _wait_for_floor(self) -> None:
        """Until the candidate has been quiet for FLOOR_GAP_S (or FLOOR_MAX_WAIT_S passed)."""
        deadline = time.monotonic() + FLOOR_MAX_WAIT_S
        while time.monotonic() < deadline:
            quiet_for = time.monotonic() - (self.vad.last_voice_at or 0.0)
            if not self.vad.in_speech and quiet_for >= FLOOR_GAP_S:
                return
            await asyncio.sleep(0.05)

    def _expect_answer(self, reply: AgentReply) -> None:
        # "Mm-hmm" answers a yes/no question; otherwise it's filler
        self.assembler.expect_short_answer = (
            reply.phase in SHORT_ANSWER_PHASES or reply.ask_kind is AskKind.CONFIRM
        )

    # --- actions: playback ending ---------------------------------------------------------------

    async def _act_stop_playback(self, event: TurnEvent, payload: Any) -> None:
        reason = payload.get("reason") if isinstance(payload, dict) else "utterance"
        await self._stop_reply(payload, reason=str(reason))

    async def _stop_reply(self, payload: Any, *, reason: str) -> None:
        task, entry, metrics = self._speak_task, self._reply_entry, self._metrics
        tts_done = task is None or task.done() or self._tts_finished()
        if task is not None:
            task.cancel()
        result = await self.player.interrupt()
        self._reply_label = None
        if result is None or entry is None or result.label.startswith(("ack", "greeting")):
            return
        heard_ms = result.heard_ms or 0.0
        total_ms = result.sent_ms if tts_done else len(entry.text.split()) * MS_PER_WORD
        total_ms = max(total_ms, result.sent_ms, 1.0)
        started = payload.get("speech_started_at") if isinstance(payload, dict) else None
        info = {
            "reason": reason,
            "stop_latency_ms": round((time.monotonic() - started) * 1000) if started else None,
            "heard_share": round(heard_ms / total_ms, 2),
            "reply_words": len(entry.text.split()),
        }
        if tts_done and heard_ms / total_ms >= HEARD_ALL:
            # They answered as the question ended (the mark lags ~0.5 s): not an interruption
            self.log.info("answered_at_end_of_reply", **info)
        else:
            heard = heard_portion(entry.text, heard_ms, total_ms)
            self.barge_ins.append(info)
            self.log.info("barge_in", **info)
            await self.manager.handle_interruption(heard)
            if metrics is not None:
                metrics.interrupted = True
        await self._turn_done()

    def _tts_finished(self) -> bool:
        current = self.player.current
        return bool(current and current.extra.get("tts_done"))

    async def _act_redispatch(self, event: TurnEvent, payload: Any) -> None:
        await self._dispatch(event, payload)

    async def _act_hold_backchannel(self, event: TurnEvent, payload: Any) -> None:
        if self._heard_share() >= HEARD_ALL:
            self._late_answers.add(id(payload))  # said as the question ended: an answer
        self._held.append(payload)

    def _heard_share(self) -> float:
        current, entry = self.player.current, self._reply_entry
        if current is None or entry is None or current.label != self._reply_label:
            return 0.0
        total = current.sent_ms if self._tts_finished() else len(entry.text.split()) * MS_PER_WORD
        return self.player.heard_ms(current) / max(total, current.sent_ms, 1.0)

    async def _act_release_backchannel(self, event: TurnEvent, payload: Any) -> None:
        """The reply has played. A "yes" said over its end answers a yes/no question."""
        await self._turn_done()
        held, self._held = self._held, []
        # A bare "Hello?" is the candidate checking the line, never an answer
        held = [u for u in held if not set(words(u.text)) <= GREETING_NOISE]
        if not held:
            return
        late, self._late_answers = self._late_answers, set()
        text = " ".join(u.text for u in held)
        answers = self.assembler.expect_short_answer or any(id(u) in late for u in held)
        if not answers and all(is_backchannel(u.text) for u in held):
            self.backchannels_ignored += len(held)
            self.log.info("backchannel_ignored", words=len(text.split()))
            return
        confs = [u.confidence for u in held if u.confidence is not None]
        last = held[-1]
        self._post(
            TurnEvent.UTTERANCE,
            Utterance(
                session_id=self.id,
                text=text,
                confidence=min(confs) if confs else None,
                started_at=held[0].started_at,
                ended_at=last.ended_at,
                completed_at=last.completed_at,
                trigger=last.trigger,
                segments=sum(u.segments for u in held),
            ),
        )

    async def _turn_done(self) -> None:
        """The agent's turn is over (played or interrupted): record latency, save."""
        metrics, self._metrics = self._metrics, None
        if metrics is not None:
            if self._reply_entry is not None:
                self._reply_entry.latency_ms = metrics.segments()["first_sound_ms"]
            self.metrics.append(metrics)
            self.log.info("voice_turn_latency", **metrics.as_dict())
        await self._save_transcript()

    # --- actions: timers and endings ------------------------------------------------------------

    async def _act_start_silence_timer(self, event: TurnEvent, payload: Any) -> None:
        self._greeted = True
        if self._silence_task is not None:
            self._silence_task.cancel()
        self._silence_task = self._spawn(self._silence_timer(), "silence")

    async def _silence_timer(self) -> None:
        timeout = self.settings.silence_timeout_s
        started = time.monotonic()
        while True:
            wait = max(started, self.vad.last_voice_at or 0.0) + timeout - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            elif self.vad.in_speech or self.assembler.in_speech:
                await asyncio.sleep(0.5)  # they're talking: wait for the utterance
            else:
                self._post(TurnEvent.SILENCE)
                return

    async def _act_stop_silence_timer(self, event: TurnEvent, payload: Any) -> None:
        if self._silence_task is not None:
            self._silence_task.cancel()
            self._silence_task = None

    async def _act_run_silence_prompt(self, event: TurnEvent, payload: Any) -> None:
        self._silences += 1
        count = self._silences
        self.log.info("silence_timeout", count=count)
        self._metrics = None
        self._pending_text, self._pending_conf = "", None
        self._ack_played = None
        self._start_agent(lambda: self.manager.handle_silence(count))

    async def _act_speak_time_up(self, event: TurnEvent, payload: Any) -> None:
        if self._agent_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._agent_task
        self._ack_task, self._ack_played, self._metrics = None, None, None
        reply = self.manager.time_up()
        self._reply_entry = self.manager.transcript[-1]
        await self._act_speak_reply(event, reply)

    async def _act_play_apology(self, event: TurnEvent, payload: Any) -> None:
        self.failure_reason = self.failure_reason or str(payload or "failure")
        self.log.warning("session_failure", reason=self.failure_reason)
        label = self.player.new_label("apology")
        self._reply_label = label
        try:
            clip = self.tts.apology_clip(call_attempt_id=self.id)
        except TTSError:
            self._post(TurnEvent.PLAYBACK_DONE, label)  # nothing to say it with
            return

        async def play() -> None:
            result = await self.player.play_clip(clip, kind="apology", label=label, wait=False)
            await self.player.wait_played(result)
            self._post(TurnEvent.PLAYBACK_DONE, result)

        self._spawn(play(), "apology")

    async def _act_hang_up(self, event: TurnEvent, payload: Any) -> None:
        self.ended_by = "agent"
        await self._turn_done()

    async def _act_finish(self, event: TurnEvent, payload: Any) -> None:
        self.ended_by = "caller" if payload == "stop" else "error"
        if payload != "stop":
            self.failure_reason = self.failure_reason or "stream_dropped"
        if self._running(self._agent_task):
            # Let the agent finish with the answer they gave just before hanging up
            assert self._agent_task is not None
            with contextlib.suppress(Exception):
                await asyncio.wait({self._agent_task}, timeout=HANGUP_GRACE_S)
        self.log.info("caller_hung_up", reason=payload, during=self.turns.history[-1][0].value)

    # --- end ------------------------------------------------------------------------------------

    async def _save_transcript(self) -> None:
        if self.writer is None:
            return
        await self.writer.save(
            [asdict(e) for e in self.manager.transcript],
            live={
                "state": self.manager.state.model_dump(mode="json"),
                "turn_metrics": [m.as_dict() for m in self.metrics],
            },
        )

    def _end_reason(self) -> EndReason:
        state = self.manager.state
        if state.ended and state.end_reason is not None:
            return state.end_reason
        return EndReason.ERROR if self.failure_reason else EndReason.HANGUP

    async def _finish(self) -> SessionOutcome:
        result = await self.manager.end(self._end_reason())
        call_reason = END_REASONS.get(result.end_reason, CallEndReason.TECHNICAL_FAILURE)
        await self._save_transcript()
        stats = {
            "turns": len(self.metrics),
            "merges": self.merges,
            "barge_ins": self.barge_ins,
            "backchannels_ignored": self.backchannels_ignored,
            "vad": asdict(self.vad.stats) | {"name": self.vad.name},
            "stt": asdict(self.stt.stats) if getattr(self.stt, "stats", None) else None,
            "frames_sent": self.sender.frames_sent,
            "clears": self.sender.clears,
            "mark_latency_s": self.marks.latencies(),
            "max_loop_lag_ms": round(self.max_loop_lag_ms, 1),
            "dropped_inbound_bytes": self.inbound.dropped_bytes,
            "duration_s": round(time.monotonic() - self.started_at, 1),
            "turn_history": list(self.turns.handled())[-80:],
        }
        outcome = SessionOutcome(
            result=result,
            end_reason=call_reason,
            ended_by=self.ended_by,
            failure_reason=self.failure_reason,
            metrics=[m.as_dict() for m in self.metrics],
            stats=stats,
        )
        self.log.info(
            "session_ended",
            end_reason=call_reason.value,
            screening_status=result.screening_status.value,
            ended_by=self.ended_by,
            failure_reason=self.failure_reason,
            **{
                k: v
                for k, v in stats.items()
                if k not in ("turn_history", "barge_ins", "mark_latency_s", "stt")
            },
        )
        if self.on_end is not None:
            try:
                await self.on_end(outcome)
            except Exception:
                self.log.exception("session_on_end_failed")
        return outcome


ACK_WORDS = frozenset(
    {"okay", "ok", "got", "it", "thank", "you", "thanks", "sure", "right", "alright", "noted"}
)


LEAD_WORDS = frozenset({"sure", "okay", "ok", "right", "alright"})  # "Sure, we'll call you…"


def strip_leading_ack(text: str) -> str:
    """When an acknowledgement was already played: 'Got it. What is your notice period?' →
    'What is your notice period?', and 'Sure, we'll call you back…' → 'We'll call you back…'.
    Only a first sentence made of acknowledgement words, or one such leading word before a
    comma, goes ('Thank you, Rahul.' stays)."""
    for sep in (". ", "! "):
        head, found, rest = text.partition(sep)
        if found and rest.strip() and words(head) and set(words(head)) <= ACK_WORDS:
            return _capitalized(rest)
    head, found, rest = text.partition(", ")
    if (
        found
        and rest.strip()
        and words(head)
        and len(words(head)) == 1
        and (words(head)[0] in LEAD_WORDS)
    ):
        return _capitalized(rest)
    return text


def _capitalized(text: str) -> str:
    text = text.strip()
    return text[0].upper() + text[1:]
