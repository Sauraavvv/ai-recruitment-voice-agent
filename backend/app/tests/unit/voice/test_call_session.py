"""CallSession end to end with fakes (phase-06 §7.1): turn order, acknowledgements, merging,
barge-in, backchannels, silence, failures, hang-ups, isolation and leaks."""

import asyncio
from typing import Any

from app.agent.prompts import CandidateContext
from app.agent.state import EndReason, Phase
from app.database.models import CallEndReason
from app.providers.tts import ACKNOWLEDGEMENTS
from app.tests.unit.agent.stub_llm import ScriptedLLM, turn
from app.tests.unit.voice.session_harness import FakeTTS, Harness, fast_settings
from app.voice.turn_manager import TurnState

INTERESTED = turn(
    "Got it. Where are you currently based?",
    fields={"interested": True},
    evidence={"interested": "yes I'm interested"},
    next_question="current_location",
)


class SlowLLM(ScriptedLLM):
    def __init__(self, delay_s: float = 0.4, outputs: list[Any] | None = None) -> None:
        super().__init__(outputs)
        self.delay_s = delay_s

    async def structured(self, *args: Any, **kwargs: Any) -> Any:
        result = await super().structured(*args, **kwargs)
        await asyncio.sleep(self.delay_s)
        return result


async def to_screening(h: Harness) -> None:
    """Greeting → identity → introduction → permission → role line + first question."""
    h.llm.push(turn(identity_confirmed=True))
    h.say("Yes, speaking.")
    await h.wait_listening(2)
    h.llm.push(turn(permission_granted=True))
    h.say("Sure, go ahead.")
    await h.wait_listening(3)


async def test_conversation_turns_acks_and_latency() -> None:
    h = Harness()
    await h.start()
    assert h.spoken()[0] == "Hello, am I speaking with Rahul Sharma?"
    await to_screening(h)
    # No acknowledgement before the introduction (identity phase), one before the role line.
    # Long replies go to TTS as two requests: the first sentence, then the rest (prefetch).
    spoken = h.spoken()
    assert spoken[1].startswith("Hi Rahul, I'm an AI recruitment assistant")
    acks = [t for t in spoken if t in ACKNOWLEDGEMENTS]
    assert len(acks) == 1 and spoken.index(acks[0]) > 2
    assert spoken[spoken.index(acks[0]) + 1] == "Great, thank you."

    h.llm.push(INTERESTED)
    await h.voice(400)  # their words on the line, so the VAD sees when they stopped
    await asyncio.sleep(0.25)
    h.say("Yes, I'm interested.")
    await h.wait_listening(4)
    spoken = h.spoken()
    acks = [t for t in spoken if t in ACKNOWLEDGEMENTS]
    assert len(acks) == 2 and acks[1] != acks[0]  # never the same one twice in a row
    ack = acks[1]
    assert spoken[-1] == "Where are you currently based?"  # "Got it." was already said
    entry = h.manager.transcript[-1]
    assert entry.text == "Got it. Where are you currently based?" and entry.ack == ack
    assert entry.latency_ms is not None and entry.latency_ms >= 0

    outcome = await h.hang_up()
    assert outcome.end_reason is CallEndReason.CANDIDATE_HANGUP and outcome.ended_by == "caller"
    assert outcome.result.collected_data["interested"] is True
    assert [m["turn"] for m in outcome.metrics] == [1, 2, 3]
    assert outcome.metrics[2]["ack"] == ack and outcome.metrics[2]["llm_ms"] is not None
    # turns alternate: greeting, then candidate/agent pairs
    speakers = [e["speaker"] for e in outcome.result.transcript]
    assert speakers == ["assistant"] + ["candidate", "assistant"] * 3
    assert h.stt.closed and h.stt.audio_bytes > 0


async def test_hello_before_the_greeting_is_dropped_answer_over_it_is_kept() -> None:
    h = Harness(settings=fast_settings(greeting_wait_ms=1000))
    await h.start(wait_greeting=False)
    await h.voice(200)  # "Hello?"
    h.say("Hello?")
    await h.wait(lambda: h.session._greeting_started, 3)
    h.llm.push(turn(identity_confirmed=True))
    h.say("Yes this is Rahul")  # said over the greeting: answered once it ends
    await h.wait_listening(2)
    texts = [e.text for e in h.manager.transcript if e.speaker == "candidate"]
    assert texts == ["Yes this is Rahul"]
    await h.hang_up()


async def test_candidate_keeps_talking_turns_are_merged() -> None:
    h = Harness(SlowLLM(0.5))
    await h.start()
    await to_screening(h)
    h.llm.push(INTERESTED, INTERESTED)  # the first request is cancelled
    h.say("Yes I am")
    await h.wait(lambda: len(h.llm.calls) == 3, 3)  # the agent is thinking about it
    h.say("very interested in this role")
    await h.wait_listening(4, timeout=8)
    candidate = [e.text for e in h.manager.transcript if e.speaker == "candidate"]
    assert candidate[-1] == "Yes I am very interested in this role"
    assert len(candidate) == 3 and h.session.merges == 1
    last_prompt = h.llm.calls[-1][-1].content
    assert "Yes I am very interested in this role" in last_prompt
    outcome = await h.hang_up()
    assert outcome.metrics[-1]["merged"] == 1
    # one acknowledgement for the merged turn
    assert sum(1 for t in h.spoken()[4:] if t in ACKNOWLEDGEMENTS) == 1


async def test_barge_in_stops_playback_and_is_recorded() -> None:
    h = Harness(tts=FakeTTS(ms_per_word=150))
    await h.start()
    h.llm.push(turn(identity_confirmed=True))
    h.say("Yes, speaking.")  # the introduction is long: about 5 s of audio
    await h.wait(lambda: h.state is TurnState.SPEAKING, 3)
    await asyncio.sleep(1.0)
    await h.voice(600, wait=False)  # the candidate talks over it
    await h.wait(lambda: h.state is TurnState.LISTENING, 3)
    assert h.line.events("clear")
    intro = h.manager.transcript[-1]
    assert intro.interrupted and intro.heard_text is not None
    assert 0 < len(intro.heard_text.split()) < len(intro.text.split())
    (info,) = h.session.barge_ins
    assert info["reason"] == "long_speech" and info["stop_latency_ms"] < 600
    # The candidate's words arrive; the agent answers knowing it was interrupted
    h.llm.push(turn(permission_granted=True))
    h.say("Sorry, who is this?")
    await h.wait_listening(3)
    assert any("(interrupted by the candidate)" in m.content for m in h.llm.calls[-1])
    outcome = await h.hang_up()
    assert outcome.metrics[0]["interrupted"] is True  # the greeting has no turn metrics


async def test_backchannel_during_speech_is_ignored() -> None:
    h = Harness(tts=FakeTTS(ms_per_word=150))
    await h.start()
    await to_screening(h)
    h.llm.push(INTERESTED)
    h.say("yes I'm interested")
    await h.wait(lambda: h.state is TurnState.SPEAKING, 3)
    h.say("okay")  # mid-question, not an answer to anything
    await h.wait_listening(4)
    await asyncio.sleep(0.1)
    assert h.session.backchannels_ignored == 1 and not h.line.events("clear")
    assert h.state is TurnState.LISTENING
    await h.hang_up()


async def test_yes_over_the_end_of_a_yes_no_question_is_the_answer() -> None:
    h = Harness(tts=FakeTTS(ms_per_word=150))
    await h.start()
    h.llm.push(turn(identity_confirmed=True))
    h.say("Yes, speaking.")  # → "…Is this a good time for a quick conversation?"
    await h.wait(lambda: h.state is TurnState.SPEAKING, 3)
    h.llm.push(turn(permission_granted=True))
    h.say("yes")
    await h.wait_listening(3, timeout=10)
    assert h.manager.state.phase is Phase.SCREENING
    await h.hang_up()


async def test_silence_reprompts_then_asks_then_closes() -> None:
    h = Harness(tts=FakeTTS(ms_per_word=30))
    await h.start()
    outcome = await h.finished(timeout=15)
    agent = [e["text"] for e in outcome.result.transcript if e["speaker"] == "assistant"]
    assert agent[1] == "Sorry, I'll ask again. Hello, am I speaking with Rahul Sharma?"
    assert agent[2].startswith("Are you still there?")
    assert agent[3].startswith("It seems we got disconnected")
    assert len(agent) == 4
    assert outcome.end_reason is CallEndReason.SILENCE_TIMEOUT and outcome.ended_by == "agent"
    assert h.line.sent[-1]["event"] == "mark"  # hung up after the closing line played


async def test_speech_postpones_the_silence_timeout() -> None:
    h = Harness(settings=fast_settings(silence_timeout_s=0.8))
    await h.start()
    await h.voice(1200)  # talking (STT hasn't produced words yet)
    await asyncio.sleep(0.3)
    assert h.session._silences == 0
    await h.hang_up()


async def test_stt_failure_apologises_and_ends() -> None:
    h = Harness()
    await h.start()
    h.stt.push("error", detail="no stream for 5 s")
    outcome = await h.finished()
    assert "<apology>" in h.spoken()
    assert outcome.end_reason is CallEndReason.TECHNICAL_FAILURE
    assert outcome.failure_reason == "stt_unavailable" and outcome.ended_by == "agent"


async def test_tts_failure_apologises_and_ends() -> None:
    h = Harness()
    await h.start()
    h.tts.fail = True
    h.llm.push(turn(identity_confirmed=True))
    h.say("Yes, speaking.")
    outcome = await h.finished()
    assert outcome.end_reason is CallEndReason.TECHNICAL_FAILURE
    assert outcome.failure_reason == "tts_failed"
    assert outcome.result.identity_confirmed is True  # what we learned is kept


async def test_agent_ends_the_call_after_the_closing_line() -> None:
    h = Harness()
    await h.start()
    h.llm.push(turn(identity_confirmed=False))
    h.say("No, wrong number.")
    outcome = await h.finished()
    assert outcome.end_reason is CallEndReason.WRONG_PERSON and outcome.ended_by == "agent"
    assert h.spoken()[-1].startswith("Sorry for the trouble")
    assert h.manager.state.end_reason is EndReason.WRONG_PERSON


async def test_hang_up_while_thinking_keeps_the_answer() -> None:
    h = Harness(SlowLLM(0.3))
    await h.start()
    await to_screening(h)
    h.llm.push(INTERESTED)
    h.say("Yes I'm interested")
    await h.wait(lambda: h.state is TurnState.THINKING, 2)
    outcome = await h.hang_up()
    assert outcome.result.collected_data["interested"] is True
    assert outcome.end_reason is CallEndReason.CANDIDATE_HANGUP


async def test_socket_drop_is_a_technical_failure() -> None:
    h = Harness()
    await h.start()
    outcome = await h.hang_up("disconnect")
    assert outcome.end_reason is CallEndReason.TECHNICAL_FAILURE
    assert outcome.failure_reason == "stream_dropped" and outcome.ended_by == "error"


async def test_time_limit_wraps_up_and_closes() -> None:
    settings = fast_settings(call_wrap_up_s=0.5, max_call_duration_s=21.5)  # time up at 1.5 s
    h = Harness(settings=settings, tts=FakeTTS(ms_per_word=20))
    await h.start()
    outcome = await h.finished(timeout=10)
    assert outcome.end_reason is CallEndReason.MAX_DURATION
    assert h.manager.transcript[-1].text.startswith("Thanks, Rahul. I'll pass what we've covered")
    assert h.spoken()[-2:] == ["Thanks, Rahul.", h.manager.transcript[-1].text[15:]]


async def test_two_sessions_are_isolated() -> None:
    a = Harness(attempt_id="call-A", candidate=CandidateContext(name="Asha Rao"))
    b = Harness(attempt_id="call-B", candidate=CandidateContext(name="Bilal Khan"))
    await asyncio.gather(a.start(), b.start())
    a.llm.push(turn(identity_confirmed=True))
    b.llm.push(turn(identity_confirmed=True))
    a.say("Yes, Asha here.")
    b.say("Yes, Bilal speaking.")
    await asyncio.gather(a.wait_listening(2), b.wait_listening(2))
    out_a, out_b = await asyncio.gather(a.hang_up(), b.hang_up())

    for h, me, other in ((a, "Asha", "Bilal"), (b, "Bilal", "Asha")):
        assert {m["stream_sid"] for m in h.line.sent} == {f"stream-{h.session.id}"}
        assert {aid for aid, _ in h.tts.spoken} == {h.session.id}
        text = " ".join(h.spoken())
        assert me in text and other not in text
    assert "Asha" in str(out_a.result.transcript) and "Bilal" not in str(out_a.result.transcript)
    assert "Bilal" in str(out_b.result.transcript) and "Asha" not in str(out_b.result.transcript)
    # nothing shared between the two sessions
    for attr in ("inbound", "sender", "marks", "stt", "manager", "vad", "player", "assembler"):
        assert getattr(a.session, attr) is not getattr(b.session, attr), attr
    assert a.session._events is not b.session._events


async def test_twenty_sessions_leave_no_tasks_behind() -> None:
    await asyncio.sleep(0)
    baseline = len(asyncio.all_tasks())
    for i in range(20):
        h = Harness(attempt_id=f"leak-{i:02d}", tts=FakeTTS(ms_per_word=5))
        await h.start()
        h.llm.push(turn(identity_confirmed=True))
        h.say("Yes.")
        await h.wait_listening(2)
        await h.hang_up()
        for _ in range(5):
            await asyncio.sleep(0.05)  # pending mark echoes in the fake line finish
    await asyncio.sleep(0.1)
    assert len(asyncio.all_tasks()) <= baseline


async def test_job_questions_are_synthesized_during_the_greeting() -> None:
    h = Harness(settings=fast_settings(voice_tts_warm=True))
    await h.start()
    await h.wait(lambda: len(h.spoken()) >= 1 + 3 + len(h.manager.state.questions), 3)
    spoken = h.spoken()
    assert spoken[0].startswith("Hello, am I speaking")
    assert {q.prompt for q in h.manager.state.questions} <= set(spoken)
    assert {aid for aid, _ in h.tts.spoken} == {h.session.id}
    await h.hang_up()


# --- found on the first real call (2026-11-19) ------------------------------------------------


async def test_slow_reply_gets_one_moment_once() -> None:
    h = Harness(SlowLLM(1.2), settings=fast_settings(voice_hold_after_ms=400))
    await h.start()
    await to_screening(h)
    h.llm.push(INTERESTED)
    h.say("Yes, I'm interested.")
    await h.wait_listening(4, timeout=8)
    spoken = h.spoken()
    assert spoken.count("One moment.") >= 1
    last_hold = len(spoken) - 1 - spoken[::-1].index("One moment.")
    last_turn = spoken[last_hold - 1 :]
    assert last_turn[0] in ACKNOWLEDGEMENTS and last_turn[-1] == "Where are you currently based?"
    outcome = await h.hang_up()
    assert outcome.metrics[-1]["hold"] is True


async def test_fast_reply_gets_no_hold_phrase() -> None:
    h = Harness(settings=fast_settings(voice_hold_after_ms=400))
    await h.start()
    await to_screening(h)
    await asyncio.sleep(0.6)
    assert "One moment." not in h.spoken()
    await h.hang_up()


async def test_talking_into_the_pause_does_not_cut_the_reply() -> None:
    """The candidate says "Hello?" into the thinking pause and is still talking when the reply
    starts: that's not a barge-in (it cut two replies at their first word on the real call)."""
    h = Harness(SlowLLM(0.8), tts=FakeTTS(ms_per_word=120))
    await h.start()
    h.llm.push(turn(identity_confirmed=True))
    h.say("Yes, speaking.")
    await asyncio.sleep(0.3)
    await h.voice(1500, wait=False)  # still going when the reply begins at ~0.8 s
    await h.wait(lambda: h.state is TurnState.SPEAKING, 3)
    await asyncio.sleep(1.0)
    assert h.state is TurnState.SPEAKING and not h.line.events("clear")
    h.say("Hello?")  # its transcript: a backchannel, held, not an interruption
    await h.wait_listening(2, timeout=10)
    assert not h.session.barge_ins and not h.manager.transcript[-1].interrupted
    await h.hang_up()


async def test_silence_timer_runs_after_a_barge_in() -> None:
    h = Harness(tts=FakeTTS(ms_per_word=150), settings=fast_settings(silence_timeout_s=0.6))
    await h.start()
    h.llm.push(turn(identity_confirmed=True))
    h.say("Yes, speaking.")
    await h.wait(lambda: h.state is TurnState.SPEAKING, 3)
    await asyncio.sleep(1.0)
    await h.voice(600, wait=False)  # a cough or noise: no words follow
    await h.wait(lambda: h.session.barge_ins != [], 3)
    await h.wait(lambda: h.session._silences == 1, 5)  # the agent asks again
    await h.hang_up()


async def test_instant_reply_waits_for_the_candidate_to_finish() -> None:
    """Real call: "Total work." got an instant "Sorry, I didn't catch that" while the candidate
    was still saying "…four years". The reply now waits for quiet, so the rest merges."""
    h = Harness()
    await h.start()
    await to_screening(h)
    h.llm.push(turn("Got it. Where are you based?", fields={"interested": True},
                    evidence={"interested": "yes interested"},
                    next_question="current_location"))  # fmt: skip
    await h.voice(1500, wait=False)  # still talking…
    await asyncio.sleep(0.3)
    h.say("Total work", confidence=0.4)  # low confidence → instant template reply
    await asyncio.sleep(0.6)
    assert h.state is TurnState.THINKING and not h.line.events("clear")  # held back
    h.say("yes I am interested")  # …the rest arrives: one merged turn
    await h.wait_listening(4, timeout=8)
    assert h.session.merges == 1
    texts = [e.text for e in h.manager.transcript if e.speaker == "candidate"]
    assert texts[-1] == "Total work yes I am interested"
    assert not any(e.interrupted for e in h.manager.transcript)
    await h.hang_up()
