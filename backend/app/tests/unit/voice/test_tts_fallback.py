"""FallbackTTSProvider routing: per-sentence fallback, sticky calls, circuit breaker."""

from collections.abc import AsyncIterator

import pytest

from app.providers.tts.base import (
    AudioClip,
    ProviderStatus,
    TTSConfigError,
    TTSNotReadyError,
    TTSProvider,
    TTSStreamInterruptedError,
    TTSSynthesisError,
)
from app.providers.tts.fallback import FallbackTTSProvider

SR = 24000


class Fake(TTSProvider):
    def __init__(self, name: str, *, sample_rate: int = SR) -> None:
        self.name = name
        self.sample_rate = sample_rate
        self.ready = False
        self.fail_init = False
        self.fail = False
        self.break_stream = False
        self.spoken: list[str] = []

    async def initialize(self) -> None:
        if self.fail_init:
            raise TTSConfigError(f"{self.name} down")
        self.ready = True

    def _clip(self) -> AudioClip:
        return AudioClip.from_pcm(self.name.encode().ljust(48, b"\0"), self.sample_rate)

    async def synthesize(self, text: str, *, call_attempt_id: str | None = None) -> AudioClip:
        if not self.ready:
            raise TTSNotReadyError(self.name)
        if self.fail:
            raise TTSSynthesisError(f"{self.name} failed")
        self.spoken.append(text)
        return self._clip()

    async def stream(
        self, text: str, *, call_attempt_id: str | None = None
    ) -> AsyncIterator[AudioClip]:
        if self.fail:
            raise TTSSynthesisError(f"{self.name} failed")
        self.spoken.append(text)
        yield self._clip()
        if self.break_stream:
            raise TTSStreamInterruptedError("broke")
        yield self._clip()

    def apology_clip(self, *, call_attempt_id: str | None = None) -> AudioClip:
        if not self.ready:
            raise TTSNotReadyError(self.name)
        return self._clip()

    async def close(self) -> None:
        self.ready = False

    def status(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, ready=self.ready, detail=self.name)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


async def make(**kw: float) -> tuple[FallbackTTSProvider, Fake, Fake, Clock]:
    primary, fallback, clock = Fake("deepgram"), Fake("kitten"), Clock()
    provider = FallbackTTSProvider(primary, fallback, clock=clock, **kw)  # type: ignore[arg-type]
    await provider.initialize()
    return provider, primary, fallback, clock


def who(clip: AudioClip) -> str:
    return clip.pcm.rstrip(b"\0").decode()


async def test_primary_speaks_when_healthy() -> None:
    p, _, fallback, _ = await make()
    assert who(await p.synthesize("Hi.", call_attempt_id="c1")) == "deepgram"
    assert fallback.spoken == []
    status = p.status()
    assert status.ready and status.name == "deepgram+kitten" and len(status.components) == 2


async def test_failed_sentence_goes_to_fallback_and_call_sticks() -> None:
    p, primary, _, _ = await make()
    primary.fail = True
    assert who(await p.synthesize("One.", call_attempt_id="c1")) == "kitten"
    primary.fail = False
    # same call stays on Kitten so the voice doesn't switch back
    assert who(await p.synthesize("Two.", call_attempt_id="c1")) == "kitten"
    assert p.is_on_fallback("c1")
    # another call still gets the primary
    assert who(await p.synthesize("Three.", call_attempt_id="c2")) == "deepgram"
    p.forget_call("c1")
    assert who(await p.synthesize("Four.", call_attempt_id="c1")) == "deepgram"


async def test_circuit_opens_after_repeated_failures_and_recovers() -> None:
    p, primary, _, clock = await make(max_failures=3, open_s=60)
    primary.fail = True
    for i in range(3):
        await p.synthesize(f"x{i}", call_attempt_id=f"call{i}")
    primary.fail = False
    calls_before = len(primary.spoken)
    assert who(await p.synthesize("new call", call_attempt_id="fresh")) == "kitten"
    assert len(primary.spoken) == calls_before  # primary not even tried while open
    assert "circuit open" in p.status().detail
    clock.t += 61
    assert who(await p.synthesize("later", call_attempt_id="fresh2")) == "deepgram"


async def test_success_resets_failure_count() -> None:
    p, primary, _, _ = await make(max_failures=2)
    primary.fail = True
    await p.synthesize("a", call_attempt_id="c1")
    primary.fail = False
    await p.synthesize("b", call_attempt_id="c2")
    primary.fail = True
    await p.synthesize("c", call_attempt_id="c3")
    assert "circuit open" not in p.status().detail


async def test_stream_falls_back_before_first_audio() -> None:
    p, primary, _, _ = await make()
    primary.fail = True
    pieces = [who(c) async for c in p.stream("Hi.", call_attempt_id="c1")]
    assert pieces == ["kitten", "kitten"]


async def test_stream_broken_midway_repeats_sentence_on_fallback() -> None:
    p, primary, fallback, _ = await make()
    primary.break_stream = True
    pieces = [who(c) async for c in p.stream("Hello there.", call_attempt_id="c1")]
    assert pieces == ["deepgram", "kitten", "kitten"]
    assert fallback.spoken == ["Hello there."]
    assert p.is_on_fallback("c1")


async def test_primary_down_at_startup_uses_fallback() -> None:
    primary, fallback = Fake("deepgram"), Fake("kitten")
    primary.fail_init = True
    p = FallbackTTSProvider(primary, fallback)
    await p.initialize()
    assert p.status().ready
    assert who(await p.synthesize("Hi.")) == "kitten"
    assert who(p.apology_clip()) == "kitten"


async def test_fallback_down_at_startup_uses_primary_and_raises_its_errors() -> None:
    primary, fallback = Fake("deepgram"), Fake("kitten")
    fallback.fail_init = True
    p = FallbackTTSProvider(primary, fallback)
    await p.initialize()
    assert who(await p.synthesize("Hi.")) == "deepgram"
    primary.fail = True
    with pytest.raises(TTSSynthesisError):
        await p.synthesize("Hi again.")


async def test_both_down_is_a_startup_error() -> None:
    primary, fallback = Fake("deepgram"), Fake("kitten")
    primary.fail_init = fallback.fail_init = True
    p = FallbackTTSProvider(primary, fallback)
    with pytest.raises(TTSConfigError, match="no TTS available"):
        await p.initialize()
    with pytest.raises(TTSNotReadyError):
        await p.synthesize("Hi.")


async def test_apology_matches_the_calls_voice() -> None:
    p, primary, _, _ = await make()
    assert who(p.apology_clip(call_attempt_id="c1")) == "deepgram"
    primary.fail = True
    await p.synthesize("x", call_attempt_id="c1")
    assert who(p.apology_clip(call_attempt_id="c1")) == "kitten"


def test_sample_rates_must_match() -> None:
    with pytest.raises(TTSConfigError, match="sample rates"):
        FallbackTTSProvider(Fake("a"), Fake("b", sample_rate=8000))


async def test_primary_down_at_startup_is_retried_later() -> None:
    import asyncio

    primary, fallback, clock = Fake("deepgram"), Fake("kitten"), Clock()
    primary.fail_init = True
    p = FallbackTTSProvider(primary, fallback, clock=clock)
    await p.initialize()
    assert who(await p.synthesize("a", call_attempt_id="c1")) == "kitten"
    primary.fail_init = False
    clock.t += 61  # retry is due: the next request starts it in the background
    assert who(await p.synthesize("b", call_attempt_id="c2")) == "kitten"
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert who(await p.synthesize("c", call_attempt_id="c3")) == "deepgram"
    await p.close()
