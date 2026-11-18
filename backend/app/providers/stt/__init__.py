"""STT providers. `create_stt_provider` returns a new provider for one call session."""

from collections.abc import Sequence

from app.config import Settings
from app.providers.stt.base import STTConfigError, STTProvider


def default_keyterms(settings: Settings) -> list[str]:
    return [t.strip() for t in settings.deepgram_stt_keyterms.split(",") if t.strip()]


def create_stt_provider(settings: Settings, *, keyterms: Sequence[str] = ()) -> STTProvider:
    """A fresh Deepgram stream for one session (never share one between calls). `keyterms` are
    added to DEEPGRAM_STT_KEYTERMS, e.g. the job's company name and location."""
    if not settings.deepgram_api_key:
        raise STTConfigError("speech-to-text needs DEEPGRAM_API_KEY")
    from app.providers.stt.deepgram_provider import DeepgramSTTProvider

    return DeepgramSTTProvider(
        api_key=settings.deepgram_api_key.get_secret_value(),
        model=settings.deepgram_stt_model,
        language=settings.deepgram_stt_language,
        endpointing_ms=settings.deepgram_stt_endpointing_ms,
        utterance_end_ms=settings.deepgram_stt_utterance_end_ms,
        smart_format=settings.deepgram_stt_smart_format,
        keyterms=[*default_keyterms(settings), *keyterms],
    )
