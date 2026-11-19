"""Phase 6 building blocks: VAD, barge-in rules, the turn table, playback (phase-06 §7.1)."""

import asyncio
import math

import numpy as np
import pytest

from app.tests.unit.voice.session_harness import FakeLine, FakeTTS
from app.voice.audio_processor import InboundFramer, InboundQueue, decode_media
from app.voice.interruption import BargeInPolicy, heard_portion, is_backchannel
from app.voice.pipeline import strip_leading_ack
from app.voice.playback import (
    PLAYOUT_LAG_MS,
    AudioSender,
    CrossSessionAudioError,
    MarkTracker,
    Player,
    split_for_prefetch,
)
from app.voice.session_registry import SessionExistsError, SessionRegistry
from app.voice.turn_manager import ANY, TABLE, Act, TurnEvent, TurnManager, TurnState
from app.voice.vad import SpeechDetector, frame_dbfs, webrtc_classifier

S, E, A = TurnState, TurnEvent, Act
LOUD = (np.random.default_rng(0).normal(0, 6000, 160)).astype("<i2").tobytes()
FAINT = (np.random.default_rng(0).normal(0, 60, 160)).astype("<i2").tobytes()
QUIET = b"\0" * 320


# --- VAD -----------------------------------------------------------------------------------


def detector(min_dbfs: float = -45.0, echo_margin_db: float = 6.0) -> SpeechDetector:
    return SpeechDetector(
        lambda _f: True,
        start_ms=60,
        end_silence_ms=200,
        min_dbfs=min_dbfs,
        echo_margin_db=echo_margin_db,
    )


def feed(vad: SpeechDetector, frames: list[bytes], t0: float = 100.0) -> list[tuple[str, float]]:
    events: list[tuple[str, float]] = []
    for i, frame in enumerate(frames):
        e = vad.process(frame, t0 + (i + 1) * 0.02)
        if e:
            events.append((e.kind, round(e.at, 3)))
    return events


def test_frame_level() -> None:
    assert frame_dbfs(QUIET) == -math.inf
    assert frame_dbfs(LOUD) > -20 > frame_dbfs(FAINT) > -60


def test_speech_start_and_end_of_turn() -> None:
    vad = detector()
    events = feed(vad, [QUIET] * 5 + [LOUD] * 10 + [QUIET] * 12)
    # starts after 60 ms of voice (3 frames); ends 200 ms after the last voiced frame
    assert events == [("speech_start", 100.1), ("speech_end", 100.3)]
    assert vad.stats.speech_runs == 1 and not vad.in_speech


def test_short_click_does_not_start_speech() -> None:
    vad = detector()
    assert feed(vad, [LOUD, QUIET, LOUD, QUIET, QUIET] * 4) == []


def test_pause_shorter_than_end_silence_keeps_the_turn() -> None:
    vad = detector()
    events = feed(vad, [LOUD] * 5 + [QUIET] * 5 + [LOUD] * 5 + [QUIET] * 11)
    assert [k for k, _ in events] == ["speech_start", "speech_end"]


def test_echo_margin_raises_the_gate() -> None:
    mid = (np.random.default_rng(0).normal(0, 300, 160)).astype("<i2").tobytes()  # ~ -40 dBFS
    vad = detector(min_dbfs=-45, echo_margin_db=10)
    assert vad.is_voiced(mid)
    vad.echo = True
    assert not vad.is_voiced(mid) and vad.stats.gated_by_echo == 1
    assert vad.is_voiced(LOUD)


def test_run_ms() -> None:
    vad = detector()
    feed(vad, [LOUD] * 20)
    assert vad.run_ms(100.4) == pytest.approx(400, abs=1)


def test_webrtcvad_is_installed_and_rejects_silence() -> None:
    classify = webrtc_classifier(8000, 2)
    assert classify is not None, "webrtcvad-wheels missing"
    assert classify(QUIET) is False


# --- inbound audio ---------------------------------------------------------------------------


def test_inbound_framer_carries_remainder() -> None:
    framer = InboundFramer(8000)
    assert framer.push(b"\1" * 500) == [b"\1" * 320]
    frames = framer.push(b"\2" * 460)
    assert len(frames) == 2 and frames[0] == b"\1" * 180 + b"\2" * 140


def test_decode_media() -> None:
    import base64

    assert decode_media(base64.b64encode(b"\1\0").decode(), encoding="slin") == b"\1\0"


async def test_inbound_queue_close() -> None:
    q = InboundQueue(1000)
    q.put(b"ab")
    q.close()
    assert await q.get() == b"ab"
    with pytest.raises(EOFError):
        await q.get()


# --- barge-in ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ms", "preview", "interrupt"),
    [
        (100, "wait wait", False),  # too short to be anything
        (350, "", False),  # nothing heard yet
        (350, "okay", False),  # a backchannel
        (350, "haan ji", False),
        (350, "no actually it's", True),  # words: interrupt
        (650, "", True),  # long speech, whatever STT says
        (650, "yes", True),
    ],
)
def test_barge_in_policy(ms: float, preview: str, interrupt: bool) -> None:
    assert BargeInPolicy(min_ms=300, backchannel_max_ms=600).check(ms, preview).interrupt is (
        interrupt
    )


def test_backchannels() -> None:
    assert is_backchannel("Yeah.") and is_backchannel("mm-hmm okay") and is_backchannel("")
    assert not is_backchannel("yes I am") and not is_backchannel("fifteen lakhs")
    assert not is_backchannel("yes yes okay sure")  # four words


def test_heard_portion() -> None:
    text = "one two three four five six seven eight nine ten"
    assert heard_portion(text, 500, 1000) == "one two three four five"
    assert heard_portion(text, 0, 1000) == "" and heard_portion(text, 5000, 1000) == text


def test_strip_leading_ack() -> None:
    assert strip_leading_ack("Got it. What is your notice period?") == (
        "What is your notice period?"
    )
    assert strip_leading_ack("Okay! where are you based?") == "Where are you based?"
    assert strip_leading_ack("Thank you, Rahul. Next one.") == "Thank you, Rahul. Next one."
    assert strip_leading_ack("Got it.") == "Got it."
    assert strip_leading_ack("Sure, we'll call you back.") == "We'll call you back."
    assert strip_leading_ack("Okay, no problem. Next?") == "No problem. Next?"
    assert strip_leading_ack("Great, thank you. It's a role.") == "Great, thank you. It's a role."


# --- turn table ------------------------------------------------------------------------------

CASES = [
    (S.STARTING, E.STREAM_STARTED, S.THINKING, (A.WAIT_HELLO_THEN_GREET,)),
    (S.LISTENING, E.UTTERANCE, S.THINKING, (A.STOP_SILENCE_TIMER, A.RUN_AGENT, A.PLAY_ACK)),
    (S.LISTENING, E.SILENCE, S.THINKING, (A.RUN_SILENCE_PROMPT,)),
    (S.THINKING, E.UTTERANCE, S.THINKING, (A.CANCEL_AGENT, A.MERGE_AND_RERUN)),
    (S.THINKING, E.AGENT_REPLY, S.THINKING, (A.SPEAK_REPLY,)),
    (S.THINKING, E.END_REPLY, S.ENDING, (A.SPEAK_REPLY,)),
    (S.THINKING, E.FIRST_AUDIO, S.SPEAKING, ()),
    (S.SPEAKING, E.PLAYBACK_DONE, S.LISTENING, (A.START_SILENCE_TIMER, A.RELEASE_BACKCHANNEL)),
    (S.SPEAKING, E.BARGE_IN, S.LISTENING, (A.STOP_PLAYBACK, A.START_SILENCE_TIMER)),
    (S.SPEAKING, E.UTTERANCE, S.LISTENING, (A.STOP_PLAYBACK, A.REDISPATCH)),
    (S.SPEAKING, E.BACKCHANNEL, S.SPEAKING, (A.HOLD_BACKCHANNEL,)),
    (S.ENDING, E.PLAYBACK_DONE, S.ENDED, (A.HANG_UP,)),
    (S.ENDING, E.BARGE_IN, S.ENDING, (A.IGNORE,)),  # the closing line plays to the end
    (S.ENDING, E.UTTERANCE, S.ENDING, (A.IGNORE,)),
    (S.ENDING, E.FAILURE, S.ENDING, (A.IGNORE,)),
    (S.LISTENING, E.BARGE_IN, S.LISTENING, (A.IGNORE,)),  # nothing to interrupt
    (S.SPEAKING, E.CALLER_HANGUP, S.ENDED, (A.FINISH,)),
    (S.ENDING, E.CALLER_HANGUP, S.ENDED, (A.FINISH,)),
    (S.THINKING, E.FAILURE, S.ENDING, (A.CANCEL_AGENT, A.STOP_SILENCE_TIMER, A.PLAY_APOLOGY)),
    (S.SPEAKING, E.TIME_UP, S.ENDING, (A.CANCEL_AGENT, A.STOP_SILENCE_TIMER, A.SPEAK_TIME_UP)),
    (S.ENDED, E.UTTERANCE, S.ENDED, (A.IGNORE,)),
]


@pytest.mark.parametrize(("state", "event", "after", "acts"), CASES)
def test_turn_table(
    state: TurnState, event: TurnEvent, after: TurnState, acts: tuple[Act, ...]
) -> None:
    tm = TurnManager(state)
    assert tm.handle(event) == acts
    assert tm.state is after


def test_every_action_has_a_handler() -> None:
    from app.voice.pipeline import CallSession

    used = {a for _s, acts in TABLE.values() for a in acts} | {
        a for _s, acts in ANY.values() for a in acts
    }
    for act in used | {Act.IGNORE}:
        assert hasattr(CallSession, f"_act_{act.value}"), act


# --- playback ------------------------------------------------------------------------------


def player(session_id: str = "s1") -> tuple[Player, FakeLine, AudioSender, MarkTracker]:
    line = FakeLine()
    sender = AudioSender(
        line,
        "sid",
        encoding="slin",
        sample_rate=8000,
        frame_bytes=640,
        send_ahead_ms=100,
        session_id=session_id,
    )
    marks = MarkTracker()
    line.sender, line.marks = sender, marks
    return (
        Player(sender, FakeTTS(ms_per_word=50), marks, session_id=session_id),
        line,
        sender,
        marks,
    )


async def test_speak_sends_frames_then_mark_and_waits_for_it() -> None:
    p, line, _sender, marks = player()
    result = await p.speak("one two three four", label="reply-x")
    media = line.events("media")
    assert media and all(m["stream_sid"] == "sid" for m in media)
    assert line.sent[-1] == {"event": "mark", "stream_sid": "sid", "mark": {"name": "reply-x"}}
    assert result.mark_returned and result.first_frame_at and result.first_chunk_at
    assert result.sent_ms == pytest.approx(len(media) * 40)
    assert "reply-x" in marks.latencies()


async def test_prefetch_splits_first_sentence() -> None:
    assert split_for_prefetch("Got it. Where are you based? Thanks.") == [
        "Got it.",
        "Where are you based? Thanks.",
    ]
    p, _line, _sender, _marks = player()
    await p.speak("Got it. Where are you based?", wait=False)
    assert [t for _a, t in p.tts.spoken] == ["Got it.", "Where are you based?"]  # type: ignore[attr-defined]


async def test_fixed_phrases_are_not_split() -> None:
    p, _line, _sender, _marks = player()
    p.no_split = frozenset({"Sorry. Again?"})
    await p.speak("Sorry. Again?", wait=False)
    assert [t for _a, t in p.tts.spoken] == ["Sorry. Again?"]  # type: ignore[attr-defined]


async def test_interrupt_clears_and_estimates_heard() -> None:
    p, line, sender, _marks = player()
    task = asyncio.create_task(p.speak(" ".join(["word"] * 40)))
    await asyncio.sleep(0.6)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    result = await p.interrupt()
    assert result is not None and result.interrupted
    assert line.sent[-1]["event"] == "clear" and sender.buffered_s == 0
    # about 0.6 s played at our end, minus Exotel's playout lag
    assert 0 < (result.heard_ms or 0) <= 600 - PLAYOUT_LAG_MS + 150


async def test_audio_cannot_cross_sessions() -> None:
    _p, _line, sender, marks = player("call-A")
    with pytest.raises(CrossSessionAudioError):
        await sender.push(b"\0" * 640, session_id="call-B")
    with pytest.raises(CrossSessionAudioError):
        Player(sender, FakeTTS(), marks, session_id="call-B")


def test_registry_refuses_duplicates() -> None:
    reg: SessionRegistry[object] = SessionRegistry()
    a = object()
    reg.register("x", a)
    with pytest.raises(SessionExistsError):
        reg.register("x", object())
    reg.unregister("x", object())  # someone else's: ignored
    assert "x" in reg
    reg.unregister("x", a)
    assert len(reg) == 0 and reg.total == 1
