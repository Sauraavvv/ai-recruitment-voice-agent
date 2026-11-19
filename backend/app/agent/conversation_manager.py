"""Turn loop for one screening conversation (phase plan 5.6).

Knows nothing about audio or telephony: P4/P6 feed it text and speak what it returns.
"""

import asyncio
import copy
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import structlog

from app.agent import prompts
from app.agent.extraction import consistency_flags, extract, normalize_key
from app.agent.prompts import PROMPT_VERSION, CandidateContext, JobConfig, model_key
from app.agent.schemas import AgentTurn, FieldName, NextAction
from app.agent.screening_agent import (
    DEFAULT_TIMEOUT_S,
    CallMetrics,
    ScreeningAgent,
    TurnCall,
    TurnFailed,
)
from app.agent.state import (
    MAX_ASKS,
    MAX_CLARIFICATIONS,
    AskKind,
    EndReason,
    FieldRecord,
    FieldStatus,
    FieldValue,
    Phase,
    QuestionSpec,
    ScreeningState,
)
from app.database.models.enums import ScreeningStatus
from app.providers.llm.base import LLMError, LLMProvider, Message

log = structlog.get_logger(__name__)

MAX_TURNS = 40
MAX_IDENTITY_ATTEMPTS = 3
MAX_PERMISSION_ATTEMPTS = 3
LOW_CONFIDENCE = 0.6
MAX_LOW_CONFIDENCE_REPROMPTS = 2
CALLBACK_MAX_AHEAD = timedelta(days=14)
MAX_WORDS = 40
MAX_WORDS_ANSWER = 55
MAX_SILENCES = 3  # re-prompt, "are you still there?", then close (phase-06 §5.5)

_END_PHASE = {
    EndReason.COMPLETED: Phase.ENDED,
    EndReason.CALLBACK: Phase.CALLBACK,
    EndReason.DECLINED: Phase.DECLINED,
    EndReason.OPTED_OUT: Phase.OPTED_OUT,
    EndReason.WRONG_PERSON: Phase.WRONG_PERSON,
    EndReason.ESCALATED: Phase.ESCALATED,
}


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass
class TranscriptEntry:
    seq: int
    speaker: str  # "assistant" | "candidate"
    text: str
    timestamp: str  # UTC ISO 8601
    interrupted: bool = False
    heard_text: str | None = None
    # Voice calls (Phase 6): filled in by the pipeline
    stt_confidence: float | None = None
    latency_ms: int | None = None  # candidate stopped speaking → first sound of this reply
    ack: str | None = None  # acknowledgement played before this reply ("Okay.")


@dataclass
class TurnLog:
    turn: int
    phase_before: str
    phase_after: str
    utterance: str
    reply: str
    action: str
    asked_field: str | None
    ask_kind: str | None
    settled: list[str]  # fields not MISSING when the reply was chosen
    updates: dict[str, Any] = field(default_factory=dict)
    dropped: dict[str, str] = field(default_factory=dict)
    invalid: dict[str, str] = field(default_factory=dict)
    guardrails: list[str] = field(default_factory=list)
    llm_calls: list[CallMetrics] = field(default_factory=list)
    prompt_version: str = PROMPT_VERSION


@dataclass
class Checkpoint:
    """Everything a turn can change, to undo a turn that was cancelled (see `restore`)."""

    state: ScreeningState
    transcript: list[TranscriptEntry]
    turn_logs: int
    consecutive_errors: int
    last_question_text: str | None


@dataclass
class AgentReply:
    text: str
    action: str
    end_call: bool
    phase: Phase
    asked_field: str | None = None
    ask_kind: AskKind | None = None
    state_diff: dict[str, Any] = field(default_factory=dict)
    log: TurnLog | None = None


@dataclass
class ScreeningResult:
    end_reason: EndReason
    screening_status: ScreeningStatus
    collected_data: dict[str, FieldValue]
    fields: dict[str, dict[str, Any]]
    missing_fields: list[str]
    callback: dict[str, Any]
    opted_out: bool
    declined_opportunity: bool
    identity_confirmed: bool | None
    candidate_questions: list[str]
    escalation_reason: str | None
    transcript: list[dict[str, Any]]
    turns: int
    llm_calls: int
    input_tokens: int
    output_tokens: int
    prompt_version: str = PROMPT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScreeningResult":
        """Inverse of `to_dict` (the post-call job reads the stored result)."""
        values = {k: data[k] for k in cls.__dataclass_fields__ if k in data}
        values["end_reason"] = EndReason(values["end_reason"])
        values["screening_status"] = ScreeningStatus(values["screening_status"])
        values.setdefault("transcript", [])
        return cls(**values)


def clean_for_speech(text: str, *, max_words: int = MAX_WORDS) -> str:
    """Strip markdown and emoji; keep it short while keeping the final question."""
    text = re.sub(r"[*_#`>\[\]]", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.MULTILINE)
    text = re.sub("[\U0001f000-\U0001faff☀-➿️]", "", text)
    text = " ".join(text.split())
    if len(text.split()) <= max_words:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    question = next((s for s in reversed(sentences) if s.endswith("?")), None)
    budget = max_words - (len(question.split()) if question else 0)
    kept: list[str] = []
    for s in sentences:
        if s is question:
            break
        if len(" ".join([*kept, s]).split()) > budget:
            break
        kept.append(s)
    if question:
        kept.append(question)
    return " ".join(kept) if kept else " ".join(text.split()[:max_words])


def resolve_callback(iso: str | None, now: datetime) -> datetime | None:
    """A callback time must be a real future time within 14 days (P2-T9)."""
    if not iso:
        return None
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=prompts.IST)
    if not now < when <= now + CALLBACK_MAX_AHEAD:
        return None
    return when


class ConversationManager:
    def __init__(
        self,
        job: JobConfig,
        candidate: CandidateContext,
        llm: LLMProvider,
        clock: Clock | None = None,
        prior_fields: dict[str, Any] | None = None,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.job = job
        self.candidate = candidate
        self.clock = clock or SystemClock()
        self.agent = ScreeningAgent(
            llm, timeout_s=timeout_s, cache_key=f"screening-{job.job_id or 'adhoc'}"
        )
        self.state = ScreeningState.new(
            candidate_name=candidate.name,
            job_title=job.job_title,
            questions=list(job.questions),
            candidate_id=candidate.candidate_id,
            call_id=candidate.call_id or str(uuid.uuid4()),
        )
        self.transcript: list[TranscriptEntry] = []
        self.turn_logs: list[TurnLog] = []
        self._consecutive_errors = 0
        self._last_question_text: str | None = None
        self._turn_log: TurnLog | None = None
        self._wrap_up_requested = False
        if prior_fields:
            self._load_prior(prior_fields)

    # --- public interface ----------------------------------------------------------------------

    async def start(self) -> AgentReply:
        if self.state.phase is not Phase.GREETING:
            raise RuntimeError("Conversation already started")
        self.state.phase = Phase.IDENTITY_CHECK
        self.state.identity_attempts = 1
        self._last_question_text = prompts.greeting(self.candidate)
        return self._say(self._last_question_text, NextAction.ASK_QUESTION)

    def checkpoint(self) -> Checkpoint:
        return Checkpoint(
            state=self.state.model_copy(deep=True),
            transcript=copy.deepcopy(self.transcript),
            turn_logs=len(self.turn_logs),
            consecutive_errors=self._consecutive_errors,
            last_question_text=self._last_question_text,
        )

    def restore(self, cp: Checkpoint) -> None:
        """Undo everything since `cp`: the voice pipeline cancels a turn when the candidate kept
        talking, merges the two utterances and runs the turn again (phase-06 §5.2)."""
        self.state = cp.state.model_copy(deep=True)
        self.transcript = copy.deepcopy(cp.transcript)
        del self.turn_logs[cp.turn_logs :]
        self._consecutive_errors = cp.consecutive_errors
        self._last_question_text = cp.last_question_text
        self._turn_log = None

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

    async def _handle_utterance(self, text: str, *, stt_confidence: float | None) -> AgentReply:
        s = self.state
        if s.ended:
            return AgentReply("", NextAction.END_CALL, True, s.phase)
        if s.phase is Phase.GREETING:
            raise RuntimeError("Call start() before handle_utterance()")
        text = text.strip()
        s.turn_count += 1
        self._add("candidate", text)
        self.transcript[-1].stt_confidence = stt_confidence
        before = self._fingerprint()
        phase_before = s.phase

        low = stt_confidence is not None and stt_confidence < LOW_CONFIDENCE
        if (not text or low) and s.low_confidence_streak < MAX_LOW_CONFIDENCE_REPROMPTS:
            s.low_confidence_streak += 1
            return self._log(
                before, phase_before, text, self._say(prompts.low_confidence(), "clarify")
            )
        s.low_confidence_streak = 0

        if s.turn_count > MAX_TURNS:
            reply = self._finish(EndReason.MAX_TURNS, prompts.max_turns_close(self.candidate))
            return self._log(before, phase_before, text, reply)

        messages = self._messages(text)
        try:
            call = await self.agent.run(messages)
        except LLMError as exc:
            calls = exc.calls if isinstance(exc, TurnFailed) else []
            self._consecutive_errors += 1
            if self._consecutive_errors >= 2:
                s.escalation_reason = "llm_error"
                reply = self._finish(EndReason.ERROR, prompts.error_close())
            else:
                reply = self._say(prompts.llm_error_retry(), NextAction.CLARIFY)
            reply_log = self._log(before, phase_before, text, reply)
            if reply_log.log:
                reply_log.log.llm_calls = calls
                reply_log.log.guardrails.append(f"llm_error:{type(exc).__name__}")
            return reply_log
        self._consecutive_errors = 0
        self._turn_log = TurnLog(
            turn=s.turn_count,
            phase_before=phase_before.value,
            phase_after="",
            utterance=text,
            reply="",
            action="",
            asked_field=None,
            ask_kind=None,
            settled=[],
            llm_calls=list(call.calls),
        )
        reply = await self._apply(call, text, messages)
        return self._log(before, phase_before, text, reply)

    async def handle_silence(self, count: int, *, max_silences: int = MAX_SILENCES) -> AgentReply:
        """`count` = consecutive silence timeouts. The first repeats the question in its short
        form, the next ones ask "are you still there?", the last ends the call."""
        if self.state.ended:
            return AgentReply("", NextAction.END_CALL, True, self.state.phase)
        if count >= max_silences:
            return self._finish(EndReason.NO_RESPONSE, prompts.silence_close())
        if count == 1 and max_silences > 2:
            return self._say(prompts.silence_reprompt(self._short_question()), "reprompt")
        return self._say(prompts.silence_prompt(self._last_question_text), NextAction.ASK_QUESTION)

    def request_wrap_up(self) -> None:
        """The call is running long (phase-06 §5.5): after the candidate's next answer, read
        back what we have instead of asking the next question, then close."""
        if not self._wrap_up_requested:
            self._wrap_up_requested = True
            log.info("screening_wrap_up", turns=self.state.turn_count, call_id=self.state.call_id)

    def time_up(self) -> AgentReply:
        """Hard call limit: close now."""
        if self.state.ended:
            return AgentReply("", NextAction.END_CALL, True, self.state.phase)
        return self._finish(EndReason.MAX_TURNS, prompts.max_turns_close(self.candidate))

    def _short_question(self) -> str | None:
        key = self.state.current_question
        if key and self.state.current_ask_kind is AskKind.QUESTION:
            spec = self.state.spec(key)
            if spec is not None:
                return spec.prompt
        return self._last_question_text

    async def handle_interruption(self, heard_portion: str) -> None:
        """The candidate barged in: only `heard_portion` of the last reply was played."""
        for entry in reversed(self.transcript):
            if entry.speaker == "assistant":
                entry.interrupted = True
                entry.heard_text = heard_portion.strip()
                return

    async def end(self, reason: EndReason) -> ScreeningResult:
        s = self.state
        if not s.ended:
            s.end_reason = reason
            s.phase = _END_PHASE.get(reason, Phase.ENDED)
        assert s.end_reason is not None
        calls = [c for t in self.turn_logs for c in t.llm_calls]
        return ScreeningResult(
            end_reason=s.end_reason,
            screening_status=self._screening_status(),
            collected_data=s.collected_data(),
            fields={k: r.model_dump(mode="json") for k, r in s.fields.items()},
            missing_fields=s.missing_fields(),
            callback=s.callback.model_dump(mode="json"),
            opted_out=s.opted_out,
            declined_opportunity=s.declined_opportunity,
            identity_confirmed=s.identity_confirmed,
            candidate_questions=list(s.candidate_questions),
            escalation_reason=s.escalation_reason,
            transcript=[asdict(e) for e in self.transcript],
            turns=s.turn_count,
            llm_calls=len(calls),
            input_tokens=sum(c.input_tokens for c in calls),
            output_tokens=sum(c.output_tokens for c in calls),
        )

    def snapshot(self) -> dict[str, Any]:
        """JSON-serializable state for persistence (P6/P7)."""
        return {
            "prompt_version": PROMPT_VERSION,
            "state": self.state.model_dump(mode="json"),
            "transcript": [asdict(e) for e in self.transcript],
        }

    # --- turn handling -------------------------------------------------------------------------

    async def _apply(self, call: TurnCall, utterance: str, messages: list[Any]) -> AgentReply:
        s, t = self.state, call.turn

        if t.opt_out:
            s.opted_out = True
            return self._finish(EndReason.OPTED_OUT, prompts.opt_out_close())

        if s.phase is Phase.IDENTITY_CHECK:
            if t.identity_confirmed is False:
                s.identity_confirmed = False
                return self._finish(EndReason.WRONG_PERSON, prompts.wrong_person_close())
            undecided = t.identity_confirmed is None
            if undecided and not (t.callback_requested or t.declined_opportunity):
                s.identity_attempts += 1
                if s.identity_attempts > MAX_IDENTITY_ATTEMPTS:
                    s.escalation_reason = "identity_not_confirmed"
                    return self._finish(EndReason.ESCALATED, prompts.identity_unresolved_close())
                return self._say(clean_for_speech(t.response_text), NextAction.CLARIFY)
            if t.identity_confirmed:
                s.identity_confirmed = True

        ext = extract(t, utterance, s) if s.identity_confirmed else None
        pending_range = self._merge(ext) if ext else None

        if t.candidate_question:
            s.candidate_questions.append(t.candidate_question.strip()[:300])

        interested = s.fields.get(FieldName.INTERESTED)
        if t.declined_opportunity or (interested and interested.value is False):
            s.declined_opportunity = True
            if interested and interested.status is FieldStatus.MISSING:
                s.merge(FieldName.INTERESTED, False, raw_text=utterance, turn=s.turn_count)
            return self._finish(EndReason.DECLINED, prompts.declined_close(self.candidate))

        if s.callback.time_asked and t.permission_granted and not t.callback_requested:
            s.callback.requested = s.callback.time_asked = False  # "actually, go ahead now"
            s.phase = Phase.PERMISSION
        elif (
            t.callback_requested
            or s.callback.time_asked
            or (s.phase is Phase.PERMISSION and t.permission_granted is False)
        ):
            return self._callback(t)

        if t.next_action is NextAction.ESCALATE:
            s.escalation_reason = (t.candidate_question or "candidate asked for a person")[:300]
            return self._finish(EndReason.ESCALATED, prompts.escalate_close())

        if s.phase is Phase.IDENTITY_CHECK:  # identity just confirmed
            s.phase = Phase.PERMISSION
            s.permission_attempts = 1
            self._last_question_text = prompts.introduction(self.candidate, self.job)
            return self._say(self._last_question_text, NextAction.ASK_QUESTION)

        if s.phase is Phase.PERMISSION:
            if t.permission_granted:
                s.phase = Phase.SCREENING
                return self._ask_next(prefix=prompts.role_line(self.job))
            s.permission_attempts += 1
            if s.permission_attempts > MAX_PERMISSION_ATTEMPTS:
                s.callback.requested = s.callback.needs_recruiter = True
                return self._finish(EndReason.CALLBACK, prompts.callback_vague_close())
            return self._say(
                clean_for_speech(t.response_text, max_words=MAX_WORDS_ANSWER),
                NextAction.ANSWER_CANDIDATE,
            )

        if s.phase is Phase.CONFIRMATION:
            return self._finish(EndReason.COMPLETED, prompts.closing(self.candidate))

        return await self._screening_reply(t, ext, pending_range, messages)

    def _merge(self, ext: Any) -> tuple[str, float, float] | None:
        s = self.state
        in_confirmation = s.phase is Phase.CONFIRMATION
        updates: dict[str, Any] = {}
        for u in ext.updates:
            outcome = s.merge(
                u.key,
                u.value,
                raw_text=u.raw_text,
                turn=s.turn_count,
                meta=u.meta,
                affirmed=in_confirmation,
            )
            updates[u.key] = {"value": u.value, "outcome": outcome.value}
        pending_range = None
        for r in ext.ranges:
            rec = s.fields[r.key]
            if rec.has_value:
                continue
            if rec.meta.get("range_asked") or rec.clarify_count >= MAX_CLARIFICATIONS:
                s.merge(
                    r.key,
                    r.low,
                    raw_text=r.raw_text,
                    turn=s.turn_count,
                    meta={"range": [r.low, r.high]},
                )
                updates[r.key] = {"value": r.low, "outcome": "range_lower_bound"}
            elif pending_range is None:
                pending_range = (r.key, r.low, r.high)
        for k in ext.declined:
            if s.decline(k):
                updates[k] = {"outcome": "declined"}
        for k in ext.unknown:
            if s.mark_unknown(k):
                updates[k] = {"outcome": "unknown"}
        for k in ext.confirmed:
            rec = s.fields[k]
            if in_confirmation and k not in s.readback_fields:
                continue  # only what was read back can be affirmed by "yes, that's correct"
            if not in_confirmation and rec.turn == s.turn_count:
                continue  # a value given this turn hasn't been read back, so can't be affirmed
            asked_to_confirm = s.current_ask_kind is AskKind.CONFIRM and s.current_question == k
            if (in_confirmation or rec.needs_confirmation or asked_to_confirm) and s.confirm(k):
                updates.setdefault(k, {})["outcome"] = "confirmed"
        for k in consistency_flags(s):
            rec = s.fields[k]
            if not rec.meta.get("consistency_checked"):
                rec.meta["consistency_checked"] = True
                rec.needs_confirmation = True
                updates.setdefault(k, {})["needs_confirmation"] = True
        tl = self._turn_log
        if tl:
            tl.updates, tl.dropped, tl.invalid = updates, dict(ext.dropped), dict(ext.invalid)
        return pending_range

    def _callback(self, t: AgentTurn) -> AgentReply:
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
            return self._say(prompts.callback_ask(), NextAction.SCHEDULE_CALLBACK)
        s.callback.needs_recruiter = True
        return self._finish(EndReason.CALLBACK, prompts.callback_vague_close())

    async def _screening_reply(
        self,
        t: AgentTurn,
        ext: Any,
        pending_range: tuple[str, float, float] | None,
        messages: list[Any],
    ) -> AgentReply:
        s = self.state
        guard = self._guardrails()
        if self._wrap_up_requested:
            guard.append("wrap_up")
            return self._to_confirmation(prefix=prompts.wrap_up_line())

        # Python-detected problems come first: a range to narrow, or a value that failed checks.
        if pending_range:
            key, low, high = pending_range
            s.fields[key].meta["range_asked"] = True
            guard.append(f"range_clarify:{key}")
            text = prompts.range_clarify(self._spec(key), low, high)
            return self._ask_field(key, AskKind.CLARIFY, text)
        for key in ext.invalid if ext else []:
            rec = s.fields[key]
            if rec.status is FieldStatus.MISSING:
                if rec.clarify_count < MAX_CLARIFICATIONS:
                    guard.append(f"invalid_clarify:{key}")
                    return self._ask_field(key, AskKind.CLARIFY, prompts.clarify(self._spec(key)))
                s.mark_unknown(key)

        # The model wants to clarify a field that is still missing.
        target = normalize_key(t.next_question, s)
        if t.next_action is NextAction.CLARIFY and target:
            rec = s.fields[target]
            if rec.status is FieldStatus.MISSING:
                if rec.clarify_count < MAX_CLARIFICATIONS:
                    return self._ask_field(
                        target, AskKind.CLARIFY, clean_for_speech(t.response_text)
                    )
                s.mark_unknown(target)
                guard.append(f"gave_up:{target}")
                target = None

        expected = s.next_field()
        if expected is None:
            return self._to_confirmation()

        if self._valid_target(t, target):
            assert target is not None
            kind = AskKind.CONFIRM if s.fields[target].needs_confirmation else AskKind.QUESTION
            words = MAX_WORDS_ANSWER if t.candidate_question else MAX_WORDS
            return self._ask_field(target, kind, clean_for_speech(t.response_text, max_words=words))

        if t.next_action is NextAction.ANSWER_CANDIDATE and target is None:
            answer = clean_for_speech(t.response_text, max_words=MAX_WORDS_ANSWER)
            guard.append("appended_question")
            return self._ask_next(prefix=answer)

        # Guardrail (5.6 step 6). A confirmation the model couldn't know about goes straight to
        # the template; otherwise re-prompt once, then fall back to the configured question.
        if not s.fields[expected].needs_confirmation:
            reason = (
                f"already {s.fields[target].status.value}"
                if target and target in s.fields
                else "no valid next_question"
            )
            guard.append(f"reprompt:{reason}")
            spec = self._spec(expected)
            note = (
                f"CORRECTION: your reply was invalid ({reason}"
                f"{'; the call is not complete' if t.conversation_complete else ''}). Keep the "
                f"same extraction, but your response_text must ask about {model_key(expected)} "
                f'("{spec.prompt}") and next_question must be '
                f"{model_key(expected)}."
            )
            try:
                retry = await self.agent.run([*messages, Message("developer", note)])
                if self._turn_log:
                    self._turn_log.llm_calls.extend(retry.calls)
                retarget = normalize_key(retry.turn.next_question, s)
                if retarget == expected and self._valid_target(retry.turn, retarget):
                    return self._ask_field(
                        expected, AskKind.QUESTION, clean_for_speech(retry.turn.response_text)
                    )
            except LLMError:
                pass
        guard.append(f"template:{expected}")
        return self._ask_next(prefix="Got it.")

    def _valid_target(self, t: AgentTurn, target: str | None) -> bool:
        s = self.state
        if target is None or t.conversation_complete or t.next_action is NextAction.END_CALL:
            return False
        rec = s.fields[target]
        pending = s.pending_confirmation()
        if pending:
            return target in pending
        return rec.status is FieldStatus.MISSING and rec.asked_count < MAX_ASKS

    def _ask_next(self, *, prefix: str = "") -> AgentReply:
        s = self.state
        key = s.next_field()
        if key is None:
            return self._to_confirmation(prefix=prefix)
        spec = self._spec(key)
        rec = s.fields[key]
        if rec.needs_confirmation:
            text = f"{prefix} {prompts.confirm_value(spec, rec.value)}".strip()
            return self._ask_field(key, AskKind.CONFIRM, text)
        return self._ask_field(key, AskKind.QUESTION, prompts.ask(spec, prefix=prefix))

    def _ask_field(self, key: str, kind: AskKind, text: str) -> AgentReply:
        action = NextAction.CLARIFY if kind is AskKind.CLARIFY else NextAction.ASK_QUESTION
        if self.state.fields[key].asked_count + 1 > MAX_ASKS and kind is AskKind.QUESTION:
            # Never loop on a field: give up on it and move on.
            self.state.mark_unknown(key)
            return self._ask_next(prefix="Okay.")
        self.state.note_asked(key, kind)
        self._last_question_text = text
        reply = self._say(text, action)
        reply.asked_field, reply.ask_kind = key, kind
        return reply

    def _to_confirmation(self, *, prefix: str = "") -> AgentReply:
        s = self.state
        rb = prompts.readback(s)
        if rb is None:
            return self._finish(EndReason.COMPLETED, prompts.closing(self.candidate))
        s.phase = Phase.CONFIRMATION
        s.current_question, s.current_ask_kind = None, AskKind.CONFIRM
        text, s.readback_fields = rb
        if prefix and prefix not in ("Got it.", "Okay."):
            text = f"{prefix} {text}"
        self._last_question_text = text
        reply = self._say(text, NextAction.ASK_QUESTION)
        reply.ask_kind = AskKind.CONFIRM
        return reply

    def _finish(self, reason: EndReason, text: str) -> AgentReply:
        s = self.state
        s.end_reason = reason
        s.phase = _END_PHASE.get(reason, Phase.ENDED)
        s.current_question = None
        log.info("screening_ended", reason=reason.value, turns=s.turn_count, call_id=s.call_id)
        return self._say(text, NextAction.END_CALL, end_call=True)

    def _say(self, text: str, action: str, *, end_call: bool = False) -> AgentReply:
        self._add("assistant", text)
        return AgentReply(text, str(action), end_call, self.state.phase)

    # --- helpers -------------------------------------------------------------------------------

    def _spec(self, key: str) -> QuestionSpec:
        spec = self.state.spec(key)
        assert spec is not None, key
        return spec

    def _guardrails(self) -> list[str]:
        return self._turn_log.guardrails if self._turn_log else []

    def _messages(self, utterance: str) -> list[Any]:
        history = []
        for e in self.transcript[:-1]:
            text = e.text
            if e.interrupted:
                text = f"{e.heard_text or ''}… (interrupted by the candidate)"
            history.append((e.speaker, text))
        return prompts.build_messages(
            job=self.job,
            state=self.state,
            history=history,
            utterance=utterance,
            now=self.clock.now(),
        )

    def _add(self, speaker: str, text: str) -> None:
        self.transcript.append(
            TranscriptEntry(
                seq=len(self.transcript) + 1,
                speaker=speaker,
                text=text,
                timestamp=self.clock.now().astimezone(UTC).isoformat(),
            )
        )

    def _fingerprint(self) -> dict[str, tuple[Any, str, bool]]:
        return {
            k: (r.value, r.status.value, r.needs_confirmation) for k, r in self.state.fields.items()
        }

    def _log(
        self, before: dict[str, Any], phase_before: Phase, utterance: str, reply: AgentReply
    ) -> AgentReply:
        s = self.state
        after = self._fingerprint()
        diff = {
            k: {"value": v[0], "status": v[1], **({"needs_confirmation": True} if v[2] else {})}
            for k, v in after.items()
            if before.get(k) != v
        }
        if phase_before is not s.phase:
            diff["_phase"] = {"from": phase_before.value, "to": s.phase.value}
        reply.state_diff = diff
        tl = self._turn_log
        if tl is None or tl.turn != s.turn_count:
            tl = TurnLog(
                turn=s.turn_count,
                phase_before=phase_before.value,
                phase_after="",
                utterance=utterance,
                reply="",
                action="",
                asked_field=None,
                ask_kind=None,
                settled=[],
            )
        tl.phase_after = s.phase.value
        tl.reply, tl.action = reply.text, reply.action
        tl.asked_field = reply.asked_field
        tl.ask_kind = reply.ask_kind.value if reply.ask_kind else None
        tl.settled = [k for k, r in s.fields.items() if r.settled]
        self.turn_logs.append(tl)
        reply.log = tl
        self._turn_log = None
        log.info(
            "agent_turn",
            turn=tl.turn,
            phase=tl.phase_after,
            action=tl.action,
            asked=tl.asked_field,
            guardrails=tl.guardrails or None,
            latency_ms=sum(c.latency_ms for c in tl.llm_calls) or None,
            prompt_version=PROMPT_VERSION,
        )
        return reply

    def _screening_status(self) -> ScreeningStatus:
        s = self.state
        reason = s.end_reason
        if reason is EndReason.OPTED_OUT or s.opted_out:
            return ScreeningStatus.OPTED_OUT
        if reason is EndReason.WRONG_PERSON:
            return ScreeningStatus.WRONG_PERSON
        if reason is EndReason.DECLINED:
            return ScreeningStatus.DECLINED
        if reason is EndReason.CALLBACK:
            return ScreeningStatus.CALLBACK_REQUESTED
        if reason is EndReason.COMPLETED and s.required_complete():
            return ScreeningStatus.COMPLETED
        if any(r.has_value for r in s.fields.values()):
            return ScreeningStatus.PARTIALLY_COMPLETED
        return ScreeningStatus.NOT_STARTED

    def _load_prior(self, prior: dict[str, Any]) -> None:
        """Resume a callback/retry without re-asking known answers."""
        for key, value in prior.items():
            if key not in self.state.fields or value is None:
                continue
            if isinstance(value, dict) and "status" in value:
                rec = FieldRecord.model_validate(value)
                rec.asked_count = rec.clarify_count = 0
                if rec.status is FieldStatus.UNKNOWN:
                    rec.status = FieldStatus.MISSING  # worth asking again on a new call
            else:
                rec = FieldRecord(
                    value=value, status=FieldStatus.ANSWERED, meta={"source": "prior_call"}
                )
            self.state.fields[key] = rec
