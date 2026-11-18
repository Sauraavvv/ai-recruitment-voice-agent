"""Local voice loop: audio → Deepgram STT → UtteranceAssembler → screening agent (plan P4-T7).

    make voice-loop                       # microphone: you talk (use headphones)
    make voice-loop SPEAK=1               # also speak the agent's replies (Deepgram Aura)
    make voice-loop SCRIPT=s14_happy_path # a scenario's lines spoken by macOS `say`, turn by turn

Runs on the Mac host (microphone and `say`), with the job from tests/agent_eval/job.yaml, so no
database is needed. Uses the real Deepgram and OpenAI APIs.

Each finished utterance produces exactly one `ConversationManager.handle_utterance` call and so
one reply (P4-AC2); utterances that finish while the agent is still busy wait their turn.
Barge-in, playback cancellation and acknowledgement masking are Phase 6. Every log line carries
`session_id`.
"""

import argparse
import asyncio
import contextlib
import sys
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

import structlog
import yaml

from app.agent.conversation_manager import AgentReply, ConversationManager, ScreeningResult
from app.agent.prompts import CandidateContext, JobConfig
from app.agent.state import AskKind, EndReason, Phase
from app.providers.stt.base import STTProvider
from app.utils.log import get_logger
from app.voice.utterance import Utterance, UtteranceAssembler

logger = get_logger(__name__)

FRAME_MS = 20
SHORT_ANSWER_PHASES = {Phase.IDENTITY_CHECK, Phase.PERMISSION, Phase.CONFIRMATION}
AGENT_EVAL = Path(__file__).resolve().parents[1] / "tests" / "agent_eval"

Speak = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class TurnRecord:
    utterance: Utterance
    reply: AgentReply
    stt_latency_ms: float | None  # end of speech → utterance complete
    agent_ms: float  # utterance complete → reply ready


class VoiceLoop:
    def __init__(
        self,
        stt: STTProvider,
        manager: ConversationManager,
        *,
        session_id: str,
        encoding: str = "linear16",
        sample_rate: int = 16000,
        speak: Speak | None = None,
        silence_timeout_s: float | None = None,
        out: Callable[[str], None] = print,
    ) -> None:
        self.stt = stt
        self.manager = manager
        self.session_id = session_id
        self.encoding = encoding
        self.sample_rate = sample_rate
        self.speak = speak
        self.silence_timeout_s = silence_timeout_s
        self.out = out
        self.assembler = UtteranceAssembler(session_id)
        self.turns: list[TurnRecord] = []
        self.stt_error: str | None = None
        # Set whenever the agent has finished a reply: scripted audio waits for it.
        self.agent_done = asyncio.Event()
        self._utterances: asyncio.Queue[Utterance | None] = asyncio.Queue()

    def hangup(self) -> None:
        """End the conversation after the current turn (the candidate hung up)."""
        self._utterances.put_nowait(None)

    async def run(self, frames: AsyncIterator[bytes]) -> ScreeningResult:
        structlog.contextvars.bind_contextvars(session_id=self.session_id)
        pump: asyncio.Task[None] | None = None
        listener: asyncio.Task[None] | None = None
        reason = EndReason.HANGUP
        try:
            await self.stt.start_stream(
                session_id=self.session_id, encoding=self.encoding, sample_rate=self.sample_rate
            )
            listener = asyncio.create_task(self._listen())
            pump = asyncio.create_task(self._pump(frames))
            await self._reply(await self.manager.start())
            reason = await self._converse()
        finally:
            if pump is not None:
                pump.cancel()
                await asyncio.gather(pump, return_exceptions=True)
            await self.stt.close()
            if listener is not None:
                await asyncio.gather(listener, return_exceptions=True)
            result = await self.manager.end(reason)
            logger.info(
                "voice_loop_ended",
                end_reason=result.end_reason.value,
                turns=len(self.turns),
                stt_error=self.stt_error,
            )
            structlog.contextvars.unbind_contextvars("session_id")
        return result

    async def _converse(self) -> EndReason:
        silences = 0
        while not self.manager.state.ended:
            try:
                utterance = await asyncio.wait_for(
                    self._utterances.get(), timeout=self.silence_timeout_s
                )
            except TimeoutError:
                if self.assembler.in_speech:
                    continue  # they're mid-sentence
                silences += 1
                await self._reply(await self.manager.handle_silence(silences))
                continue
            if utterance is None:  # the stream ended
                if self.stt_error:
                    self.out(f"[transcription failed: {self.stt_error}]")
                    return EndReason.ERROR
                return EndReason.HANGUP
            silences = 0
            self.out(
                f"\n\033[1mCandidate:\033[0m {utterance.text}  \033[2m(conf "
                f"{utterance.confidence or 0:.2f}, {utterance.trigger})\033[0m"
            )
            started = time.monotonic()
            reply = await self.manager.handle_utterance(
                utterance.text, stt_confidence=utterance.confidence
            )
            agent_ms = (time.monotonic() - started) * 1000
            spoken = self.stt.sent_at(utterance.ended_at) if utterance.ended_at else None
            stt_ms = (utterance.completed_at - spoken) * 1000 if spoken else None
            self.turns.append(TurnRecord(utterance, reply, stt_ms, agent_ms))
            logger.info(
                "voice_turn",
                turn=len(self.turns),
                utterance=utterance.text,
                stt_confidence=utterance.confidence,
                reply=reply.text,
                stt_ms=None if stt_ms is None else int(stt_ms),
                agent_ms=int(agent_ms),
            )
            await self._reply(reply, f"stt {stt_ms or 0:.0f} ms + agent {agent_ms:.0f} ms")
        return self.manager.state.end_reason or EndReason.COMPLETED

    async def _reply(self, reply: AgentReply, timing: str = "") -> None:
        if reply.text:
            note = f"  \033[2m({timing})\033[0m" if timing else ""
            self.out(f"\033[1mAgent:\033[0m {reply.text}{note}")
            if self.speak is not None:
                await self.speak(reply.text)
        # "Mm-hmm" is an answer to a yes/no question, filler otherwise
        self.assembler.expect_short_answer = (
            reply.phase in SHORT_ANSWER_PHASES or reply.ask_kind is AskKind.CONFIRM
        )
        self.agent_done.set()

    async def _pump(self, frames: AsyncIterator[bytes]) -> None:
        async for frame in frames:
            await self.stt.send_audio(frame)

    async def _listen(self) -> None:
        try:
            async for event in self.stt.events():
                if event.kind == "error":
                    self.stt_error = event.detail or "error"
                utterance = self.assembler.feed(event)
                if utterance is not None:
                    await self._utterances.put(utterance)
        finally:
            await self._utterances.put(None)


# --- audio sources -----------------------------------------------------------------------------


async def mic_frames(sample_rate: int) -> AsyncIterator[bytes]:
    """20 ms linear16 frames from the default microphone (sounddevice / PortAudio)."""
    import sounddevice as sd

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def callback(data: bytes, _frames: int, _time: object, status: object) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, bytes(data))

    with sd.RawInputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
        blocksize=sample_rate * FRAME_MS // 1000,
        callback=callback,
    ):
        while True:
            yield await queue.get()


async def scripted_frames(
    clips: list[bytes], sample_rate: int, agent_done: asyncio.Event, *, gap_s: float = 0.6
) -> AsyncIterator[bytes]:
    """A phone line: continuous 20 ms frames, silence except when a clip is playing. Each clip
    starts `gap_s` after the agent finishes its reply; after the last one, silence."""
    step = sample_rate * FRAME_MS // 1000 * 2
    silence = b"\0" * step
    pending = list(clips)
    current = b""
    wait_until: float | None = None
    started = time.monotonic()
    i = 0
    while True:
        if not current and pending and agent_done.is_set():
            if wait_until is None:
                wait_until = time.monotonic() + gap_s
            elif time.monotonic() >= wait_until:
                agent_done.clear()
                current, wait_until = pending.pop(0), None
        if current:
            frame, current = current[:step], current[step:]
            yield frame.ljust(step, b"\0")
        else:
            yield silence
        i += 1
        await asyncio.sleep(max(0.0, started + i * FRAME_MS / 1000 - time.monotonic()))


def say_clips(lines: list[str], voice: str, sample_rate: int) -> list[bytes]:
    """Lines spoken by macOS `say`, as linear16 at `sample_rate` (8 kHz = phone band)."""
    from app.scripts.stt_tools import prepare, say

    return [prepare(say(line, voice), 16000, sample_rate) for line in lines]


def make_speaker(settings: object) -> Speak:
    """Speak replies with Deepgram Aura through the default output (headphones!)."""
    import numpy as np
    import sounddevice as sd

    from app.config import Settings
    from app.providers.tts import create_tts_provider

    assert isinstance(settings, Settings)
    tts = create_tts_provider(
        settings.model_copy(update={"tts_provider": "deepgram", "tts_fallback": False})
    )
    ready = asyncio.Lock()
    initialized = False

    async def speak(text: str) -> None:
        nonlocal initialized
        async with ready:
            if not initialized:
                await tts.initialize()
                initialized = True
        pcm = b"".join([c.pcm async for c in tts.stream(text)])
        audio = np.frombuffer(pcm, dtype="<i2")
        await asyncio.to_thread(lambda: (sd.play(audio, tts.sample_rate), sd.wait()))

    return speak


# --- CLI ---------------------------------------------------------------------------------------


async def main_async(args: argparse.Namespace) -> int:
    from app.config import get_settings
    from app.providers.llm import create_llm_provider
    from app.providers.stt import create_stt_provider

    settings = get_settings()
    job = JobConfig.from_dict(yaml.safe_load(Path(args.job_file).read_text()))
    name = args.name
    lines: list[str] = []
    if args.script:
        path = Path(args.script)
        if not path.exists():
            path = AGENT_EVAL / "scenarios" / f"{args.script}.yaml"
        scenario = yaml.safe_load(path.read_text())
        lines = [t["say"] for t in scenario["turns"]]
        name = scenario.get("candidate", {}).get("name", name)

    llm = create_llm_provider(settings)
    manager = ConversationManager(
        job, CandidateContext(name=name), llm, timeout_s=settings.openai_timeout_s
    )
    session_id = f"local-{uuid.uuid4().hex[:8]}"
    stt = create_stt_provider(settings, keyterms=[job.company_name])
    loop = VoiceLoop(
        stt,
        manager,
        session_id=session_id,
        sample_rate=args.rate,
        speak=make_speaker(settings) if args.speak else None,
        silence_timeout_s=args.silence_timeout,
    )
    print(
        f"session {session_id} | {job.job_title} at {job.company_name} | "
        f"{settings.deepgram_stt_model}/{settings.deepgram_stt_language} {args.rate} Hz"
    )
    if lines:
        frames = scripted_frames(
            say_clips(lines, args.voice, args.rate), args.rate, loop.agent_done
        )
    else:
        print("Listening… speak after the agent (Ctrl+C to hang up)")
        frames = mic_frames(args.rate)
    try:
        if lines:
            # hang up a few seconds after the last line was answered
            async def stop_when_done() -> None:
                while len(loop.turns) < len(lines) and not manager.state.ended:
                    await asyncio.sleep(0.2)

            runner = asyncio.create_task(loop.run(frames))
            await asyncio.wait(
                {runner, asyncio.create_task(stop_when_done())}, return_when=asyncio.FIRST_COMPLETED
            )
            if not runner.done():
                await asyncio.sleep(1)
                loop.hangup()
            result = await runner
        else:
            result = await loop.run(frames)
    except (KeyboardInterrupt, asyncio.CancelledError):
        result = None
    finally:
        await llm.aclose()

    stt_ms = sorted(t.stt_latency_ms for t in loop.turns if t.stt_latency_ms is not None)
    print(f"\n--- {len(loop.turns)} utterances → {len(loop.turns)} replies ---")
    if stt_ms:
        print(f"stt latency median {stt_ms[len(stt_ms) // 2]:.0f} ms, max {stt_ms[-1]:.0f} ms")
    if result is not None:
        print(f"end_reason={result.end_reason.value} status={result.screening_status.value}")
        for key, value in result.collected_data.items():
            print(f"  {key}: {value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    from app.utils.log import configure_logging

    parser = argparse.ArgumentParser(description="Talk to the screening agent through Deepgram")
    parser.add_argument("--script", help="scenario name or YAML, spoken by macOS `say`")
    parser.add_argument("--voice", default="Rishi", help="`say` voice for --script")
    parser.add_argument("--rate", type=int, default=16000, choices=(8000, 16000))
    parser.add_argument("--speak", action="store_true", help="speak replies (headphones)")
    parser.add_argument("--silence-timeout", type=float, default=None)
    parser.add_argument("--job-file", default=str(AGENT_EVAL / "job.yaml"))
    parser.add_argument("--name", default="Test Candidate")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    configure_logging("INFO" if args.verbose else "WARNING")
    with contextlib.suppress(KeyboardInterrupt):
        return asyncio.run(main_async(args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
