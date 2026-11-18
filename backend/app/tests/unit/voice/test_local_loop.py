"""VoiceLoop: finished utterances drive the agent, exactly one reply each (P4-AC2), with a fake
STT stream and the scripted LLM."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any

from app.agent.conversation_manager import ConversationManager
from app.agent.state import EndReason
from app.providers.stt.base import STTProvider, STTStats, TranscriptEvent
from app.tests.unit.agent.stub_llm import CANDIDATE, JOB, FixedClock, ScriptedLLM, turn
from app.voice.local_loop import VoiceLoop, scripted_frames

SID = "loop-1"


class FakeSTT(STTProvider):
    def __init__(self) -> None:
        self.session_id = ""
        self.stats = STTStats()
        self.audio = bytearray()
        self.queue: asyncio.Queue[TranscriptEvent] = asyncio.Queue()
        self.closed = False

    async def start_stream(
        self,
        *,
        session_id: str,
        encoding: str,
        sample_rate: int,
        channels: int = 1,
        keyterms: Sequence[str] = (),
    ) -> None:
        self.session_id = session_id

    async def send_audio(self, audio_chunk: bytes) -> None:
        self.audio.extend(audio_chunk)

    def push(self, kind: str, text: str = "", **kw: Any) -> None:
        self.queue.put_nowait(TranscriptEvent(SID, kind, text, received_at=1.0, **kw))  # type: ignore[arg-type]

    async def get_transcription(self) -> TranscriptEvent:
        return await self.queue.get()

    def sent_at(self, audio_s: float) -> float | None:
        return 0.5

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            self.push("closed")


async def no_audio() -> AsyncIterator[bytes]:
    await asyncio.Event().wait()
    yield b""


def make_loop(llm: ScriptedLLM, stt: FakeSTT, **kw: Any) -> VoiceLoop:
    manager = ConversationManager(JOB, CANDIDATE, llm, FixedClock())
    return VoiceLoop(stt, manager, session_id=SID, out=lambda _s: None, **kw)


async def wait_for(condition: Any, timeout: float = 2.0) -> None:
    async def poll() -> None:
        while not condition():  # noqa: ASYNC110 - simple poll in a test
            await asyncio.sleep(0.01)

    await asyncio.wait_for(poll(), timeout)


async def test_each_utterance_gets_exactly_one_reply() -> None:
    interested = turn(
        "Great. Where are you based?",
        fields={"interested": True},
        evidence={"interested": "I'm interested"},
        next_question="current_location",
    )
    llm = ScriptedLLM([turn(identity_confirmed=True), turn(permission_granted=True), interested])
    stt = FakeSTT()
    loop = make_loop(llm, stt)
    run = asyncio.create_task(loop.run(no_audio()))
    await wait_for(lambda: loop.agent_done.is_set())  # greeting said

    stt.push("partial", "yes")
    stt.push("final", "Yes, speaking.", confidence=0.95, endpoint=True, end_s=1.0)
    stt.push("utterance_end")  # second signal for the same utterance: ignored
    stt.push("final", "", endpoint=True)  # empty final: ignored
    await wait_for(lambda: len(loop.turns) == 1)
    stt.push("final", "Sure, go ahead.", endpoint=True)
    await wait_for(lambda: len(loop.turns) == 2)
    assert not loop.assembler.expect_short_answer  # screening question now
    stt.push("final", "Hmm.", endpoint=True)  # filler: dropped
    # two segments, completed by UtteranceEnd
    stt.push("final", "Yes,", confidence=0.9)
    stt.push("final", "I'm interested.", confidence=0.8)
    stt.push("utterance_end")
    await wait_for(lambda: len(loop.turns) == 3)
    loop.hangup()
    result = await run

    utterances = [t.utterance.text for t in loop.turns]
    assert utterances == ["Yes, speaking.", "Sure, go ahead.", "Yes, I'm interested."]
    assert len(llm.calls) == 3  # one agent turn per utterance
    assert loop.assembler.dropped_fillers == 1
    assert all(t.reply.text for t in loop.turns)
    assert loop.turns[2].utterance.confidence == 0.8
    assert loop.turns[0].stt_latency_ms == 500
    assert result.end_reason is EndReason.HANGUP
    assert stt.closed


async def test_utterances_arriving_while_busy_are_answered_in_order() -> None:
    gate = asyncio.Event()

    class SlowLLM(ScriptedLLM):
        async def structured(self, *a: Any, **kw: Any) -> Any:
            await gate.wait()
            return await super().structured(*a, **kw)

    llm = SlowLLM([turn(identity_confirmed=True), turn(permission_granted=True)])
    stt = FakeSTT()
    loop = make_loop(llm, stt)
    run = asyncio.create_task(loop.run(no_audio()))
    stt.push("final", "Yes, this is Rahul.", endpoint=True)
    stt.push("final", "Go ahead.", endpoint=True)
    await asyncio.sleep(0.05)
    gate.set()
    await wait_for(lambda: len(loop.turns) == 2)
    loop.hangup()
    await run
    assert [t.utterance.text for t in loop.turns] == ["Yes, this is Rahul.", "Go ahead."]


async def test_drop_stale_discards_what_was_said_while_the_agent_was_busy() -> None:
    # Live call 2026-11-19: candidates repeat an answer into the agent's thinking pause; the
    # repeat must not become the answer to the next question.
    gate = asyncio.Event()

    class SlowLLM(ScriptedLLM):
        async def structured(self, *a: Any, **kw: Any) -> Any:
            await gate.wait()
            return await super().structured(*a, **kw)

    llm = SlowLLM([turn(identity_confirmed=True), turn(permission_granted=True)])
    stt = FakeSTT()
    loop = make_loop(llm, stt, drop_stale=True)
    run = asyncio.create_task(loop.run(no_audio()))
    await wait_for(lambda: loop.agent_done.is_set())
    stt.push("final", "Yes, this is Rahul.", endpoint=True)
    await asyncio.sleep(0.05)  # the agent is now thinking
    stt.push("final", "Yes, this is Rahul.", endpoint=True)  # repeated into the silence
    await asyncio.sleep(0.05)
    gate.set()
    await wait_for(lambda: len(loop.turns) == 1 and not loop._utterances.qsize())
    stt.push("final", "Go ahead.", endpoint=True)
    await wait_for(lambda: len(loop.turns) == 2)
    loop.hangup()
    await run
    assert [t.utterance.text for t in loop.turns] == ["Yes, this is Rahul.", "Go ahead."]
    assert loop.dropped == ["Yes, this is Rahul."]


async def test_stt_error_ends_the_call_without_crashing() -> None:
    stt = FakeSTT()
    loop = make_loop(ScriptedLLM(), stt)
    run = asyncio.create_task(loop.run(no_audio()))
    await wait_for(lambda: loop.agent_done.is_set())
    stt.push("error", detail="transcription stream lost")
    stt.push("closed")
    result = await asyncio.wait_for(run, 2)
    assert result.end_reason is EndReason.ERROR
    assert loop.stt_error == "transcription stream lost"


async def test_silence_timeout_reprompts_then_closes() -> None:
    stt = FakeSTT()
    loop = make_loop(ScriptedLLM(), stt, silence_timeout_s=0.05)
    result = await asyncio.wait_for(loop.run(no_audio()), 2)
    assert result.end_reason is EndReason.NO_RESPONSE


async def test_scripted_frames_wait_for_the_agent() -> None:
    done = asyncio.Event()
    clip = b"\x01\x00" * 320  # 40 ms at 8 kHz
    frames = scripted_frames([clip], 8000, done, gap_s=0.0)
    first = [await anext(frames) for _ in range(3)]
    assert all(f == b"\0" * 320 for f in first)  # the agent hasn't spoken yet
    done.set()
    rest = [await anext(frames) for _ in range(4)]
    assert b"\x01\x00" * 160 in rest
    assert not done.is_set()  # cleared when the clip started
