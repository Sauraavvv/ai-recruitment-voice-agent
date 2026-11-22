"""Turn loop for one telephonic round call (phase-11 step 6b).

Same interface as `ConversationManager`, so the voice pipeline (VAD, STT, TTS, barge-in,
silence, time limit) runs it unchanged. Knows nothing about audio or the database.

Python owns the flow:

    greeting / identity ─► "is now a good time? about ten minutes" ─► role intro
      ─► the approved questions, in order, at most one follow-up each ─► "any questions?"
      ─► closing

The model (Groq, low effort) only classifies each candidate turn (answer, partial,
asks_question, declined, dont_know, callback, opt_out, wrong_person, not_interested, off_topic)
and writes
the lines Python can't template: an answer from the JD, a nudge back on topic, one follow-up.
It never picks the next question and never fills in an answer: the record holds only the
candidate's own words. If the model is slow or down mid-question, the agent says a filler and
moves on to the next question (the words are kept, marked unchecked); it never hangs.

The side exits (callback, opt-out, not interested, wrong person) end the call with the same end
reasons as screening, so retries and callbacks keep working. A callback or retry resumes at the
first question not answered on an earlier call of the round.
"""

import asyncio
import copy
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC
from enum import StrEnum
from typing import Any

import structlog
from pydantic import BaseModel, Field

from app.agent import prompts
from app.agent import telephonic_prompts as tp
from app.agent.conversation_manager import (
    LOW_CONFIDENCE,
    MAX_LOW_CONFIDENCE_REPROMPTS,
    MAX_SILENCES,
    AgentReply,
    Clock,
    SystemClock,
    TranscriptEntry,
    clean_for_speech,
    resolve_callback,
)
from app.agent.schemas import NextAction
from app.agent.state import TERMINAL_PHASES, AskKind, CallbackInfo, EndReason, Phase
from app.agent.telephonic_prompts import RoundQuestion, Stage, TelephonicContext, TelephonicTurn
from app.providers.llm.base import LLMError, LLMProvider

log = structlog.get_logger(__name__)


def _lower_first(text: str) -> str:
    """ "Which product?" → "which product?" (after "follow-up:"), but "AI tools?" stays."""
    if len(text) > 1 and text[0].isupper() and text[1].islower():
        return text[0].lower() + text[1:]
    return text


MAX_TURNS = 60
MAX_IDENTITY_ATTEMPTS = 3
MAX_PERMISSION_ATTEMPTS = 3
MAX_OFF_TOPIC = 2  # per question: then move on
MAX_CLOSING_QUESTIONS = 3  # "any questions for me?" rounds
MAX_LLM_ERRORS = 3  # in a row: then close politely
MAX_REPLY_WORDS = 55
MAX_FOLLOW_UP_WORDS = 25
# Follow-ups are rare (real call: one on every question felt like extra questions): at most two
# per call, only after a short answer, and announced as a follow-up
MAX_FOLLOW_UPS = 2
FOLLOW_UP_BELOW_WORDS = 20  # an answer this long or longer never gets a follow-up
FOLLOW_UP_LEAD = "Just one quick follow-up:"
MAX_OUTPUT_TOKENS = 1500  # the model's reasoning counts as output
DEFAULT_TIMEOUT_S = 5.0
NO_DETAIL = "I don't have that detail, but the recruiter will share it."

_END_PHASE = {
    EndReason.COMPLETED: Phase.ENDED,
    EndReason.CALLBACK: Phase.CALLBACK,
    EndReason.DECLINED: Phase.DECLINED,
    EndReason.OPTED_OUT: Phase.OPTED_OUT,
    EndReason.WRONG_PERSON: Phase.WRONG_PERSON,
    EndReason.ESCALATED: Phase.ESCALATED,
}


class AnswerStatus(StrEnum):
    ANSWERED = "answered"
    PARTIAL = "partial"
    DECLINED = "declined"  # refused to answer, or gave no answer at all
    DONT_KNOW = "dont_know"  # said they don't know or can't answer
    NOT_ASKED = "not_asked"


class AnswerRecord(BaseModel):
    question_id: str
    question: str
    status: AnswerStatus = AnswerStatus.NOT_ASKED
    parts: list[str] = Field(default_factory=list)  # the candidate's words, turn by turn
    follow_up_asked: bool = False
    follow_up: str | None = None
    # False: the model was unavailable on (one of) these turns, so the status wasn't checked
    checked: bool = True
    from_earlier_call: bool = False
    off_topic: int = 0

    @property
    def answer(self) -> str:
        return " ".join(p for p in self.parts if p).strip()

    def as_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "status": self.status.value,
            "answer": self.answer,
            "follow_up_asked": self.follow_up_asked,
            "follow_up": self.follow_up,
            "checked": self.checked,
            "from_earlier_call": self.from_earlier_call,
        }


class TelephonicState(BaseModel):
    candidate_name: str
    call_id: str | None = None
    phase: Phase = Phase.GREETING
    turn_count: int = 0
    answers: list[AnswerRecord]
    current: int | None = None  # index of the question being asked
    callback: CallbackInfo = Field(default_factory=CallbackInfo)
    opted_out: bool = False
    declined_round: bool = False
    identity_confirmed: bool | None = None
    escalation_reason: str | None = None
    candidate_questions: list[str] = Field(default_factory=list)
    end_reason: EndReason | None = None
    identity_attempts: int = 0
    permission_attempts: int = 0
    low_confidence_streak: int = 0
    closing_questions: int = 0
    llm_errors: int = 0  # in a row

    @property
    def ended(self) -> bool:
        return self.phase in TERMINAL_PHASES

    def remaining(self) -> list[int]:
        return [i for i, a in enumerate(self.answers) if a.status is AnswerStatus.NOT_ASKED]


@dataclass
class TelephonicCheckpoint:
    state: TelephonicState
    transcript: list[TranscriptEntry]
    calls: int
    errors: int
    last_question_text: str | None
    wrap_up: bool


@dataclass
class TelephonicResult:
    end_reason: EndReason
    question_set_id: str
    version: int
    answers: list[dict[str, Any]]
    candidate_questions: list[str]
    callback: dict[str, Any]
    opted_out: bool
    declined_round: bool
    identity_confirmed: bool | None
    escalation_reason: str | None
    all_asked: bool  # every question was asked (on this call or an earlier one)
    transcript: list[dict[str, Any]]
    turns: int
    llm_calls: int
    llm_errors: int
    input_tokens: int
    output_tokens: int
    purpose: str = "telephonic"
    prompt_version: str = tp.PROMPT_VERSION

    @property
    def status(self) -> str:
        """completed (the round finished), or the side exit, or partial / not_started."""
        if self.end_reason is EndReason.COMPLETED:
            return "completed"
        if self.end_reason in (
            EndReason.CALLBACK,
            EndReason.DECLINED,
            EndReason.OPTED_OUT,
            EndReason.WRONG_PERSON,
        ):
            return self.end_reason.value
        asked = any(a["status"] != AnswerStatus.NOT_ASKED for a in self.answers)
        return "partial" if asked else "not_started"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def telephonic(self) -> dict[str, Any]:
        """What the call recorded, as stored in conversations.extracted_data["telephonic"]."""
        return {
            "question_set_id": self.question_set_id,
            "version": self.version,
            "answers": self.answers,
            "candidate_questions": self.candidate_questions,
        }


@dataclass
class _Call:
    latency_ms: int
    input_tokens: int
    output_tokens: int
    kind: str


@dataclass
class _Usage:
    calls: list[_Call] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class TelephonicManager:
    def __init__(
        self,
        ctx: TelephonicContext,
        candidate: prompts.CandidateContext,
        llm: LLMProvider,
        clock: Clock | None = None,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.ctx = ctx
        self.candidate = candidate
        self.llm = llm
        self.clock = clock or SystemClock()
        self.timeout_s = timeout_s
        self.state = TelephonicState(
            candidate_name=candidate.name,
            call_id=candidate.call_id or str(uuid.uuid4()),
            answers=[self._record(q) for q in ctx.questions],
        )
        self.transcript: list[TranscriptEntry] = []
        self.usage = _Usage()
        self._last_question_text: str | None = None
        self._wrap_up = False

    def _record(self, q: RoundQuestion) -> AnswerRecord:
        record = AnswerRecord(question_id=q.id, question=q.text)
        prior = self.ctx.prior_answers.get(q.id)
        if prior and prior.get("status") in ("answered", "partial", "declined"):
            record.status = AnswerStatus(prior["status"])
            record.parts = [str(prior.get("answer") or "")]
            record.follow_up_asked = bool(prior.get("follow_up_asked"))
            record.follow_up = prior.get("follow_up")
            record.checked = bool(prior.get("checked", True))
            record.from_earlier_call = True
        return record

    # --- public interface (the voice pipeline's) ------------------------------------------------

    async def start(self) -> AgentReply:
        if self.state.phase is not Phase.GREETING:
            raise RuntimeError("Conversation already started")
        self.state.phase = Phase.IDENTITY_CHECK
        self.state.identity_attempts = 1
        return self._ask(tp.greeting(self.candidate))

    def checkpoint(self) -> TelephonicCheckpoint:
        return TelephonicCheckpoint(
            state=self.state.model_copy(deep=True),
            transcript=copy.deepcopy(self.transcript),
            calls=len(self.usage.calls),
            errors=len(self.usage.errors),
            last_question_text=self._last_question_text,
            wrap_up=self._wrap_up,
        )

    def restore(self, cp: TelephonicCheckpoint) -> None:
        """Undo everything since `cp` (the pipeline merges two utterances into one turn)."""
        self.state = cp.state.model_copy(deep=True)
        self.transcript = copy.deepcopy(cp.transcript)
        del self.usage.calls[cp.calls :]
        del self.usage.errors[cp.errors :]
        self._last_question_text = cp.last_question_text
        self._wrap_up = cp.wrap_up

    async def handle_utterance(
        self, text: str, *, stt_confidence: float | None = None
    ) -> AgentReply:
        """One candidate turn. Cancel-safe: if cancelled, the conversation is as before."""
        cp = self.checkpoint()
        try:
            return await self._handle_utterance(text, stt_confidence=stt_confidence)
        except asyncio.CancelledError:
            self.restore(cp)
            raise

    async def handle_silence(self, count: int, *, max_silences: int = MAX_SILENCES) -> AgentReply:
        if self.state.ended:
            return self._nothing()
        if count >= max_silences:
            return self._finish(EndReason.NO_RESPONSE, prompts.silence_close())
        if count == 1 and max_silences > 2:
            q = self._current_question()
            short = q.text if q is not None else self._last_question_text
            return self._say(prompts.silence_reprompt(short), "reprompt")
        return self._say(prompts.silence_prompt(self._last_question_text), NextAction.ASK_QUESTION)

    async def handle_interruption(self, heard_portion: str) -> None:
        for entry in reversed(self.transcript):
            if entry.speaker == "assistant":
                entry.interrupted = True
                entry.heard_text = heard_portion.strip()
                return

    def request_wrap_up(self) -> None:
        """The call is running long: after the current answer, close instead of asking on."""
        if not self._wrap_up:
            self._wrap_up = True
            log.info("telephonic_wrap_up", turns=self.state.turn_count, call_id=self.state.call_id)

    def time_up(self) -> AgentReply:
        if self.state.ended:
            return self._nothing()
        return self._finish(EndReason.MAX_TURNS, tp.wrap_up_close(self.candidate))

    async def end(self, reason: EndReason) -> TelephonicResult:
        s = self.state
        if not s.ended:
            s.end_reason = reason
            s.phase = _END_PHASE.get(reason, Phase.ENDED)
        assert s.end_reason is not None
        calls = self.usage.calls
        return TelephonicResult(
            end_reason=s.end_reason,
            question_set_id=self.ctx.question_set_id,
            version=self.ctx.version,
            answers=[a.as_dict() for a in s.answers],
            candidate_questions=list(s.candidate_questions),
            callback=s.callback.model_dump(mode="json"),
            opted_out=s.opted_out,
            declined_round=s.declined_round,
            identity_confirmed=s.identity_confirmed,
            escalation_reason=s.escalation_reason,
            all_asked=not s.remaining(),
            transcript=[asdict(e) for e in self.transcript],
            turns=s.turn_count,
            llm_calls=len(calls),
            llm_errors=len(self.usage.errors),
            input_tokens=sum(c.input_tokens for c in calls),
            output_tokens=sum(c.output_tokens for c in calls),
        )

    def warm_texts(self, fillers: Sequence[str] = ()) -> list[str]:
        """Lines worth synthesizing during the greeting (they're said word for word)."""
        remaining = self.state.remaining()
        texts = [tp.introduction(self.candidate, self.ctx, remaining=len(remaining))]
        questions = [self.ctx.questions[i] for i in remaining]
        if questions:
            texts.append(tp.first_question(self.ctx, questions[0], total=len(questions)))
        texts.extend(fillers)
        for n, q in enumerate(questions[1:], start=2):
            texts.append(tp.next_question(q, last=n == len(questions)))
        texts.extend([tp.ANY_QUESTIONS, tp.closing(self.candidate)])
        return texts

    # --- one turn -------------------------------------------------------------------------------

    async def _handle_utterance(self, text: str, *, stt_confidence: float | None) -> AgentReply:
        s = self.state
        if s.ended:
            return self._nothing()
        if s.phase is Phase.GREETING:
            raise RuntimeError("Call start() before handle_utterance()")
        text = text.strip()
        s.turn_count += 1
        self._add("candidate", text)
        self.transcript[-1].stt_confidence = stt_confidence

        low = stt_confidence is not None and stt_confidence < LOW_CONFIDENCE
        if (not text or low) and s.low_confidence_streak < MAX_LOW_CONFIDENCE_REPROMPTS:
            s.low_confidence_streak += 1
            return self._say(prompts.low_confidence(), NextAction.CLARIFY)
        s.low_confidence_streak = 0
        if s.turn_count > MAX_TURNS:
            return self._finish(EndReason.MAX_TURNS, tp.wrap_up_close(self.candidate))

        stage = self._stage()
        try:
            turn = await self._classify(stage, text)
        except (LLMError, TimeoutError) as exc:
            return self._on_model_error(text, exc)
        s.llm_errors = 0
        reply = self._apply(turn, text)
        log.info(
            "telephonic_turn",
            turn=s.turn_count,
            stage=stage.phase,
            kind=turn.kind,
            phase=s.phase.value,
            question=stage.question_number,
            call_id=s.call_id,
        )
        return reply

    async def _classify(self, stage: Stage, text: str) -> TelephonicTurn:
        history = []
        for e in self.transcript[:-1]:
            said = f"{e.heard_text or ''}… (interrupted)" if e.interrupted else e.text
            history.append((e.speaker, said))
        messages = tp.build_messages(self.ctx, stage, history, text, self.clock.now())
        # The provider has its own timeout per key; this bounds the whole turn
        result = await asyncio.wait_for(
            self.llm.structured(
                messages, TelephonicTurn, timeout_s=self.timeout_s, max_tokens=MAX_OUTPUT_TOKENS
            ),
            timeout=self.timeout_s + 1,
        )
        self.usage.calls.append(
            _Call(result.latency_ms, result.input_tokens, result.output_tokens, result.value.kind)
        )
        return result.value

    def _stage(self) -> Stage:
        s = self.state
        total = len(s.answers)
        if s.callback.time_asked:
            return Stage(phase="callback_time", total_questions=total)
        if s.phase is Phase.IDENTITY_CHECK:
            return Stage(phase="identity", total_questions=total)
        if s.phase is Phase.PERMISSION:
            return Stage(phase="permission", total_questions=total)
        if s.phase is Phase.CLOSING:
            return Stage(phase="closing", total_questions=total)
        record, q = self._current()
        return Stage(
            phase="follow_up" if record.follow_up_asked else "question",
            question=q.text,
            rubric=q.rubric or None,
            follow_up=record.follow_up,
            question_number=(s.current or 0) + 1,
            total_questions=total,
            follow_up_allowed=self._follow_up_left(record),
        )

    def _follow_up_left(self, record: AnswerRecord) -> bool:
        asked = sum(a.follow_up_asked and not a.from_earlier_call for a in self.state.answers)
        return not record.follow_up_asked and asked < MAX_FOLLOW_UPS

    def _on_model_error(self, text: str, exc: Exception) -> AgentReply:
        """The model failed or was too slow. Never hang: keep the words and move on."""
        s = self.state
        s.llm_errors += 1
        self.usage.errors.append(type(exc).__name__)
        log.warning(
            "telephonic_model_error",
            error=type(exc).__name__,
            in_a_row=s.llm_errors,
            phase=s.phase.value,
            call_id=s.call_id,
        )
        if s.llm_errors >= MAX_LLM_ERRORS:
            s.escalation_reason = "llm_error"
            return self._finish(EndReason.ERROR, prompts.error_close())
        if s.phase is Phase.SCREENING and s.current is not None:
            record = s.answers[s.current]
            record.parts.append(text)
            record.checked = False
            if record.status is AnswerStatus.NOT_ASKED:
                record.status = AnswerStatus.ANSWERED  # their words, kept as said
            return self._advance(prefix=tp.NOT_SURE_FILLER)
        if s.phase is Phase.CLOSING:
            s.candidate_questions.append(text[:300])  # unanswered: the recruiter follows up
            return self._finish(EndReason.COMPLETED, tp.closing(self.candidate))
        return self._say(prompts.llm_error_retry(), NextAction.CLARIFY)

    def _apply(self, t: TelephonicTurn, text: str) -> AgentReply:
        s = self.state
        if t.kind == "opt_out":
            s.opted_out = True
            return self._finish(EndReason.OPTED_OUT, prompts.opt_out_close())
        if t.kind == "wrong_person" or (
            s.phase is Phase.IDENTITY_CHECK and t.identity_confirmed is False
        ):
            s.identity_confirmed = False
            return self._finish(EndReason.WRONG_PERSON, prompts.wrong_person_close())
        if t.kind == "not_interested":
            s.declined_round = True
            return self._finish(EndReason.DECLINED, tp.declined_close(self.candidate))

        if s.callback.time_asked:
            if t.kind != "callback" and t.permission_granted and not t.callback_time_iso:
                s.callback = CallbackInfo()  # "actually, go ahead now"
                return self._resume_after_callback()
            return self._callback(t)
        if t.kind == "callback" or (s.phase is Phase.PERMISSION and t.permission_granted is False):
            return self._callback(t)

        if s.phase is Phase.IDENTITY_CHECK:
            return self._identity_turn(t)
        if s.phase is Phase.PERMISSION:
            return self._permission_turn(t)
        if s.phase is Phase.CLOSING:
            return self._closing_turn(t, text)
        return self._question_turn(t, text)

    def _identity_turn(self, t: TelephonicTurn) -> AgentReply:
        s = self.state
        if t.identity_confirmed:
            s.identity_confirmed = True
            s.phase = Phase.PERMISSION
            s.permission_attempts = 1
            remaining = len(s.remaining())
            return self._ask(tp.introduction(self.candidate, self.ctx, remaining=remaining))
        s.identity_attempts += 1
        if s.identity_attempts > MAX_IDENTITY_ATTEMPTS:
            s.escalation_reason = "identity_not_confirmed"
            return self._finish(EndReason.ESCALATED, prompts.identity_unresolved_close())
        again = clean_for_speech(t.reply) or tp.greeting(self.candidate)
        if "?" not in again:
            again = f"{again} {tp.greeting(self.candidate)}"
        return self._ask(again, action=NextAction.CLARIFY)

    def _permission_turn(self, t: TelephonicTurn) -> AgentReply:
        s = self.state
        if t.permission_granted:
            s.phase = Phase.SCREENING
            return self._ask_first()
        if t.kind == "asks_question":
            self._note_question(t, "")
            answer = clean_for_speech(t.reply, max_words=MAX_REPLY_WORDS) or NO_DETAIL
            again = tp.permission_again(len(s.remaining()))
            return self._ask(f"{answer} {again}", action=NextAction.CLARIFY)
        s.permission_attempts += 1
        if s.permission_attempts > MAX_PERMISSION_ATTEMPTS:
            s.callback.requested = s.callback.needs_recruiter = True
            return self._finish(EndReason.CALLBACK, prompts.callback_vague_close())
        return self._ask(tp.permission_again(len(s.remaining())), action=NextAction.CLARIFY)

    def _question_turn(self, t: TelephonicTurn, text: str) -> AgentReply:
        record, q = self._current()
        if record.follow_up_asked and t.kind in ("asks_question", "off_topic"):
            # Pushback on the follow-up ("I already answered", "why another question?"): answer
            # if they asked something, then move on. The main question is never asked again.
            answer = ""
            if t.kind == "asks_question":
                self._note_question(t, text)
                answer = clean_for_speech(t.reply, max_words=MAX_REPLY_WORDS).rstrip("?")
            record.status = AnswerStatus.PARTIAL if record.parts else AnswerStatus.DECLINED
            return self._advance(prefix=f"{answer} No problem." if answer else "No problem.")
        if t.kind == "asks_question":
            self._note_question(t, text)
            answer = clean_for_speech(t.reply, max_words=MAX_REPLY_WORDS) or NO_DETAIL
            return self._ask(f"{answer} {tp.repeat_question(q)}", asked=q.id)
        if t.kind == "off_topic":
            record.off_topic += 1
            if record.off_topic <= MAX_OFF_TOPIC:
                nudge = clean_for_speech(t.reply, max_words=25).rstrip("?") or "Sorry."
                return self._ask(f"{nudge} {tp.repeat_question(q)}", asked=q.id)
            # Nothing usable after a few tries: what they did say stays as a partial answer
            record.status = AnswerStatus.PARTIAL if record.parts else AnswerStatus.DECLINED
            return self._advance(prefix="Okay, let's move on.")
        record.parts.append(text)
        if t.kind in ("declined", "dont_know"):
            refused = AnswerStatus.DECLINED if t.kind == "declined" else AnswerStatus.DONT_KNOW
            # Words already given (e.g. before a follow-up) still count as a partial answer
            record.status = AnswerStatus.PARTIAL if len(record.parts) > 1 else refused
            return self._advance(prefix="No problem.")
        if t.kind == "partial":
            follow_up = clean_for_speech(t.follow_up or "", max_words=MAX_FOLLOW_UP_WORDS)
            record.status = AnswerStatus.PARTIAL
            short = len(" ".join(record.parts).split()) < FOLLOW_UP_BELOW_WORDS
            if self._follow_up_left(record) and short and follow_up.endswith("?"):
                record.follow_up_asked, record.follow_up = True, follow_up
                return self._ask(
                    f"{FOLLOW_UP_LEAD} {_lower_first(follow_up)}", asked=q.id, kind=AskKind.CLARIFY
                )
            return self._advance()
        record.status = AnswerStatus.ANSWERED  # "answer" (and anything else said as one)
        return self._advance()

    def _closing_turn(self, t: TelephonicTurn, text: str) -> AgentReply:
        s = self.state
        if t.kind == "asks_question":
            self._note_question(t, text)
            answer = clean_for_speech(t.reply, max_words=MAX_REPLY_WORDS) or NO_DETAIL
            s.closing_questions += 1
            if s.closing_questions < MAX_CLOSING_QUESTIONS:
                return self._ask(f"{answer} {tp.ANYTHING_ELSE}")
            return self._finish(EndReason.COMPLETED, f"{answer} {tp.closing(self.candidate)}")
        return self._finish(EndReason.COMPLETED, tp.closing(self.candidate))

    def _callback(self, t: TelephonicTurn) -> AgentReply:
        s = self.state
        s.callback.requested = True
        if t.callback_time_text:
            s.callback.time_text = t.callback_time_text.strip()[:200]
        when = resolve_callback(t.callback_time_iso, self.clock.now())
        if when:
            s.callback.time_iso = when.isoformat()
            return self._finish(EndReason.CALLBACK, prompts.callback_confirm(when))
        if not s.callback.time_asked:
            s.callback.time_asked = True
            return self._ask(prompts.callback_ask(), action=NextAction.SCHEDULE_CALLBACK)
        s.callback.needs_recruiter = True
        return self._finish(EndReason.CALLBACK, prompts.callback_vague_close())

    def _resume_after_callback(self) -> AgentReply:
        s = self.state
        if s.phase is Phase.SCREENING and s.current is not None:
            _record, q = self._current()
            return self._ask(f"Sure. {tp.repeat_question(q)}", asked=q.id)
        if s.phase is Phase.CLOSING:
            return self._ask(tp.ANY_QUESTIONS)
        s.phase = Phase.SCREENING
        return self._ask_first()

    # --- moving through the questions -----------------------------------------------------------

    def _ask_first(self) -> AgentReply:
        s = self.state
        remaining = s.remaining()
        if not remaining:  # everything was answered on earlier calls
            s.phase = Phase.CLOSING
            return self._ask(f"{tp.role_intro(self.ctx)} {tp.ANY_QUESTIONS}")
        s.current = remaining[0]
        q = self.ctx.questions[s.current]
        return self._ask(tp.first_question(self.ctx, q, total=len(remaining)), asked=q.id)

    def _advance(self, *, prefix: str = "Thanks.") -> AgentReply:
        s = self.state
        if self._wrap_up:
            # Out of time: the questions left stay "not asked" and the next call resumes them
            return self._finish(EndReason.MAX_TURNS, tp.wrap_up_close(self.candidate))
        remaining = s.remaining()
        if not remaining:
            s.phase, s.current = Phase.CLOSING, None
            return self._ask(f"{prefix} {tp.ANY_QUESTIONS}")
        s.current = remaining[0]
        q = self.ctx.questions[s.current]
        text = tp.next_question(q, last=len(remaining) == 1, prefix=prefix)
        return self._ask(text, asked=q.id)

    def _current(self) -> tuple[AnswerRecord, RoundQuestion]:
        index = self.state.current
        assert index is not None
        return self.state.answers[index], self.ctx.questions[index]

    def _current_question(self) -> RoundQuestion | None:
        index = self.state.current
        return self.ctx.questions[index] if index is not None else None

    def _note_question(self, t: TelephonicTurn, text: str) -> None:
        asked = (t.candidate_question or text).strip()
        if asked:
            self.state.candidate_questions.append(asked[:300])

    # --- speaking -------------------------------------------------------------------------------

    def _ask(
        self,
        text: str,
        *,
        action: str = NextAction.ASK_QUESTION,
        asked: str | None = None,
        kind: AskKind = AskKind.QUESTION,
    ) -> AgentReply:
        self._last_question_text = text
        reply = self._say(text, action)
        reply.asked_field, reply.ask_kind = asked, (kind if asked else None)
        return reply

    def _finish(self, reason: EndReason, text: str) -> AgentReply:
        s = self.state
        s.end_reason = reason
        s.phase = _END_PHASE.get(reason, Phase.ENDED)
        log.info("telephonic_ended", reason=reason.value, turns=s.turn_count, call_id=s.call_id)
        return self._say(text, NextAction.END_CALL, end_call=True)

    def _say(self, text: str, action: str, *, end_call: bool = False) -> AgentReply:
        self._add("assistant", text)
        return AgentReply(text, str(action), end_call, self.state.phase)

    def _nothing(self) -> AgentReply:
        return AgentReply("", NextAction.END_CALL, True, self.state.phase)

    def _add(self, speaker: str, text: str) -> None:
        self.transcript.append(
            TranscriptEntry(
                seq=len(self.transcript) + 1,
                speaker=speaker,
                text=text,
                timestamp=self.clock.now().astimezone(UTC).isoformat(),
            )
        )
