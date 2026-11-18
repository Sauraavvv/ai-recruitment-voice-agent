"""Live Deepgram streaming tests (plan P4 §7). Cost: a few cents. Run with `make test-stt`.

Needs DEEPGRAM_API_KEY and the synthetic clips (`make stt-clips` on the Mac host; Docker sees
them through the artifacts mount).
"""

import asyncio
import uuid
from pathlib import Path

import pytest

from app.config import Settings, load_settings
from app.providers.stt import create_stt_provider, default_keyterms
from app.providers.stt.base import STTConfigError
from app.providers.stt.deepgram_provider import DeepgramSTTProvider
from app.scripts.stt_tools import (
    AUDIO_ROOT,
    ClipFile,
    discover,
    entity_hits,
    prepare,
    read_wav,
    stream_pcm,
)
from app.voice.utterance import Utterance, UtteranceAssembler

pytestmark = pytest.mark.stt

RATE = 8000  # phone band: what calls will send


@pytest.fixture(scope="module")
def live_settings() -> Settings:
    settings = load_settings()
    if not settings.deepgram_api_key:
        pytest.skip("DEEPGRAM_API_KEY not set")
    return settings


@pytest.fixture(scope="module")
def clips() -> dict[str, ClipFile]:
    found = {c.path.stem: c for c in discover(("synthetic",)) if c.speaker == "rishi"}
    if not found:
        pytest.skip(f"no clips under {AUDIO_ROOT}/synthetic: run `make stt-clips` on the host")
    return found


def audio(clip: ClipFile) -> bytes:
    return prepare(*read_wav(clip.path), RATE)


def new_stt(settings: Settings, **overrides: object) -> DeepgramSTTProvider:
    stt = create_stt_provider(settings, keyterms=["Infosys", "Wipro", "Accenture", "HCL"])
    assert isinstance(stt, DeepgramSTTProvider)
    for key, value in overrides.items():
        setattr(stt, key, value)
    return stt


class Session:
    """One STT session plus its assembler, collecting utterances in the background."""

    def __init__(self, stt: DeepgramSTTProvider) -> None:
        self.stt = stt
        self.id = f"test-{uuid.uuid4().hex[:8]}"
        self.assembler = UtteranceAssembler(self.id)
        self.utterances: list[Utterance] = []
        self.errors: list[str] = []
        self.event_sessions: set[str] = set()
        self._listener: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "Session":
        await self.stt.start_stream(session_id=self.id, encoding="linear16", sample_rate=RATE)
        self._listener = asyncio.create_task(self._listen())
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stt.close()
        assert self._listener is not None
        await asyncio.wait_for(self._listener, 5)

    async def _listen(self) -> None:
        async for event in self.stt.events():
            self.event_sessions.add(event.session_id)
            if event.kind == "error":
                self.errors.append(event.detail or "")
            if (u := self.assembler.feed(event)) is not None:
                self.utterances.append(u)

    @property
    def text(self) -> str:
        return " ".join(u.text for u in self.utterances)

    async def wait_for_utterances(self, n: int, timeout: float = 8.0) -> None:
        async def poll() -> None:
            while len(self.utterances) < n:  # noqa: ASYNC110 - simple poll in a test
                await asyncio.sleep(0.05)

        await asyncio.wait_for(poll(), timeout)


async def test_clips_transcribe_with_key_entities(
    live_settings: Settings, clips: dict[str, ClipFile]
) -> None:
    answers = [c for c in clips.values() if c.spec.utterances and c.noise is None]
    limit = asyncio.Semaphore(8)

    async def run(clip: ClipFile) -> tuple[ClipFile, str]:
        async with limit, Session(new_stt(live_settings)) as s:
            await stream_pcm(s.stt, audio(clip), RATE)
        return clip, s.text

    results = await asyncio.gather(*(run(c) for c in answers))
    hits = [
        (clip.spec.id, h, text)
        for clip, text in results
        for h in entity_hits(text, clip.spec.entities)
    ]
    misses = [(cid, text) for cid, h, text in hits if not h]
    accuracy = 1 - len(misses) / len(hits)
    print(f"\nentity accuracy {accuracy:.1%} ({len(hits) - len(misses)}/{len(hits)})")
    assert accuracy >= 0.9, misses
    assert all(text for _, text in results)  # every answer produced a transcript


async def test_silence_keeps_the_stream_alive(
    live_settings: Settings, clips: dict[str, ClipFile]
) -> None:
    """15 s with no audio at all (longer than Deepgram's idle timeout: keepalives hold it open),
    then 15 s of silent audio: no utterances, no errors; then speech still transcribes."""
    async with Session(new_stt(live_settings)) as s:
        await asyncio.sleep(15)
        await stream_pcm(s.stt, b"\0" * (RATE * 2 * 15), RATE, tail_silence_s=0)
        assert s.utterances == [] and s.errors == []
        await stream_pcm(s.stt, audio(clips["c12_wipro"]), RATE)
        await s.wait_for_utterances(1)
    assert "wipro" in s.text.lower()
    assert s.stt.stats.connects == 1 and s.stt.stats.reconnects == 0


async def test_reconnects_after_the_socket_is_killed(
    live_settings: Settings, clips: dict[str, ClipFile]
) -> None:
    async with Session(new_stt(live_settings)) as s:
        await stream_pcm(s.stt, audio(clips["c02_company_city"]), RATE)
        await s.wait_for_utterances(1)
        s.stt.simulate_network_drop()
        await stream_pcm(s.stt, audio(clips["c18_ninety_days"]), RATE)
        await s.wait_for_utterances(2)
    assert s.stt.stats.reconnects == 1
    assert s.errors == []
    assert all(entity_hits(s.text, [["infosys"], ["90 days", "ninety days"]]))
    # session time keeps running across the two connections
    assert s.utterances[1].started_at is not None and s.utterances[0].ended_at is not None
    assert s.utterances[1].started_at > s.utterances[0].ended_at


async def test_invalid_key_is_a_clean_error(live_settings: Settings) -> None:
    stt = DeepgramSTTProvider(api_key="0" * 40)
    with pytest.raises(STTConfigError, match="API key"):
        await stt.start_stream(session_id="bad-key", encoding="linear16", sample_rate=RATE)
    await stt.close()


async def test_two_sessions_at_once_stay_separate(
    live_settings: Settings, clips: dict[str, ClipFile]
) -> None:
    a_clip, b_clip = clips["c12_wipro"], clips["c10_relocate"]

    async def run(clip: ClipFile) -> Session:
        async with Session(new_stt(live_settings)) as s:
            await stream_pcm(s.stt, audio(clip), RATE)
        return s

    a, b = await asyncio.gather(run(a_clip), run(b_clip))
    assert a.event_sessions == {a.id} and b.event_sessions == {b.id}
    assert "wipro" in a.text.lower() and "chennai" not in a.text.lower()
    assert "chennai" in b.text.lower() and "wipro" not in b.text.lower()


def test_default_keyterms_reach_the_provider(live_settings: Settings) -> None:
    stt = new_stt(live_settings)
    assert set(default_keyterms(live_settings)) <= set(stt.keyterms)


def test_clip_folder_layout() -> None:
    assert AUDIO_ROOT == Path("artifacts/stt-audio")
