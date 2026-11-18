"""Primary TTS with a fallback: Deepgram Aura first, local Kitten when Deepgram can't answer.

Rules:
- A sentence the primary can't deliver (error, or no audio within its first-byte timeout) is
  spoken by the fallback instead.
- Sticky per call: once a call has fallen back, the rest of that call uses the fallback, so the
  candidate doesn't hear the voice switch back and forth.
- Circuit breaker: after `max_failures` consecutive primary failures, the primary is skipped for
  `open_s` seconds (new calls start on the fallback), then tried again.
- If the primary stream breaks after some audio was already sent, the whole sentence is spoken
  again by the fallback. Rare, and better than an unfinished sentence.
- Ready if either provider is ready. Calls still need speech, so both failing is a startup error.
"""

import asyncio
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable

from app.providers.tts.base import (
    AudioClip,
    ProviderStatus,
    TTSConfigError,
    TTSError,
    TTSNotReadyError,
    TTSProvider,
)
from app.utils.log import get_logger

logger = get_logger(__name__)

STICKY_CALLS_KEPT = 1000
PRIMARY_RETRY_S = 60.0  # a primary that failed at startup is retried this often


class FallbackTTSProvider(TTSProvider):
    def __init__(
        self,
        primary: TTSProvider,
        fallback: TTSProvider,
        *,
        max_failures: int = 3,
        open_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if primary.sample_rate != fallback.sample_rate:
            raise TTSConfigError(
                f"sample rates differ: {primary.sample_rate} vs {fallback.sample_rate} Hz"
            )
        self.sample_rate = primary.sample_rate
        self.primary = primary
        self.fallback = fallback
        self.max_failures = max_failures
        self.open_s = open_s
        self._now = clock
        self._failures = 0
        self._open_until = 0.0
        self._sticky: OrderedDict[str, None] = OrderedDict()
        self._primary_ready = False
        self._fallback_ready = False
        self._next_primary_retry = 0.0
        self._revive: asyncio.Task[None] | None = None

    # --- lifecycle ---------------------------------------------------------------------------

    async def initialize(self) -> None:
        results = await asyncio.gather(
            self.primary.initialize(), self.fallback.initialize(), return_exceptions=True
        )
        self._primary_ready = not isinstance(results[0], BaseException)
        self._fallback_ready = not isinstance(results[1], BaseException)
        self._next_primary_retry = self._now() + PRIMARY_RETRY_S
        for name, result in zip(("primary", "fallback"), results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("tts_component_unavailable", component=name, error=str(result))
        if not (self._primary_ready or self._fallback_ready):
            raise TTSConfigError(f"no TTS available: primary {results[0]}; fallback {results[1]}")

    async def close(self) -> None:
        if self._revive is not None:
            self._revive.cancel()
        await asyncio.gather(self.primary.close(), self.fallback.close())

    def _maybe_revive_primary(self) -> None:
        """Primary failed at startup: try it again in the background, at most every minute."""
        if self._primary_ready or self._now() < self._next_primary_retry:
            return
        if self._revive is not None and not self._revive.done():
            return
        self._next_primary_retry = self._now() + PRIMARY_RETRY_S

        async def revive() -> None:
            try:
                await self.primary.initialize()
            except Exception as exc:
                logger.warning("tts_primary_still_unavailable", error=str(exc))
            else:
                self._primary_ready = True
                self._failures = 0
                logger.info("tts_primary_recovered")

        self._revive = asyncio.create_task(revive(), name="tts-primary-revive")

    def status(self) -> ProviderStatus:
        p, f = self.primary.status(), self.fallback.status()
        state = "circuit open, using fallback" if self._circuit_open() else "primary first"
        return ProviderStatus(
            name=f"{p.name}+{f.name}",
            ready=p.ready or f.ready,
            detail=f"{state}; primary: {p.detail}; fallback: {f.detail}",
            last_error=p.last_error or f.last_error,
            last_latency_ms=p.last_latency_ms,
            model_loads=f.model_loads,
            components=(p, f),
        )

    # --- routing -----------------------------------------------------------------------------

    def _circuit_open(self) -> bool:
        return self._now() < self._open_until

    def _use_fallback(self, call_attempt_id: str | None) -> bool:
        if not self._primary_ready:
            self._maybe_revive_primary()
            return True
        if not self._fallback_ready:
            return False
        return self._circuit_open() or (
            call_attempt_id is not None and call_attempt_id in self._sticky
        )

    def _primary_failed(self, exc: Exception, call_attempt_id: str | None) -> None:
        self._failures += 1
        if call_attempt_id is not None:
            self._sticky[call_attempt_id] = None
            if len(self._sticky) > STICKY_CALLS_KEPT:
                self._sticky.popitem(last=False)
        if self._failures >= self.max_failures and not self._circuit_open():
            self._open_until = self._now() + self.open_s
            logger.warning("tts_circuit_open", seconds=self.open_s, failures=self._failures)
        logger.warning(
            "tts_fallback_used",
            call_attempt_id=call_attempt_id,
            error=type(exc).__name__,
            consecutive_failures=self._failures,
        )

    def _primary_ok(self) -> None:
        self._failures = 0

    def is_on_fallback(self, call_attempt_id: str) -> bool:
        return self._use_fallback(call_attempt_id)

    def forget_call(self, call_attempt_id: str) -> None:
        """Call ended: drop its sticky state."""
        self._sticky.pop(call_attempt_id, None)

    # --- synthesis ---------------------------------------------------------------------------

    async def synthesize(self, text: str, *, call_attempt_id: str | None = None) -> AudioClip:
        if not self._fallback_ready and not self._primary_ready:
            raise TTSNotReadyError("TTS is not loaded")
        if not self._use_fallback(call_attempt_id):
            try:
                clip = await self.primary.synthesize(text, call_attempt_id=call_attempt_id)
            except TTSError as exc:
                if not self._fallback_ready:
                    raise
                self._primary_failed(exc, call_attempt_id)
            else:
                self._primary_ok()
                return clip
        return await self.fallback.synthesize(text, call_attempt_id=call_attempt_id)

    async def stream(
        self, text: str, *, call_attempt_id: str | None = None
    ) -> AsyncIterator[AudioClip]:
        if not self._fallback_ready and not self._primary_ready:
            raise TTSNotReadyError("TTS is not loaded")
        if not self._use_fallback(call_attempt_id):
            try:
                async for clip in self.primary.stream(text, call_attempt_id=call_attempt_id):
                    yield clip
            except TTSError as exc:
                if not self._fallback_ready:
                    raise
                self._primary_failed(exc, call_attempt_id)
            else:
                self._primary_ok()
                return
        async for clip in self.fallback.stream(text, call_attempt_id=call_attempt_id):
            yield clip

    def apology_clip(self, *, call_attempt_id: str | None = None) -> AudioClip:
        """In the voice the call is using; the fallback's if the primary has none."""
        order = (
            (self.fallback, self.primary)
            if self._use_fallback(call_attempt_id)
            else (self.primary, self.fallback)
        )
        for provider in order:
            try:
                return provider.apology_clip(call_attempt_id=call_attempt_id)
            except TTSNotReadyError:
                continue
        raise TTSNotReadyError("TTS is not loaded")
