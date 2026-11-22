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
