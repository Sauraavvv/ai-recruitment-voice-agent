"""KittenTTSProvider logic with a fake engine: loading, guards, retries, caching, post-processing.

The real model is exercised in tests/integration/test_kitten_provider.py (marked `tts`).
"""

import asyncio
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from app.providers.tts import create_tts_provider, fixed_phrases
from app.providers.tts.base import (
    TECHNICAL_APOLOGY,
    TTSConfigError,
    TTSNotReadyError,
    TTSSynthesisError,
    TTSTimeoutError,
)
from app.providers.tts.kitten_provider import (
    EXPECTED_SAMPLE_RATE,
    KittenTTSProvider,
    model_loads_total,
)
from app.tests.conftest import make_settings

SR = EXPECTED_SAMPLE_RATE


class FakeEngine:
    def __init__(self, sample_rate: int = SR) -> None:
        self.sample_rate = sample_rate
        self.voices = ["Iris", "Grace"]
        self.calls: list[str] = []
        self.fail_next = 0
        self.delay_s = 0.0
        self.lock = threading.Lock()

    def speak(self, text: str) -> np.ndarray:
        with self.lock:
            self.calls.append(text)
            if self.fail_next:
                self.fail_next -= 1
                raise RuntimeError("boom")
        if self.delay_s:
            time.sleep(self.delay_s)
        # 0.2 s silence, then 10 ms of quiet tone per character, then 0.3 s silence
        n = int(SR * 0.01) * len(text)
        tone = (0.1 * np.sin(np.arange(n) / 5)).astype(np.float32)
        return np.concatenate([np.zeros(int(SR * 0.2)), tone, np.zeros(int(SR * 0.3))])[None]


@pytest.fixture
def model_dir(tmp_path: Path) -> Path:
    (tmp_path / "config.json").write_text("{}")
    return tmp_path


def make_provider(
    model_dir: Path, engine: FakeEngine | None = None, **kwargs: object
) -> tuple[KittenTTSProvider, FakeEngine]:
    engine = engine or FakeEngine()

    def factory(_dir: Path, voice: str, _threads: int) -> FakeEngine:
        if voice not in engine.voices:
            raise TTSConfigError(f"unknown KITTEN_VOICE {voice!r}")
        return engine

    provider = KittenTTSProvider(model_dir=model_dir, engine_factory=factory, **kwargs)  # type: ignore[arg-type]
    return provider, engine


async def test_initialize_loads_once_warms_up_and_caches_phrases(model_dir: Path) -> None:
    before = model_loads_total()
    provider, engine = make_provider(model_dir, fixed_phrases=["Okay.", "Got it."])
    assert not provider.status().ready
    await provider.initialize()
    await provider.initialize()  # idempotent
    assert model_loads_total() == before + 1
    assert engine.calls[0].startswith("Hello, this is a warm up")
    assert provider.cached_phrases == 3  # apology + 2
    status = provider.status()
    assert status.ready and "Iris" in status.detail and status.model_loads == before + 1
    await provider.close()


async def test_synthesize_before_initialize_is_refused(model_dir: Path) -> None:
    provider, _ = make_provider(model_dir)
    with pytest.raises(TTSNotReadyError):
        await provider.synthesize("Hello.")


async def test_missing_model_dir_is_a_config_error(tmp_path: Path) -> None:
    provider, _ = make_provider(tmp_path / "nowhere")
    with pytest.raises(TTSConfigError, match="no Kitten model"):
        await provider.initialize()
    assert not provider.status().ready
    assert "no Kitten model" in (provider.status().last_error or "")


async def test_unknown_voice_is_a_config_error(model_dir: Path) -> None:
    provider, _ = make_provider(model_dir, voice="Nobody")
    with pytest.raises(TTSConfigError, match="Nobody"):
        await provider.initialize()


async def test_wrong_sample_rate_is_a_config_error(model_dir: Path) -> None:
    provider, _ = make_provider(model_dir, FakeEngine(sample_rate=22050))
    with pytest.raises(TTSConfigError, match="22050"):
        await provider.initialize()


async def test_audio_is_trimmed_normalized_int16(model_dir: Path) -> None:
    provider, _ = make_provider(model_dir)
    await provider.initialize()
    clip = await provider.synthesize("Hi there")
    samples = np.frombuffer(clip.pcm, dtype="<i2")
    assert clip.sample_rate == SR
    # 8 chars → 80 ms of tone plus up to 50 ms padding either side; the 0.5 s of silence is gone
    assert 80 <= clip.duration_ms <= 185
    assert abs(int(np.max(np.abs(samples))) - round(32767 * 10 ** (-3 / 20))) <= 2


async def test_text_is_normalized_before_synthesis(model_dir: Path) -> None:
    provider, engine = make_provider(model_dir)
    await provider.initialize()
    await provider.synthesize("Your CTC is 12.5 LPA.")
    assert engine.calls[-1] == "Your C T C is twelve point five lakhs per annum."


async def test_empty_text_gives_empty_clip(model_dir: Path) -> None:
    provider, engine = make_provider(model_dir)
    await provider.initialize()
    calls = len(engine.calls)
    for text in ("", "   ", "😊", "**"):
        assert (await provider.synthesize(text)).is_empty
    assert len(engine.calls) == calls


async def test_long_text_is_chunked(model_dir: Path) -> None:
    provider, engine = make_provider(model_dir)
    await provider.initialize()
    sentence = "This is a fairly ordinary sentence about the role and the team. "
    calls = len(engine.calls)
    clip = await provider.synthesize(sentence * 8)  # ~520 characters
    assert len(engine.calls) - calls > 1
    assert all(len(c) <= 400 for c in engine.calls[calls:])
    assert not clip.is_empty


async def test_fixed_phrases_and_repeats_come_from_cache(model_dir: Path) -> None:
    provider, engine = make_provider(model_dir, fixed_phrases=["Got it."])
    await provider.initialize()
    calls = len(engine.calls)
    first = await provider.synthesize("Got it.")
    assert len(engine.calls) == calls  # pinned at startup
    await provider.synthesize("Thanks, Rahul.")
    await provider.synthesize("Thanks, Rahul.")
    assert len(engine.calls) == calls + 1  # second one from the LRU
    assert first == await provider.synthesize("Got it.")


async def test_apology_clip_is_ready_after_initialize(model_dir: Path) -> None:
    provider, engine = make_provider(model_dir)
    with pytest.raises(TTSNotReadyError):
        provider.apology_clip()
    await provider.initialize()
    assert not provider.apology_clip().is_empty
    assert any("technical problem" in c for c in engine.calls)
    assert TECHNICAL_APOLOGY.startswith("Sorry")


async def test_one_failure_is_retried(model_dir: Path) -> None:
    provider, engine = make_provider(model_dir)
    await provider.initialize()
    engine.fail_next = 1
    clip = await provider.synthesize("Where are you located?")
    assert not clip.is_empty
    assert "attempt 1" in (provider.status().last_error or "")


async def test_two_failures_raise(model_dir: Path) -> None:
    provider, engine = make_provider(model_dir)
    await provider.initialize()
    engine.fail_next = 2
    with pytest.raises(TTSSynthesisError):
        await provider.synthesize("Where are you located?")
    # the provider still works afterwards
    assert not (await provider.synthesize("Where are you located?")).is_empty


async def test_timeouts_raise_after_one_retry(model_dir: Path) -> None:
    provider, engine = make_provider(model_dir, timeout_s=0.05, max_workers=2)
    await provider.initialize()
    engine.delay_s = 0.2
    with pytest.raises(TTSTimeoutError):
        await provider.synthesize("This will be slow.")
    engine.delay_s = 0


async def test_synthesis_runs_off_the_event_loop(model_dir: Path) -> None:
    provider, engine = make_provider(model_dir, max_workers=1)
    await provider.initialize()
    engine.delay_s = 0.15
    ticks = 0

    async def ticker() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    await provider.synthesize("A sentence that takes a while.")
    task.cancel()
    assert ticks >= 8  # the loop kept running during the 150 ms synthesis


async def test_failed_warm_up_leaves_provider_not_ready(model_dir: Path) -> None:
    engine = FakeEngine()
    engine.fail_next = 1
    provider, _ = make_provider(model_dir, engine)
    with pytest.raises(TTSConfigError, match=r"failed to load|warm-up"):
        await provider.initialize()
    assert not provider.status().ready


def test_factory_uses_settings_and_defaults() -> None:
    provider = create_tts_provider(
        make_settings(tts_threads=3, kitten_model_path="/x/y", tts_provider="kitten")
    )
    assert isinstance(provider, KittenTTSProvider)
    assert provider.voice == "Iris"
    assert provider.threads == 3
    assert provider.model_dir == Path("/x/y")
    assert provider.status().detail == "not loaded"


def test_fixed_phrases_have_no_placeholders() -> None:
    phrases = fixed_phrases()
    assert len(phrases) >= 10
    assert not any("{" in p or "None" in p for p in phrases)
