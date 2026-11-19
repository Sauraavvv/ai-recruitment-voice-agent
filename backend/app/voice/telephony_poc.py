"""Phase 5 telephony PoC script, kept as a line check for `make test-call mode=full|listen`.

    full    clip → beep → 15 s echo → stop (`clear`) test → goodbye → backend hangs up
    listen  clip, then record until the caller hangs up

Real calls run the screening conversation (`voice/pipeline.py`); this only runs when a test
call asks for it.
"""

import asyncio
import time
from dataclasses import dataclass

import numpy as np

from app.config import Settings
from app.providers.tts.base import TTSError, TTSProvider
from app.voice import audio_converter as ac
from app.voice import pcm as pcm_utils
from app.voice.audio_processor import InboundQueue
from app.voice.playback import AudioSender, MarkTracker

INTRO_FULL = (
    "Hello, this is a test call from the recruitment assistant. "
    "If you can hear me clearly, please say something after the beep. "
    "You will hear yourself back about one second later."
)
INTRO_LISTEN = (
    "Hello, this is a test call from the recruitment assistant. "
    "Please say a few words, and then hang up whenever you like."
)
CLEAR_INTRO = "Now a stop test. I will count to ten, but I should stop at about three."
COUNTING = "One. Two. Three. Four. Five. Six. Seven. Eight. Nine. Ten."
GOODBYE = "The test is finished. Thank you, goodbye."
ECHO_SECONDS = 15.0
ECHO_DELAY_S = 1.0
CLEAR_AFTER_S = 2.6  # "one, two, three" takes about this long


@dataclass
class PocSession:
    attempt_id: str
    sender: AudioSender
    inbound: InboundQueue
    marks: MarkTracker
    notes: list[str]
    hangup_requested: bool = False

    def note(self, text: str) -> None:
        self.notes.append(text)


def _beep(rate: int, *, hz: float = 880.0, ms: int = 300) -> bytes:
    t = np.arange(int(rate * ms / 1000)) / rate
    tone = (0.3 * np.sin(2 * np.pi * hz * t)).astype(np.float32)
    fade = min(len(tone) // 10, int(rate * 0.01))
    if fade:
        ramp = np.linspace(0, 1, fade, dtype=np.float32)
        tone[:fade] *= ramp
        tone[-fade:] *= ramp[::-1]
    return pcm_utils.float_to_pcm16(tone)


async def _speak(tts: TTSProvider, text: str, settings: Settings, attempt_id: str) -> bytes:
    clip = await tts.synthesize(text, call_attempt_id=attempt_id)
    return ac.to_telephony(
        clip.pcm,
        clip.sample_rate,
        to_rate=settings.telephony_sample_rate,
        encoding=settings.telephony_encoding,
    )


async def _mark(session: PocSession, name: str) -> None:
    session.marks.note_sent(name)
    await session.sender.mark(name)


async def _wait_mark(session: PocSession, name: str, timeout: float) -> bool:
    ok = await session.marks.wait(name, timeout)
    if not ok:
        session.note(f"mark {name} not returned within {timeout:.0f}s")
    return ok


async def _echo(session: PocSession, seconds: float) -> None:
    """Send the caller's own audio back ECHO_DELAY_S later."""
    session.inbound.drain()
    await asyncio.sleep(ECHO_DELAY_S)
    end = time.monotonic() + seconds
    encoding = session.sender.encoding
    while time.monotonic() < end:
        try:
            chunk = await asyncio.wait_for(session.inbound.get(), timeout=1.0)
        except TimeoutError:
            continue
        except EOFError:
            return
        out = ac.pcm16_to_mulaw(chunk) if encoding == "mulaw" else chunk
        await session.sender.push(out)


async def run_poc(
    session: PocSession, mode: str, tts: TTSProvider | None, settings: Settings
) -> None:
    ready = tts is not None and tts.status().ready
    if not ready:
        session.note("no TTS available; playing beeps only")
    try:
        say = (
            (lambda text: _speak(tts, text, settings, session.attempt_id))
            if tts is not None and ready
            else None
        )
        beep = ac.to_telephony(
            _beep(settings.telephony_sample_rate),
            settings.telephony_sample_rate,
            to_rate=settings.telephony_sample_rate,
            encoding=settings.telephony_encoding,
        )
        await asyncio.sleep(0.3)
        intro = await say(INTRO_FULL if mode == "full" else INTRO_LISTEN) if say else b""
        session.note(f"intro clip {len(intro)} bytes; playing")
        await session.sender.play(intro + (beep if mode == "full" else b""))
        await _mark(session, "intro")
        await _wait_mark(session, "intro", timeout=30)
        if mode == "listen":
            session.note("listen mode: waiting for the caller to hang up")
            return

        session.note("echo start")
        await _echo(session, ECHO_SECONDS)
        session.note("echo end")
        await session.sender.play(b"")
        await asyncio.sleep(session.sender.buffered_s + 0.5)

        if say:
            await session.sender.play(await say(CLEAR_INTRO))
            await _mark(session, "clear-intro")
            await _wait_mark(session, "clear-intro", timeout=20)
            counting = await say(COUNTING)
            ms = ac.duration_ms(
                len(counting), settings.telephony_encoding, settings.telephony_sample_rate
            )
            session.note(f"counting clip {ms:.0f} ms; sending all of it ahead")
            sent_at = time.monotonic()
            # Send far ahead so Exotel holds most of it in its buffer, then clear.
            await session.sender.play(counting, ahead_s=30.0)
            await _mark(session, "counting")
            await asyncio.sleep(max(0.0, CLEAR_AFTER_S - (time.monotonic() - sent_at)))
            await session.sender.clear()
            session.note(f"clear sent {time.monotonic() - sent_at:.2f}s after counting started")
            got = await _wait_mark(session, "counting", timeout=3)
            session.note(f"counting mark after clear: {'returned' if got else 'not returned'}")
            await asyncio.sleep(1.0)
            await session.sender.play(await say(GOODBYE))
        await _mark(session, "bye")
        await _wait_mark(session, "bye", timeout=20)
        session.note("hanging up from the backend (closing the stream)")
        session.hangup_requested = True
    except TTSError as exc:
        session.note(f"TTS failed: {exc}")
        session.hangup_requested = True
