"""A whole screening call without a phone (phase-06 §7.1 harness with real providers).

    make voice-sim                          # scenario s14_happy_path, voice Rishi
    make voice-sim SCRIPT=s02_two_fields VOICE=Tara

Runs `CallSession` exactly as a real call does: real Deepgram STT, OpenAI and the Deepgram voice
(Aura; no Kitten fallback on the host). The candidate is macOS `say` reading the scenario's lines
at phone quality (8 kHz, μ-law round trip, a faint line-noise floor). A loopback "phone line"
paces our audio like Exotel and echoes marks. Nothing is written to the database.

Prints the transcript, the outcome and the latency table, and writes a stereo WAV (left: the
candidate, right: the agent) to artifacts/voice-sim/ to listen to. Costs a few cents per run.
Host only (macOS `say`).

    make voice-sim ENGINE=realtime          # the same call on OpenAI Realtime (trial engine)
"""

import argparse
import asyncio
import contextlib
import json
import sys
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from app.agent.conversation_manager import ConversationManager
from app.agent.prompts import CandidateContext, JobConfig
from app.config import get_settings
from app.providers.llm import create_llm_provider
from app.providers.stt import create_stt_provider
from app.providers.tts import create_tts_provider
from app.voice.audio_processor import InboundQueue
from app.voice.local_loop import AGENT_EVAL, say_clips
from app.voice.pipeline import CallContext, CallSession, SessionOutcome
from app.voice.playback import PLAYOUT_LAG_MS, AudioSender, MarkTracker
from app.voice.turn_manager import TurnState
from app.voice.websocket_handler import make_vad

RATE = 8000
FRAME = RATE * 2 // 50  # 20 ms
OUT_DIR = Path("artifacts/voice-sim")


class LoopbackLine:
    """Stands in for Exotel: keeps our outgoing audio on a timeline and echoes each mark about
    PLAYOUT_LAG_MS after the audio before it has played."""

    def __init__(self, started: float) -> None:
        self.started = started
        self.sender: AudioSender | None = None
        self.marks: MarkTracker | None = None
        self.agent_audio: list[tuple[float, bytes]] = []
        self.clears = 0
        self._pending: set[asyncio.Task[None]] = set()

    async def send_text(self, data: str) -> None:
        import base64

        message = json.loads(data)
        kind = message["event"]
        if kind == "media":
            assert self.sender is not None
            at = max(time.monotonic(), self.sender.playhead) - self.started
            self.agent_audio.append((at, base64.b64decode(message["media"]["payload"])))
        elif kind == "mark":
            task = asyncio.create_task(self._echo(message["mark"]["name"]))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)
        elif kind == "clear":
            self.clears += 1
            for task in list(self._pending):
                task.cancel()

    async def _echo(self, name: str) -> None:
        assert self.sender is not None and self.marks is not None
        await asyncio.sleep(self.sender.buffered_s + PLAYOUT_LAG_MS / 1000)
        self.marks.note_returned(name)


def line_noise(n: int, rng: np.random.Generator) -> bytes:
    return rng.normal(0, 25, n // 2).astype("<i2").tobytes()  # about -62 dBFS


def load_scenario(script: str) -> tuple[list[str], str, JobConfig]:
    path = Path(script)
    if not path.exists():
        path = AGENT_EVAL / "scenarios" / f"{script}.yaml"
    scenario = yaml.safe_load(path.read_text())
    lines = [t["say"] for t in scenario["turns"]]
    job = JobConfig.from_dict(yaml.safe_load((AGENT_EVAL / "job.yaml").read_text()))
    return lines, scenario.get("candidate", {}).get("name", "Test Candidate"), job


async def run(
    args: argparse.Namespace, lines: list[str], name: str, job: JobConfig, clips: list[bytes]
) -> int:
    settings = get_settings().model_copy(update={"tts_fallback": False})

    tts = create_tts_provider(settings)
    await tts.initialize()
    llm = create_llm_provider(settings)
    attempt_id = f"sim-{int(time.time())}"
    started = time.monotonic()
    line = LoopbackLine(started)
    sender = AudioSender(
        line,
        "sim-stream",
        encoding="slin",
        sample_rate=RATE,
        frame_bytes=settings.telephony_frame_bytes,
        send_ahead_ms=settings.telephony_send_ahead_ms,
        session_id=attempt_id,
    )
    marks = MarkTracker()
    line.sender, line.marks = sender, marks
    inbound = InboundQueue(RATE * 2 * 2)
    ctx = CallContext(
        attempt_id=attempt_id,
        job=job,
        candidate=CandidateContext(name=name),
        keyterms=[k for k in (job.company_name, job.location) if k],
    )
    session = CallSession(
        ctx,
        settings=settings,
        sender=sender,
        inbound=inbound,
        marks=marks,
        stt=create_stt_provider(settings, keyterms=ctx.keyterms),
        tts=tts,
        manager=ConversationManager(job, ctx.candidate, llm, timeout_s=settings.openai_timeout_s),
        vad=make_vad(settings),
    )
    candidate_audio: list[tuple[float, bytes]] = []

    async def candidate() -> None:
        """Speak the next line `gap_s` after each agent turn has finished playing."""
        rng = np.random.default_rng(7)
        pending = list(clips)
        current = b""
        ready_at: float | None = None
        replies_seen = 0
        i = 0
        while True:
            agent_lines = sum(1 for e in session.manager.transcript if e.speaker == "assistant")
            listening = session.turns.state is TurnState.LISTENING
            if not current and pending and listening and agent_lines > replies_seen:
                if ready_at is None:
                    ready_at = time.monotonic() + args.gap
                elif time.monotonic() >= ready_at:
                    current, ready_at = pending.pop(0), None
                    replies_seen = agent_lines
                    candidate_audio.append((time.monotonic() - started, current))
            if current:
                frame, current = current[:FRAME], current[FRAME:]
                frame = frame.ljust(FRAME, b"\0")
                noisy = np.frombuffer(frame, "<i2").astype(np.int32) + np.frombuffer(
                    line_noise(FRAME, rng), "<i2"
                )
                inbound.put(np.clip(noisy, -32768, 32767).astype("<i2").tobytes())
            else:
                inbound.put(line_noise(FRAME, rng))
            i += 1
            await asyncio.sleep(max(0.0, started + i * 0.02 - time.monotonic()))

    feeder = asyncio.create_task(candidate())
    runner = asyncio.create_task(session.run())
    try:
        while not runner.done():
            if not clips_left(session, len(lines)) and session.turns.state is TurnState.LISTENING:
                await asyncio.sleep(args.gap + 1.5)
                if session.turns.state is TurnState.LISTENING:
                    session.caller_hung_up("stop")
                break
            await asyncio.sleep(0.2)
        outcome: SessionOutcome = await asyncio.wait_for(runner, 60)
    finally:
        feeder.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await feeder
        await llm.aclose()
        await tts.close()

    report(outcome)
    wav = await asyncio.to_thread(write_wav, attempt_id, candidate_audio, line.agent_audio)
    print(f"\nlisten: {wav}")
    return 0


async def run_realtime(
    args: argparse.Namespace, lines: list[str], name: str, job: JobConfig, clips: list[bytes]
) -> int:
    """The scenario on the Realtime engine: the candidate answers once the agent has finished
    speaking (a new agent line, nothing generating or playing)."""
    from app.providers.realtime import OpenAIRealtimeClient
    from app.voice.realtime_session import RealtimeCallSession

    settings = get_settings().model_copy(update={"voice_engine": "realtime"})
    assert settings.openai_api_key is not None, "OPENAI_API_KEY is not set"
    attempt_id = f"sim-rt-{int(time.time())}"
    started = time.monotonic()
    line = LoopbackLine(started)
    sender = AudioSender(
        line,
        "sim-stream",
        encoding="slin",
        sample_rate=RATE,
        frame_bytes=settings.telephony_frame_bytes,
        send_ahead_ms=settings.telephony_send_ahead_ms,
        session_id=attempt_id,
    )
    marks = MarkTracker()
    line.sender, line.marks = sender, marks
    inbound = InboundQueue(RATE * 2 * 2)
    ctx = CallContext(attempt_id=attempt_id, job=job, candidate=CandidateContext(name=name))
    client = OpenAIRealtimeClient(
        settings.openai_api_key.get_secret_value(), settings.openai_realtime_model
    )
    session = RealtimeCallSession(
        ctx, settings=settings, sender=sender, inbound=inbound, marks=marks, client=client
    )
    candidate_audio: list[tuple[float, bytes]] = []
    pending = list(clips)

    async def candidate() -> None:
        rng = np.random.default_rng(7)
        current = b""
        ready_at: float | None = None
        replies_seen = 0
        i = 0
        while True:
            agent_lines = sum(
                1 for e in session.transcript if e["speaker"] == "assistant" and e["text"]
            )
            if not current and pending and not session.speaking and agent_lines > replies_seen:
                if ready_at is None:
                    ready_at = time.monotonic() + args.gap
                elif time.monotonic() >= ready_at:
                    current, ready_at = pending.pop(0), None
                    replies_seen = agent_lines
                    candidate_audio.append((time.monotonic() - started, current))
            elif session.speaking:
                ready_at = None
            if current:
                frame, current = current[:FRAME], current[FRAME:]
                frame = frame.ljust(FRAME, b"\0")
                noisy = np.frombuffer(frame, "<i2").astype(np.int32) + np.frombuffer(
                    line_noise(FRAME, rng), "<i2"
                )
                inbound.put(np.clip(noisy, -32768, 32767).astype("<i2").tobytes())
            else:
                inbound.put(line_noise(FRAME, rng))
            i += 1
            await asyncio.sleep(max(0.0, started + i * 0.02 - time.monotonic()))

    feeder = asyncio.create_task(candidate())
    runner = asyncio.create_task(session.run())
    try:
        while not runner.done():
            if not pending and not session.speaking:
                await asyncio.sleep(args.gap + 8)  # time for the last reply and the goodbye
                if not runner.done() and not session.speaking:
                    session.caller_hung_up("stop")
                    break
            await asyncio.sleep(0.2)
        outcome: SessionOutcome = await asyncio.wait_for(runner, 60)
    finally:
        feeder.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await feeder

    print("\n--- transcript (realtime) ---")
    for e in outcome.result.transcript:
        flag = " [interrupted]" if e.get("interrupted") else ""
        print(f"{e['speaker']:>9}: {e['text']}{flag}")
    print(
        f"\nend_reason={outcome.end_reason.value} "
        f"status={outcome.result.screening_status.value} ended_by={outcome.ended_by}"
    )
    for key, value in outcome.result.collected_data.items():
        print(f"  {key:<24} {value!r}")
    stats = outcome.stats
    firsts = sorted(m["first_sound_ms"] for m in outcome.metrics if m.get("first_sound_ms"))
    if firsts:
        p50 = firsts[len(firsts) // 2]
        p95 = firsts[min(len(firsts) - 1, round(0.95 * (len(firsts) - 1)))]
        print(
            f"\nfirst sound after the candidate stops: p50 {p50} ms  p95 {p95} ms (n={len(firsts)})"
        )
    print(f"usage: {stats['usage']}")
    print(f"estimated cost: ${stats['estimated_cost_usd']} for {stats['duration_s']} s")
    print(f"tool calls: {stats['tool_calls']}  barge-ins: {stats['barge_ins']}")
    wav = await asyncio.to_thread(write_wav, attempt_id, candidate_audio, line.agent_audio)
    print(f"\nlisten: {wav}")
    return 0


def clips_left(session: CallSession, total: int) -> bool:
    said = sum(1 for e in session.manager.transcript if e.speaker == "candidate")
    return said + session.merges < total


def report(outcome: SessionOutcome) -> None:
    print("\n--- transcript ---")
    for e in outcome.result.transcript:
        flag = " [interrupted]" if e.get("interrupted") else ""
        ack = f" (ack: {e['ack']})" if e.get("ack") else ""
        print(f"{e['speaker']:>9}: {e['text']}{flag}{ack}")
    print(
        f"\nend_reason={outcome.end_reason.value} "
        f"status={outcome.result.screening_status.value} ended_by={outcome.ended_by}"
    )
    for key, value in outcome.result.collected_data.items():
        print(f"  {key:<24} {value!r}")
    print("\n--- latency per turn (ms) ---")
    cols = ("turn", "ack", "stt_ms", "llm_ms", "tts_ms", "send_ms", "ack_ms", "total_ms", "merged")
    print("  ".join(f"{c:>8}" for c in cols))
    for m in outcome.metrics:
        print("  ".join(f"{'-' if m.get(c) is None else str(m.get(c)):>8}" for c in cols))
    for key in ("first_sound_ms", "total_ms", "stt_ms", "llm_ms", "tts_ms"):
        values = sorted(v for m in outcome.metrics if isinstance(v := m.get(key), int))
        if values:
            p50 = values[len(values) // 2]
            p95 = values[min(len(values) - 1, round(0.95 * (len(values) - 1)))]
            print(f"  {key:<15} p50 {p50:6d}  p95 {p95:6d}  (n={len(values)})")
    stats: dict[str, Any] = outcome.stats
    print({k: stats[k] for k in ("merges", "barge_ins", "backchannels_ignored", "max_loop_lag_ms")})


def write_wav(
    attempt_id: str, candidate: list[tuple[float, bytes]], agent: list[tuple[float, bytes]]
) -> Path:
    def track(parts: list[tuple[float, bytes]]) -> np.ndarray:
        end = max((at + len(b) / 2 / RATE for at, b in parts), default=0.0)
        out = np.zeros(int(end * RATE) + 1, dtype=np.int16)
        for at, data in parts:
            samples = np.frombuffer(data, "<i2")
            start = int(at * RATE)
            out[start : start + len(samples)] = samples[: len(out) - start]
        return out

    left, right = track(candidate), track(agent)
    n = max(len(left), len(right))
    stereo = np.zeros((n, 2), dtype=np.int16)
    stereo[: len(left), 0], stereo[: len(right), 1] = left, right
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{attempt_id}.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(stereo.tobytes())
    return path


def main() -> int:
    from app.utils.log import configure_logging

    parser = argparse.ArgumentParser(description="Simulated screening call with real providers")
    parser.add_argument("--script", default="s14_happy_path")
    parser.add_argument("--voice", default="Rishi")
    parser.add_argument("--gap", type=float, default=0.6, help="pause before each answer (s)")
    parser.add_argument("--engine", choices=["pipeline", "realtime"], default="pipeline")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging("INFO" if args.verbose else "WARNING")
    lines, name, job = load_scenario(args.script)
    print(f"Rendering {len(lines)} lines with `say -v {args.voice}`…")
    clips = say_clips(lines, args.voice, RATE)
    if args.engine == "realtime":
        return asyncio.run(run_realtime(args, lines, name, job, clips))
    return asyncio.run(run(args, lines, name, job, clips))


if __name__ == "__main__":
    sys.exit(main())
