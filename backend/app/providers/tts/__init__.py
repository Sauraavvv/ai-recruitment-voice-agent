"""TTS providers. Use `create_tts_provider` to get the configured one."""

from app.config import Settings
from app.providers.tts.base import TTSConfigError, TTSProvider

# Short acknowledgements Phase 6 plays instantly while the LLM thinks (phase-06 plan §5.8).
ACKNOWLEDGEMENTS = ("Okay.", "Got it.", "Thank you.", "Sure.", "Right.")


def fixed_phrases() -> list[str]:
    """Lines the agent says word for word, with no names in them: synthesized once at startup."""
    from app.agent import prompts

    return [
        *ACKNOWLEDGEMENTS,
        prompts.low_confidence(),
        prompts.llm_error_retry(),
        prompts.silence_prompt(None),
        prompts.silence_close(),
        prompts.callback_ask(),
        prompts.callback_vague_close(),
        prompts.opt_out_close(),
        prompts.wrong_person_close(),
        prompts.identity_unresolved_close(),
        prompts.escalate_close(),
        prompts.error_close(),
    ]


def use_deepgram(settings: Settings) -> bool:
    if settings.tts_provider == "kitten":
        return False
    if settings.tts_provider == "deepgram" and not settings.deepgram_api_key:
        raise TTSConfigError("TTS_PROVIDER=deepgram needs DEEPGRAM_API_KEY")
    return bool(settings.deepgram_api_key)


def create_tts_provider(settings: Settings) -> TTSProvider:
    """Deepgram Aura with Kitten as fallback when a Deepgram key is set (TTS_PROVIDER=auto),
    otherwise Kitten alone. See providers/tts/fallback.py for the switching rules."""
    from pathlib import Path

    from app.providers.tts.kitten_provider import (
        DEFAULT_VOICE,
        KittenTTSProvider,
        resolve_model_dir,
    )

    def kitten() -> KittenTTSProvider:
        return KittenTTSProvider(
            model_dir=resolve_model_dir(settings.kitten_model_path),
            voice=settings.kitten_voice or DEFAULT_VOICE,
            threads=settings.tts_threads,
            max_workers=settings.max_concurrent_calls,
            timeout_s=settings.tts_timeout_s,
            fixed_phrases=fixed_phrases(),
        )

    if not use_deepgram(settings):
        return kitten()

    from app.providers.tts import deepgram_provider
    from app.providers.tts.fallback import FallbackTTSProvider

    assert settings.deepgram_api_key is not None
    deepgram = deepgram_provider.DeepgramTTSProvider(
        api_key=settings.deepgram_api_key.get_secret_value(),
        voice=settings.deepgram_tts_voice or deepgram_provider.DEFAULT_VOICE,
        first_byte_timeout_s=settings.deepgram_tts_first_byte_timeout_s,
        gain_db=settings.deepgram_tts_gain_db,
        # With a fallback, don't spend a second timeout on a retry: switch at once.
        attempts=1 if settings.tts_fallback else 2,
        cache_dir=Path(settings.tts_cache_dir),
        fixed_phrases=fixed_phrases(),
    )
    if not settings.tts_fallback:
        return deepgram
    return FallbackTTSProvider(deepgram, kitten())
