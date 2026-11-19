"""DeepgramTTSProvider against a mocked HTTP transport (no network, no cost)."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import numpy as np
import pytest

from app.providers.tts import create_tts_provider
from app.providers.tts.base import (
    TTSConfigError,
    TTSNotReadyError,
    TTSStreamInterruptedError,
    TTSSynthesisError,
    TTSTimeoutError,
)
from app.providers.tts.deepgram_provider import DeepgramTTSProvider
from app.providers.tts.fallback import FallbackTTSProvider
from app.providers.tts.kitten_provider import KittenTTSProvider
from app.tests.conftest import make_settings

SR = 24000


def speech(ms: int = 300) -> bytes:
    n = SR * ms // 1000
    return (0.3 * np.sin(np.arange(n) / 4) * 32767).astype("<i2").tobytes()


class Server:
    """A fake /v1/speak: records requests and answers with configurable behaviour."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.body = speech()
        self.chunk = 1001  # odd on purpose: chunks must be re-aligned to whole samples
        self.first_delay_s = 0.0
        self.break_after: int | None = None  # raise after this many chunks
        self.fail_next = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_next:
            self.fail_next -= 1
            return httpx.Response(503)
        if self.status != 200:
            return httpx.Response(self.status, content=b'{"err_msg":"bad model"}')

        async def body() -> AsyncIterator[bytes]:
            if self.first_delay_s:
                await asyncio.sleep(self.first_delay_s)
            for i in range(0, len(self.body), self.chunk):
                if self.break_after is not None and i // self.chunk >= self.break_after:
                    raise httpx.ReadError("connection reset")
                yield self.body[i : i + self.chunk]

        return httpx.Response(200, content=body())


@pytest.fixture
def server() -> Server:
    return Server()


def make(server: Server, tmp_path: Path, **kwargs: object) -> DeepgramTTSProvider:
    async def handle(request: httpx.Request) -> httpx.Response:
        return server.handler(request)

    kwargs.setdefault("gain_db", 0.0)  # byte-exact audio unless a test is about the gain
    return DeepgramTTSProvider(
        api_key="dg-test",
        transport=httpx.MockTransport(handle),
        cache_dir=tmp_path / "cache",
        **kwargs,  # type: ignore[arg-type]
    )


async def test_initialize_checks_key_and_caches_phrases(server: Server, tmp_path: Path) -> None:
    p = make(server, tmp_path, fixed_phrases=["Okay."])
    await p.initialize()
    assert p.status().ready
    req = server.requests[0]
    assert req.headers["authorization"] == "Token dg-test"
    assert req.url.params["model"] == "aura-2-harmonia-en"
    assert req.url.params["encoding"] == "linear16"
    assert req.url.params["sample_rate"] == "24000"
    assert req.url.params["container"] == "none"
    assert len(server.requests) == 3  # warm-up + apology + "Okay."
    assert len(list((tmp_path / "cache").glob("*.pcm"))) == 2
    await p.close()


async def test_phrase_disk_cache_survives_restart(server: Server, tmp_path: Path) -> None:
    first = make(server, tmp_path, fixed_phrases=["Okay."])
    await first.initialize()
    await first.close()
    second = make(server, tmp_path, fixed_phrases=["Okay."])
    await second.initialize()
    assert len(server.requests) == 3 + 1  # the second start only sends the warm-up
    assert not second.apology_clip().is_empty
    await second.close()


@pytest.mark.parametrize("status", [401, 403])
async def test_bad_key_is_a_config_error(server: Server, tmp_path: Path, status: int) -> None:
    server.status = status
    p = make(server, tmp_path)
    with pytest.raises(TTSConfigError, match="API key"):
        await p.initialize()
    assert not p.status().ready


async def test_bad_voice_is_a_config_error(server: Server, tmp_path: Path) -> None:
    server.status = 400
    p = make(server, tmp_path, voice="aura-2-nobody-en")
    with pytest.raises(TTSConfigError, match="400"):
        await p.initialize()


async def test_synthesize_returns_whole_aligned_clip(server: Server, tmp_path: Path) -> None:
    p = make(server, tmp_path)
    await p.initialize()
    server.body = speech(500)
    clip = await p.synthesize("Where are you located?")
    assert clip.pcm == server.body
    assert clip.sample_rate == SR and clip.duration_ms == 500
    assert server.requests[-1].read() == b'{"text":"Where are you located?"}'


async def test_text_is_normalized(server: Server, tmp_path: Path) -> None:
    p = make(server, tmp_path)
    await p.initialize()
    await p.synthesize("Your CTC is 12.5 LPA.")
    assert b"twelve point five lakhs per annum" in server.requests[-1].read()


async def test_stream_yields_sample_aligned_pieces(server: Server, tmp_path: Path) -> None:
    p = make(server, tmp_path)
    await p.initialize()
    server.body = speech(400)
    pieces = [c async for c in p.stream("A fresh sentence to stream.")]
    assert len(pieces) > 3
    assert all(len(c.pcm) % 2 == 0 for c in pieces)
    assert b"".join(c.pcm for c in pieces) == server.body
    # the finished stream is cached: a repeat is one piece and no request
    count = len(server.requests)
    again = [c async for c in p.stream("A fresh sentence to stream.")]
    assert len(again) == 1 and len(server.requests) == count


async def test_retry_before_first_audio(server: Server, tmp_path: Path) -> None:
    p = make(server, tmp_path, attempts=2)
    await p.initialize()
    server.fail_next = 1
    assert not (await p.synthesize("Retry me.")).is_empty
    server.fail_next = 2
    with pytest.raises(TTSSynthesisError):
        await p.synthesize("Fail twice.")


async def test_first_byte_timeout(server: Server, tmp_path: Path) -> None:
    p = make(server, tmp_path, attempts=1, first_byte_timeout_s=0.05)
    await p.initialize()
    server.first_delay_s = 0.3
    with pytest.raises(TTSTimeoutError):
        await p.synthesize("Too slow.")


async def test_stream_broken_midway(server: Server, tmp_path: Path) -> None:
    p = make(server, tmp_path)
    await p.initialize()
    server.break_after = 2
    got: list[bytes] = []
    with pytest.raises(TTSStreamInterruptedError):
        async for clip in p.stream("This one breaks."):
            got.append(clip.pcm)
    assert got  # some audio was delivered before the break


async def test_not_ready(server: Server, tmp_path: Path) -> None:
    p = make(server, tmp_path)
    with pytest.raises(TTSNotReadyError):
        await p.synthesize("Hi.")
    with pytest.raises(TTSNotReadyError):
        p.apology_clip()


async def test_empty_text_makes_no_request(server: Server, tmp_path: Path) -> None:
    p = make(server, tmp_path)
    await p.initialize()
    count = len(server.requests)
    assert (await p.synthesize("  ")).is_empty
    assert [c async for c in p.stream("😊")] == []
    assert len(server.requests) == count


async def test_gain_raises_level_without_clipping(server: Server, tmp_path: Path) -> None:
    p = make(server, tmp_path, gain_db=6.0)
    await p.initialize()
    quiet = (0.05 * np.sin(np.arange(SR // 5) / 4) * 32767).astype("<i2")
    loud = (0.7 * np.sin(np.arange(SR // 5) / 4) * 32767).astype("<i2")
    server.body = quiet.tobytes() + loud.tobytes()
    out = np.frombuffer((await p.synthesize("Level check.")).pcm, dtype="<i2").astype(float)
    n = quiet.size
    # quiet part: about +6 dB (x2); loud part: limited below -1 dBFS, never clipped
    assert 1.9 < np.abs(out[:n]).max() / np.abs(quiet).max() < 2.05
    assert np.abs(out[n:]).max() <= 32767 * 10 ** (-1 / 20) + 1


# --- factory -------------------------------------------------------------------------------


@pytest.mark.parametrize("choice", ["auto", "kitten"])
def test_factory_default_is_kitten_then_deepgram(choice: str) -> None:
    provider = create_tts_provider(
        make_settings(
            deepgram_api_key="dg", deepgram_tts_voice="aura-2-asteria-en", tts_provider=choice
        )
    )
    assert isinstance(provider, FallbackTTSProvider)
    assert isinstance(provider.primary, KittenTTSProvider)
    assert provider.primary.attempts == 1  # switch to the fallback instead of retrying
    assert isinstance(provider.fallback, DeepgramTTSProvider)
    assert provider.fallback.voice == "aura-2-asteria-en"
    assert provider.fallback.attempts == 2  # the last resort retries


def test_factory_without_key_is_kitten_alone() -> None:
    provider = create_tts_provider(make_settings())
    assert isinstance(provider, KittenTTSProvider) and provider.attempts == 2


def test_factory_kitten_without_fallback() -> None:
    provider = create_tts_provider(make_settings(deepgram_api_key="dg", tts_fallback=False))
    assert isinstance(provider, KittenTTSProvider) and provider.attempts == 2


def test_factory_deepgram_first_with_kitten_fallback() -> None:
    provider = create_tts_provider(make_settings(deepgram_api_key="dg", tts_provider="deepgram"))
    assert isinstance(provider, FallbackTTSProvider)
    assert isinstance(provider.primary, DeepgramTTSProvider) and provider.primary.attempts == 1
    assert isinstance(provider.fallback, KittenTTSProvider)


def test_factory_deepgram_without_fallback_retries() -> None:
    provider = create_tts_provider(
        make_settings(deepgram_api_key="dg", tts_provider="deepgram", tts_fallback=False)
    )
    assert isinstance(provider, DeepgramTTSProvider)
    assert provider.attempts == 2


def test_factory_deepgram_needs_key() -> None:
    with pytest.raises(TTSConfigError, match="DEEPGRAM_API_KEY"):
        create_tts_provider(make_settings(tts_provider="deepgram"))
