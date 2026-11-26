"""TTS providers. Use `create_tts_provider` to get the configured one."""

from app.config import Settings
from app.providers.tts.base import TTSConfigError, TTSProvider

# Short acknowledgements Phase 6 plays instantly while the LLM thinks (phase-06 plan §5.8).
ACKNOWLEDGEMENTS = ("Okay.", "Got it.", "Thank you.", "Sure.", "Right.")
# Played once when the reply still hasn't started a while after the acknowledgement (P6)
HOLD_PHRASE = "One moment."


def fixed_phrases() -> list[str]:
    """Lines the agent says word for word, with no names in them: synthesized once at startup."""
    from app.agent import prompts

    return [
        *ACKNOWLEDGEMENTS,
        HOLD_PHRASE,
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


def create_tts_provider(settings: Settings) -> TTSProvider:
    """Which voice speaks:

    - TTS_PROVIDER=deepgram or auto (the default): Deepgram Aura over its API. With
      TTS_FALLBACK=true, Kitten as the fallback (only if its model is in the image).
    - TTS_PROVIDER=kitten: Kitten (local, switched off in the image for now) first, Deepgram as
      the fallback when a Deepgram key is set and TTS_FALLBACK=true.

    Raises TTSConfigError when the chosen voice has no key. With a fallback, the primary doesn't
    retry: the fallback takes the sentence at once (providers/tts/fallback.py)."""
    from pathlib import Path

    has_deepgram = bool(settings.deepgram_api_key)
    use_kitten = settings.tts_provider == "kitten"
    if not use_kitten and not has_deepgram:
        raise TTSConfigError("The API voice needs DEEPGRAM_API_KEY (or set TTS_PROVIDER=kitten)")
    with_fallback = settings.tts_fallback and has_deepgram

    def kitten(attempts: int) -> TTSProvider:
        # Imported only when chosen: the default (API) voice never loads the local model
        from app.providers.tts.kitten_provider import (
            DEFAULT_VOICE,
            KittenTTSProvider,
            resolve_model_dir,
        )

        return KittenTTSProvider(
            model_dir=resolve_model_dir(settings.kitten_model_path),
            voice=settings.kitten_voice or DEFAULT_VOICE,
            threads=settings.tts_threads,
            max_workers=settings.max_concurrent_calls,
            timeout_s=settings.tts_timeout_s,
            attempts=attempts,
            fixed_phrases=fixed_phrases(),
        )

    def deepgram(attempts: int) -> TTSProvider:
        from app.providers.tts import deepgram_provider

        assert settings.deepgram_api_key is not None
        return deepgram_provider.DeepgramTTSProvider(
            api_key=settings.deepgram_api_key.get_secret_value(),
            voice=settings.deepgram_tts_voice or deepgram_provider.DEFAULT_VOICE,
            first_byte_timeout_s=settings.deepgram_tts_first_byte_timeout_s,
            gain_db=settings.deepgram_tts_gain_db,
            attempts=attempts,
            cache_dir=Path(settings.tts_cache_dir),
            fixed_phrases=fixed_phrases(),
        )

    from app.providers.tts.fallback import FallbackTTSProvider

    if not use_kitten:
        if not settings.tts_fallback:
            return deepgram(attempts=2)
        return FallbackTTSProvider(deepgram(attempts=1), kitten(attempts=2))
    if not with_fallback:
        return kitten(attempts=2)
    return FallbackTTSProvider(kitten(attempts=1), deepgram(attempts=2))
