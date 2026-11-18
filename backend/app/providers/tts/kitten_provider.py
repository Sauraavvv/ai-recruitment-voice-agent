"""Kitten TTS 2 nano (English) behind `TTSProvider`.

- One model per process, loaded by `initialize()` (FastAPI lifespan) and warmed up. It is never
  reloaded: `model_loads_total()` counts loads so tests can prove it.
- Inference runs on a dedicated thread pool (one worker per concurrent call), never on the event
  loop. ONNX Runtime releases the GIL; the text front end (spaCy/misaki) is serialized by a lock.
- `synthesize()` normalizes agent text for speech, retries once on error or timeout, then raises.
  Fixed phrases (acknowledgements, closings, the technical apology) are pre-synthesized at startup.
- Output: mono int16 PCM at 24 kHz, silence-trimmed (50 ms padding) and peak-normalized to −3 dBFS.

Relies on two kittenml internals, pinned by version: the English G2P `Fallback` class (replaced
by an ONNX one, see g2p_onnx.py) and `KittenTTS2Tiny._chunk` (run outside the front-end lock).
"""

import asyncio
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from app.providers.tts.base import (
    AudioClip,
    ProviderStatus,
    TTSConfigError,
    TTSNotReadyError,
    TTSProvider,
    TTSSynthesisError,
    TTSTimeoutError,
)
from app.utils.log import get_logger
from app.voice import pcm
from app.voice.chunker import split_into_chunks
from app.voice.text_normalizer import TextNormalizer, default_normalizer

logger = get_logger(__name__)

MODEL_NAME = "kitten-tts-2-nano"
EXPECTED_SAMPLE_RATE = 24000
DEFAULT_VOICE = "Iris"  # chosen by the user in the Phase 3 listening test (docs/benchmarks/tts.md)
_BACKEND_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MODEL_DIRS = (Path("/opt/models") / MODEL_NAME, _BACKEND_ROOT / "models" / MODEL_NAME)

MAX_CHUNK_CHARS = 400  # longer text is split by the chunker first
CHUNK_GAP_MS = 150  # pause between chunks of one long text (Kitten's own value)
LRU_SIZE = 64
WARM_UP_TEXT = "Hello, this is a warm up sentence."
TECHNICAL_APOLOGY = "Sorry, I'm having a technical problem. We'll call you back."

_loads_total = 0
_loads_lock = threading.Lock()


def model_loads_total() -> int:
    """tts_model_loads_total: how many times a Kitten model was loaded in this process."""
    return _loads_total


class KittenEngine(Protocol):
    sample_rate: int
    voices: list[str]

    def speak(self, text: str) -> np.ndarray: ...


class _KittenTinyEngine:
    """The real model: kittenml's KittenTTS2Tiny with our ONNX G2P fallback."""

    def __init__(self, model_dir: Path, voice: str, threads: int) -> None:
        from app.providers.tts import g2p_onnx

        g2p_onnx.install()
        from kittenml.kittentts2_tiny import KittenTTS2Tiny

        self._model: Any = KittenTTS2Tiny(str(model_dir), threads=threads)
        self.sample_rate = int(self._model.sample_rate)
        self.voices = list(self._model.available_voices.get("en", []))
        matches = [v for v in self.voices if v.casefold() == voice.casefold()]
        if not matches:
            raise TTSConfigError(f"unknown KITTEN_VOICE {voice!r}; English voices: {self.voices}")
        self._lang, self._key = self._model.resolve_voice(matches[0], "en")
        self._frontend_lock = threading.Lock()

    def speak(self, text: str) -> np.ndarray:
        with self._frontend_lock:  # spaCy + misaki + the G2P memo are shared state
            chunks = self._model.phonemize(text, "en")
        parts = [
            self._model._chunk(self._lang, self._key, ps, 1.0, keep_start=(i == 0))
            for i, ps in enumerate(chunks)
        ]
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


EngineFactory = Callable[[Path, str, int], KittenEngine]


def resolve_model_dir(configured: str | None) -> Path:
    if configured:
        return Path(configured)
    for candidate in DEFAULT_MODEL_DIRS:
        if (candidate / "config.json").is_file():
            return candidate
    return DEFAULT_MODEL_DIRS[0]


class KittenTTSProvider(TTSProvider):
    def __init__(
        self,
        *,
        model_dir: Path,
        voice: str = DEFAULT_VOICE,
        threads: int = 2,
        max_workers: int = 1,
        timeout_s: float = 3.0,
        normalizer: TextNormalizer | None = None,
        fixed_phrases: Iterable[str] = (),
        engine_factory: EngineFactory | None = None,
    ) -> None:
        self.sample_rate = EXPECTED_SAMPLE_RATE
        self.model_dir = model_dir
        self.voice = voice
        self.threads = threads
        self.timeout_s = timeout_s
        self._normalize = normalizer or default_normalizer()
        self._fixed_phrases = [TECHNICAL_APOLOGY, *fixed_phrases]
        self._engine_factory: EngineFactory = engine_factory or _KittenTinyEngine
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tts")
        self._engine: KittenEngine | None = None
        self._pinned: dict[str, AudioClip] = {}
        self._lru: OrderedDict[str, AudioClip] = OrderedDict()
        self._last_error: str | None = None
        self._last_latency_ms: int | None = None
        self._loading = False

    # --- lifecycle ---------------------------------------------------------------------------

    def _load(self) -> KittenEngine:
        global _loads_total
        if not (self.model_dir / "config.json").is_file():
            raise TTSConfigError(
                f"no Kitten model at {self.model_dir} (set KITTEN_MODEL_PATH or run make tts-model)"
            )
        try:
            engine = self._engine_factory(self.model_dir, self.voice, self.threads)
        except TTSConfigError:
            raise
        except Exception as exc:
            raise TTSConfigError(f"Kitten model failed to load: {type(exc).__name__}") from exc
        with _loads_lock:
            _loads_total += 1
        if engine.sample_rate != EXPECTED_SAMPLE_RATE:
            raise TTSConfigError(
                f"model sample rate is {engine.sample_rate} Hz, expected {EXPECTED_SAMPLE_RATE}"
            )
        engine.speak(WARM_UP_TEXT)
        return engine

    async def initialize(self) -> None:
        if self._engine is not None:
            return
        self._loading = True
        started = time.perf_counter()
        loop = asyncio.get_running_loop()
        try:
            self._engine = await loop.run_in_executor(self._executor, self._load)
            for phrase in self._fixed_phrases:
                key = self._cache_key(self._normalize(phrase))
                self._pinned[key] = await self._synthesize_once(self._normalize(phrase), None)
        except Exception as exc:
            self._engine = None
            self._last_error = str(exc) if isinstance(exc, TTSConfigError) else type(exc).__name__
            logger.error("tts_load_failed", model=MODEL_NAME, error=self._last_error)
            if isinstance(exc, TTSConfigError):
                raise
            raise TTSConfigError(f"TTS warm-up failed: {self._last_error}") from exc
        finally:
            self._loading = False
        logger.info(
            "tts_ready",
            model=MODEL_NAME,
            voice=self.voice,
            threads=self.threads,
            load_ms=int((time.perf_counter() - started) * 1000),
            cached_phrases=len(self._pinned),
            model_loads_total=model_loads_total(),
        )

    async def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._engine = None
        self._pinned.clear()
        self._lru.clear()

    def status(self) -> ProviderStatus:
        if self._engine is not None:
            detail = f"{MODEL_NAME}, voice {self.voice}, {self.sample_rate} Hz"
        elif self._loading:
            detail = "loading"
        else:
            detail = "not loaded"
        return ProviderStatus(
            name="kitten",
            ready=self._engine is not None,
            detail=detail,
            last_error=self._last_error,
            last_latency_ms=self._last_latency_ms,
            model_loads=model_loads_total(),
        )

    # --- synthesis ---------------------------------------------------------------------------

    def _cache_key(self, normalized: str) -> str:
        return f"{self.voice.casefold()}|{normalized}"

    def _render(self, text: str) -> bytes:
        """Runs on the TTS thread pool."""
        assert self._engine is not None
        pieces = split_into_chunks(text) if len(text) > MAX_CHUNK_CHARS else [text]
        parts = [
            wav
            for piece in pieces
            if (
                wav := pcm.trim_silence(
                    pcm.as_mono_float(self._engine.speak(piece)), self.sample_rate
                )
            ).size
        ]
        if not parts:
            return b""
        gap = np.zeros(self.sample_rate * CHUNK_GAP_MS // 1000, dtype=np.float32)
        joined = parts[0]
        for part in parts[1:]:
            joined = np.concatenate([joined, gap, part])
        return pcm.float_to_pcm16(pcm.normalize_peak(joined))

    async def _synthesize_once(self, normalized: str, call_attempt_id: str | None) -> AudioClip:
        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        future = loop.run_in_executor(self._executor, self._render, normalized)
        data = await asyncio.wait_for(future, timeout=self.timeout_s)
        clip = AudioClip.from_pcm(data, self.sample_rate)
        self._last_latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "tts_synthesized",
            call_attempt_id=call_attempt_id,
            chars=len(normalized),
            audio_ms=clip.duration_ms,
            latency_ms=self._last_latency_ms,
        )
        return clip

    async def synthesize(
        self, text: str, *, call_attempt_id: str | None = None, cache: bool = True
    ) -> AudioClip:
        """`cache=False` always runs the model (benchmarks)."""
        if self._engine is None:
            raise TTSNotReadyError("TTS model is not loaded")
        normalized = self._normalize(text)
        if not normalized:
            return AudioClip.from_pcm(b"", self.sample_rate)
        key = self._cache_key(normalized)
        if cache and (cached := self._pinned.get(key)) is not None:
            return cached
        if cache and (cached := self._lru.get(key)) is not None:
            self._lru.move_to_end(key)
            return cached

        last_exc: Exception | None = None
        for attempt in (1, 2):
            try:
                clip = await self._synthesize_once(normalized, call_attempt_id)
            except Exception as exc:  # retried once, then reported
                last_exc = exc
                self._last_error = f"{type(exc).__name__} (attempt {attempt})"
                logger.warning(
                    "tts_synthesis_failed",
                    call_attempt_id=call_attempt_id,
                    attempt=attempt,
                    error=type(exc).__name__,
                )
                continue
            self._lru[key] = clip
            if len(self._lru) > LRU_SIZE:
                self._lru.popitem(last=False)
            return clip
        if isinstance(last_exc, TimeoutError):
            raise TTSTimeoutError(f"synthesis took over {self.timeout_s} s twice") from last_exc
        raise TTSSynthesisError(f"synthesis failed twice: {type(last_exc).__name__}") from last_exc

    def apology_clip(self) -> AudioClip:
        """Pre-synthesized 'Sorry, I'm having a technical problem…' for a call to end on (P6)."""
        clip = self._pinned.get(self._cache_key(self._normalize(TECHNICAL_APOLOGY)))
        if clip is None:
            raise TTSNotReadyError("TTS model is not loaded")
        return clip

    @property
    def cached_phrases(self) -> int:
        return len(self._pinned)
