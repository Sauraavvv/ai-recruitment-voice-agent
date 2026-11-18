"""TTS providers. Use `create_tts_provider` to get the configured one."""

from app.config import Settings
from app.providers.tts.base import TTSProvider

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


def create_tts_provider(settings: Settings) -> TTSProvider:
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
        fixed_phrases=fixed_phrases(),
    )
