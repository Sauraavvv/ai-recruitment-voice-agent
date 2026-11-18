"""Deepgram Aura-2 text-to-speech behind `TTSProvider` (REST, streamed response).

- Audio: linear16, 24 kHz, mono, no container, the same format as Kitten, so either provider can
  feed the same pipeline (and the fallback can switch without conversion).
- Deepgram sends the first audio after about 330 ms, then the rest at about twice real time
  (docs/benchmarks/tts.md). Use `stream()` for live playback. `synthesize()` waits for the whole
  clip, which is fine for cached phrases and tools, but too slow for live replies.
- Fixed phrases are pre-synthesized at startup and cached on disk (`cache_dir`), so restarts
  don't pay for them again. Pinned phrases are also silence-trimmed.
- Loudness: all Deepgram audio gets `gain_db` (default +6 dB for Harmonia, whose average level
  is ~7 dB below Kitten's Iris) through a stateless soft limiter, so streamed chunks, pinned
  phrases and the Kitten fallback sound about equally loud.
- Errors: 401/403 → TTSConfigError (bad key); 400 → TTSConfigError (bad voice/model); 429/5xx,
  network errors and timeouts → retried `attempts` times before the first audio byte, then
  TTSTimeoutError / TTSSynthesisError. A failure after audio started → TTSStreamInterruptedError.
"""

import asyncio
import contextlib
import hashlib
import time
from collections import OrderedDict
from collections.abc import AsyncGenerator, AsyncIterator, Iterable
from pathlib import Path

import httpx

from app.providers.tts.base import (
    TECHNICAL_APOLOGY,
    AudioClip,
    ProviderStatus,
    TTSConfigError,
    TTSError,
    TTSNotReadyError,
    TTSProvider,
    TTSStreamInterruptedError,
    TTSSynthesisError,
    TTSTimeoutError,
)
from app.utils.log import get_logger
from app.voice import pcm
from app.voice.text_normalizer import TextNormalizer, default_normalizer

logger = get_logger(__name__)

DEEPGRAM_SPEAK_URL = "https://api.deepgram.com/v1/speak"
SAMPLE_RATE = 24000
DEFAULT_VOICE = "aura-2-harmonia-en"  # chosen by the user, 2026-11-18 (docs/benchmarks/tts.md)
# Harmonia's average loudness is ~7 dB below Kitten's Iris; this brings it level (soft-limited).
DEFAULT_GAIN_DB = 6.0
LRU_SIZE = 64
WARM_UP_TEXT = "Hello."


class DeepgramTTSProvider(TTSProvider):
    def __init__(
        self,
        *,
        api_key: str,
        voice: str = DEFAULT_VOICE,
        first_byte_timeout_s: float = 1.5,
        total_timeout_s: float = 20.0,
        attempts: int = 2,
        gain_db: float = DEFAULT_GAIN_DB,
        cache_dir: Path | None = None,
        normalizer: TextNormalizer | None = None,
        fixed_phrases: Iterable[str] = (),
        url: str = DEEPGRAM_SPEAK_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.sample_rate = SAMPLE_RATE
        self.voice = voice
        self.first_byte_timeout_s = first_byte_timeout_s
        self.total_timeout_s = total_timeout_s
        self.attempts = max(1, attempts)
        self.gain_db = gain_db
        self.cache_dir = cache_dir
        self._api_key = api_key
        self._url = url
        self._transport = transport
        self._normalize = normalizer or default_normalizer()
        self._fixed_phrases = [TECHNICAL_APOLOGY, *fixed_phrases]
        self._client: httpx.AsyncClient | None = None
        self._ready = False
        self._pinned: dict[str, AudioClip] = {}
        self._lru: OrderedDict[str, AudioClip] = OrderedDict()
        self._last_error: str | None = None
        self._last_latency_ms: int | None = None  # time to first audio

    # --- lifecycle ---------------------------------------------------------------------------

    async def initialize(self) -> None:
        if self._ready:
            return
        self._client = httpx.AsyncClient(
            transport=self._transport,
            timeout=httpx.Timeout(self.total_timeout_s, connect=5.0),
            headers={"Authorization": f"Token {self._api_key}"},
        )
        started = time.perf_counter()
        try:
            await self._fetch(WARM_UP_TEXT)  # checks the key and the voice, opens the connection
            limit = asyncio.Semaphore(4)

            async def pin(phrase: str) -> None:
                normalized = self._normalize(phrase)
                async with limit:
                    self._pinned[self._key(normalized)] = await self._pinned_clip(normalized)

            await asyncio.gather(*(pin(p) for p in self._fixed_phrases))
        except TTSError as exc:
            self._last_error = str(exc)
            logger.error("tts_load_failed", provider="deepgram", voice=self.voice, error=str(exc))
            await self._client.aclose()
            self._client = None
            if isinstance(exc, TTSConfigError):
                raise
            raise TTSConfigError(f"Deepgram TTS unavailable at startup: {exc}") from exc
        self._ready = True
        logger.info(
            "tts_ready",
            provider="deepgram",
            voice=self.voice,
            load_ms=int((time.perf_counter() - started) * 1000),
            cached_phrases=len(self._pinned),
        )

    async def close(self) -> None:
        self._ready = False
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            name="deepgram",
            ready=self._ready,
            detail=f"Deepgram {self.voice}, {self.sample_rate} Hz" if self._ready else "not ready",
            last_error=self._last_error,
            last_latency_ms=self._last_latency_ms,
        )

    # --- HTTP --------------------------------------------------------------------------------

    def _key(self, normalized: str) -> str:
        return f"{self.voice}|{normalized}"

    async def _chunks(self, normalized: str) -> AsyncGenerator[bytes, None]:
        """One request: yields PCM byte chunks (sample-aligned). Raises TTSError subclasses."""
        assert self._client is not None
        params = {
            "model": self.voice,
            "encoding": "linear16",
            "sample_rate": str(SAMPLE_RATE),
            "container": "none",
        }
        try:
            async with self._client.stream(
                "POST", self._url, params=params, json={"text": normalized}
            ) as response:
                if response.status_code in (401, 403):
                    raise TTSConfigError(f"Deepgram rejected the API key ({response.status_code})")
                if response.status_code == 400:
                    body = (await response.aread())[:200].decode(errors="replace")
                    raise TTSConfigError(f"Deepgram refused the request (400): {body}")
                if response.status_code >= 300:
                    raise TTSSynthesisError(f"Deepgram returned HTTP {response.status_code}")
                carry = b""
                async for chunk in response.aiter_bytes():
                    data = carry + chunk
                    cut = len(data) - len(data) % 2  # never split a 16-bit sample
                    carry = data[cut:]
                    if cut:
                        yield self._level(data[:cut])
        except httpx.TimeoutException as exc:
            raise TTSTimeoutError("Deepgram request timed out") from exc
        except httpx.HTTPError as exc:
            raise TTSSynthesisError(f"Deepgram request failed: {type(exc).__name__}") from exc

    def _level(self, data: bytes) -> bytes:
        if not self.gain_db:
            return data
        return pcm.float_to_pcm16(pcm.gain_soft_limited(pcm.pcm16_to_float(data), self.gain_db))

    async def _open(
        self, normalized: str, call_attempt_id: str | None
    ) -> tuple[bytes, AsyncGenerator[bytes, None]]:
        """Start a request and wait for its first audio, retrying before any audio was sent."""
        last: TTSError | None = None
        for attempt in range(1, self.attempts + 1):
            started = time.perf_counter()
            chunks = self._chunks(normalized)
            try:
                first = await asyncio.wait_for(anext(chunks), timeout=self.first_byte_timeout_s)
            except StopAsyncIteration:
                return b"", chunks
            except TimeoutError:
                with contextlib.suppress(Exception):
                    await chunks.aclose()
                last = TTSTimeoutError(
                    f"no audio from Deepgram within {self.first_byte_timeout_s} s"
                )
            except TTSConfigError:
                raise
            except TTSError as exc:
                last = exc
            else:
                self._last_latency_ms = int((time.perf_counter() - started) * 1000)
                return first, chunks
            self._last_error = f"{type(last).__name__} (attempt {attempt})"
            logger.warning(
                "tts_synthesis_failed",
                provider="deepgram",
                call_attempt_id=call_attempt_id,
                attempt=attempt,
                error=type(last).__name__,
            )
        assert last is not None
        raise last

    async def _fetch(self, normalized: str, call_attempt_id: str | None = None) -> bytes:
        first, rest = await self._open(normalized, call_attempt_id)
        parts = [first]
        try:
            async for chunk in rest:
                parts.append(chunk)
        except TTSError as exc:
            raise TTSStreamInterruptedError(f"Deepgram stream broke: {exc}") from exc
        return b"".join(parts)

    async def _pinned_clip(self, normalized: str) -> AudioClip:
        """Fixed phrase: from the disk cache, or fetched, trimmed, normalized and saved."""
        path = None
        if self.cache_dir is not None:
            digest = hashlib.sha256(self._key(normalized).encode()).hexdigest()[:32]
            path = self.cache_dir / f"deepgram-{digest}.pcm"
            if path.is_file():
                return AudioClip.from_pcm(path.read_bytes(), SAMPLE_RATE)
        raw = await self._fetch(normalized)  # already gain-adjusted, like streamed audio
        audio = pcm.trim_silence(pcm.pcm16_to_float(raw), SAMPLE_RATE)
        data = pcm.float_to_pcm16(audio) if audio.size else b""
        if path is not None and data:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            except OSError as exc:  # a cache, not a requirement
                logger.warning("tts_cache_write_failed", path=str(path.parent), error=str(exc))
        return AudioClip.from_pcm(data, SAMPLE_RATE)

    # --- synthesis ---------------------------------------------------------------------------

    def _cached(self, normalized: str) -> AudioClip | None:
        key = self._key(normalized)
        if (clip := self._pinned.get(key)) is not None:
            return clip
        if (clip := self._lru.get(key)) is not None:
            self._lru.move_to_end(key)
        return clip

    def _remember(self, normalized: str, clip: AudioClip) -> None:
        self._lru[self._key(normalized)] = clip
        if len(self._lru) > LRU_SIZE:
            self._lru.popitem(last=False)

    def _require_ready(self) -> None:
        if not self._ready:
            raise TTSNotReadyError("Deepgram TTS is not initialized")

    async def synthesize(self, text: str, *, call_attempt_id: str | None = None) -> AudioClip:
        self._require_ready()
        normalized = self._normalize(text)
        if not normalized:
            return AudioClip.from_pcm(b"", SAMPLE_RATE)
        if (cached := self._cached(normalized)) is not None:
            return cached
        clip = AudioClip.from_pcm(await self._fetch(normalized, call_attempt_id), SAMPLE_RATE)
        self._remember(normalized, clip)
        self._log(normalized, clip, call_attempt_id)
        return clip

    async def stream(
        self, text: str, *, call_attempt_id: str | None = None
    ) -> AsyncIterator[AudioClip]:
        self._require_ready()
        normalized = self._normalize(text)
        if not normalized:
            return
        if (cached := self._cached(normalized)) is not None:
            yield cached
            return
        first, rest = await self._open(normalized, call_attempt_id)
        parts = [first]
        try:
            if first:
                yield AudioClip.from_pcm(first, SAMPLE_RATE)
            async for chunk in rest:
                parts.append(chunk)
                yield AudioClip.from_pcm(chunk, SAMPLE_RATE)
        except TTSError as exc:
            raise TTSStreamInterruptedError(f"Deepgram stream broke: {exc}") from exc
        finally:
            await rest.aclose()  # also when the caller stops early (barge-in, P6)
        clip = AudioClip.from_pcm(b"".join(parts), SAMPLE_RATE)
        self._remember(normalized, clip)
        self._log(normalized, clip, call_attempt_id)

    def _log(self, normalized: str, clip: AudioClip, call_attempt_id: str | None) -> None:
        logger.info(
            "tts_synthesized",
            provider="deepgram",
            call_attempt_id=call_attempt_id,
            chars=len(normalized),
            audio_ms=clip.duration_ms,
            first_audio_ms=self._last_latency_ms,
        )

    def apology_clip(self, *, call_attempt_id: str | None = None) -> AudioClip:
        clip = self._pinned.get(self._key(self._normalize(TECHNICAL_APOLOGY)))
        if clip is None:
            raise TTSNotReadyError("Deepgram TTS is not initialized")
        return clip
