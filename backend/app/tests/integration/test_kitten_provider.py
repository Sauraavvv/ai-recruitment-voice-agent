"""The real Kitten model (marked `tts`, run with `make test-tts`; skipped without the model files).

Covers P3-AC1 (every agent reply synthesizes), P3-AC2 (the model loads once) and P3-AC4 (the
sample rate is known and checked).
"""

from collections.abc import AsyncIterator
from pathlib import Path

import numpy as np
import pytest
import pytest_asyncio

from app.providers.tts import fixed_phrases
from app.providers.tts.base import TTSConfigError
from app.providers.tts.kitten_provider import (
    EXPECTED_SAMPLE_RATE,
    KittenTTSProvider,
    model_loads_total,
    resolve_model_dir,
)
from app.tests.fixtures.tts_corpus import agent_corpus, listening_sentences

pytestmark = pytest.mark.tts

MODEL_DIR = resolve_model_dir(None)
if not (MODEL_DIR / "config.json").is_file():
    pytest.skip(f"Kitten model not found at {MODEL_DIR} (make tts-model)", allow_module_level=True)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def provider() -> AsyncIterator[KittenTTSProvider]:
    p = KittenTTSProvider(model_dir=MODEL_DIR, threads=2, fixed_phrases=fixed_phrases())
    await p.initialize()
    yield p
    await p.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_sample_rate_is_24khz(provider: KittenTTSProvider) -> None:
    assert provider.sample_rate == EXPECTED_SAMPLE_RATE == 24000
    assert provider.status().ready


@pytest.mark.asyncio(loop_scope="module")
async def test_listening_sentences_give_audio_proportional_to_length(
    provider: KittenTTSProvider,
) -> None:
    for text in listening_sentences():
        clip = await provider.synthesize(text)
        assert clip.sample_rate == 24000
        assert not clip.is_empty, text
        # roughly 35-110 ms of speech per character for this voice after normalization
        chars = len(text)
        assert 30 * chars <= clip.duration_ms <= 160 * chars + 400, (text, clip.duration_ms)
        samples = np.frombuffer(clip.pcm, dtype="<i2")
        assert np.max(np.abs(samples)) > 20000  # peak-normalized, not silent


@pytest.mark.asyncio(loop_scope="module")
async def test_every_agent_reply_synthesizes(provider: KittenTTSProvider) -> None:
    corpus = agent_corpus()
    assert len(corpus) >= 100
    failures = []
    for text in corpus:
        clip = await provider.synthesize(text)
        if clip.is_empty or clip.duration_ms < 300:
            failures.append(text)
    assert failures == []


@pytest.mark.asyncio(loop_scope="module")
async def test_model_loads_once_over_100_syntheses(provider: KittenTTSProvider) -> None:
    loads = model_loads_total()
    assert loads >= 1
    for i in range(100):
        await provider.synthesize(f"Number {i} of one hundred, Priya.")
    assert model_loads_total() == loads  # 1 when this module runs alone (make test-tts)


@pytest.mark.asyncio(loop_scope="module")
async def test_unknown_voice_is_a_clear_startup_error() -> None:
    p = KittenTTSProvider(model_dir=MODEL_DIR, voice="Nobody")
    with pytest.raises(TTSConfigError, match="unknown KITTEN_VOICE 'Nobody'"):
        await p.initialize()
    await p.close()


@pytest.mark.asyncio(loop_scope="module")
async def test_bad_model_path_is_a_clear_startup_error(tmp_path: Path) -> None:
    p = KittenTTSProvider(model_dir=tmp_path / "missing")
    with pytest.raises(TTSConfigError, match="no Kitten model"):
        await p.initialize()
    await p.close()
