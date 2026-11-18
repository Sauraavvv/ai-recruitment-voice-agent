"""Live Deepgram Aura TTS (marked `deepgram`: costs a few cents, needs DEEPGRAM_API_KEY).

Run with `make test-deepgram-tts`.
"""

import os
from pathlib import Path

import pytest

from app.providers.tts.base import TTSConfigError
from app.providers.tts.deepgram_provider import DEFAULT_VOICE, DeepgramTTSProvider

pytestmark = pytest.mark.deepgram

KEY = os.getenv("DEEPGRAM_API_KEY", "")
if not KEY:
    pytest.skip("DEEPGRAM_API_KEY not set", allow_module_level=True)


async def test_stream_and_synthesize(tmp_path: Path) -> None:
    voice = os.getenv("DEEPGRAM_TTS_VOICE") or DEFAULT_VOICE
    p = DeepgramTTSProvider(api_key=KEY, voice=voice, cache_dir=tmp_path)
    await p.initialize()
    pieces = [c async for c in p.stream("Hello, am I speaking with Priya Iyer?")]
    assert pieces and all(len(c.pcm) % 2 == 0 for c in pieces)
    total_ms = sum(c.duration_ms for c in pieces)
    assert 1000 < total_ms < 5000
    clip = await p.synthesize("Your current CTC is 12.5 LPA, right?")
    assert clip.sample_rate == 24000 and clip.duration_ms > 1000
    assert not p.apology_clip().is_empty
    assert p.status().ready and (p.status().last_latency_ms or 0) > 0
    await p.close()


async def test_bad_key_is_a_config_error(tmp_path: Path) -> None:
    p = DeepgramTTSProvider(api_key="not-a-real-key", cache_dir=tmp_path)
    with pytest.raises(TTSConfigError, match="API key"):
        await p.initialize()


async def test_unknown_voice_is_a_config_error(tmp_path: Path) -> None:
    p = DeepgramTTSProvider(api_key=KEY, voice="aura-2-nobody-en", cache_dir=tmp_path)
    with pytest.raises(TTSConfigError):
        await p.initialize()
