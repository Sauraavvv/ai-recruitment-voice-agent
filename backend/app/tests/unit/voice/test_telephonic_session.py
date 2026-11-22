"""The voice pipeline runs the telephonic round agent unchanged (phase-11 step 6b): greeting,
turns, acknowledgements and the outcome, with fake STT, TTS and phone line."""

from app.agent.state import EndReason
from app.agent.telephonic_manager import TelephonicManager, TelephonicResult
from app.database.models import CallEndReason
from app.tests.unit.agent.stub_llm import CANDIDATE, JOB, FixedClock, ScriptedLLM
from app.tests.unit.agent.test_telephonic_manager import CTX, t
from app.tests.unit.voice.session_harness import Harness
from app.voice.pipeline import CallContext, CallSession
from app.voice.turn_manager import TurnState


def telephonic(h: Harness, llm: ScriptedLLM) -> TelephonicManager:
    """Swap the harness's screening session for a telephonic round one (same fakes)."""
    manager = TelephonicManager(CTX, CANDIDATE, llm, FixedClock())
    session: CallSession[TelephonicResult] = CallSession(
        CallContext(attempt_id="attempt-0001", job=JOB, candidate=CANDIDATE, telephonic=CTX),
        settings=h.settings,
        sender=h.sender,
        inbound=h.inbound,
        marks=h.marks,
        stt=h.stt,
        tts=h.tts,
        manager=manager,
        vad=h.vad,
    )
    h.session = session  # type: ignore[assignment]
    return manager


async def test_the_pipeline_runs_the_round() -> None:
    h = Harness()
    llm = ScriptedLLM()
    manager = telephonic(h, llm)

    def listening_after(lines: int) -> bool:
        said = sum(1 for e in manager.transcript if e.speaker == "assistant")
        return h.state is TurnState.LISTENING and said >= lines

    await h.start()
    assert h.spoken()[0] == "Hello, am I speaking with Rahul Sharma?"
    llm.push(t("answer", identity_confirmed=True))
    h.say("Yes, speaking.")
    await h.wait(lambda: listening_after(2))
    llm.push(t("answer", permission_granted=True))
    h.say("Sure.")
    await h.wait(lambda: listening_after(3))
    assert any("First, tell me about the last product you sold." in s for s in h.spoken())

    llm.push(t("answer"))
    h.say("A billing app for grocery stores.")
    await h.wait(lambda: listening_after(4))
    # "Thanks." is dropped when an acknowledgement was already played
    assert h.spoken()[-1] == "Next, how do you find new customers?"

    outcome = await h.hang_up()
    result = outcome.result
    assert isinstance(result, TelephonicResult)
    assert outcome.end_reason is CallEndReason.CANDIDATE_HANGUP
    assert result.end_reason is EndReason.HANGUP and result.status == "partial"
    assert [a["status"] for a in result.answers] == ["answered", "not_asked", "not_asked"]
    assert result.answers[0]["answer"] == "A billing app for grocery stores."


def test_an_answer_stopping_mid_sentence_gets_more_time() -> None:
    from app.tests.unit.voice.session_harness import fast_settings
    from app.voice.pipeline import answer_gap_s

    settings = fast_settings(answer_gap_s=1.8, answer_unfinished_extra_s=1.2)
    assert answer_gap_s("I built a RAG system using LangChain.", settings) == 1.8
    assert answer_gap_s("in which I choose the document of", settings) == 3.0
    assert answer_gap_s("the humans that are generating the blogs using", settings) == 3.0
    # Screening calls: as before
    assert answer_gap_s("the document of", fast_settings()) == 0.7


async def test_a_thinking_pause_mid_answer_is_not_the_end_of_the_answer() -> None:
    """Real round call: "…I choose the document of" + a pause → the agent moved on, and "…related
    to my company's" became the next question's answer. Now it waits and merges."""
    import asyncio

    from app.providers.tts import ACKNOWLEDGEMENTS
    from app.tests.unit.voice.session_harness import fast_settings

    settings = fast_settings(answer_gap_s=0.9, answer_unfinished_extra_s=0.9, answer_max_wait_s=6.0)
    h = Harness(settings=settings)
    llm = ScriptedLLM()
    manager = telephonic(h, llm)

    def listening_after(lines: int) -> bool:
        said = sum(1 for e in manager.transcript if e.speaker == "assistant")
        return h.state is TurnState.LISTENING and said >= lines

    await h.start()
    llm.push(t("answer", identity_confirmed=True))
    await h.voice(300)
    h.say("Yes, speaking.")
    await h.wait(lambda: listening_after(2))
    llm.push(t("answer", permission_granted=True))
    await h.voice(300)
    h.say("Sure.")
    await h.wait(lambda: listening_after(3))
    spoken_before = len(h.spoken())

    llm.push(t("answer"), t("answer"))  # the first run is cancelled by the merge
    await h.voice(400)
    h.say("I sold a billing app in which I chose the plan of")
    await asyncio.sleep(1.3)  # thinking: longer than the old 0.7 s, shorter than 1.8 s
    assert h.state is TurnState.THINKING and len(h.spoken()) == spoken_before
    await h.voice(400)
    h.say("each grocery store.")
    await h.wait(lambda: listening_after(4), timeout=8)

    assert h.session.merges == 1
    said = [e.text for e in manager.transcript if e.speaker == "candidate"]
    assert said[-1] == "I sold a billing app in which I chose the plan of each grocery store."
    new = h.spoken()[spoken_before:]
    assert not any(s in ACKNOWLEDGEMENTS for s in new)  # no "Thank you." into the pause
    assert new[-1].endswith("how do you find new customers?")
    assert not any(e.interrupted for e in manager.transcript)
    await h.hang_up()
