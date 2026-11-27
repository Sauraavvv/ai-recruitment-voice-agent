"""LLM providers. Use `create_llm_provider` to get the configured one."""

from app.config import Settings
from app.providers.llm.base import LLMConfigError, LLMProvider


def create_llm_provider(settings: Settings) -> LLMProvider:
    if not (settings.openai_api_key and settings.openai_model):
        raise LLMConfigError("OPENAI_API_KEY and OPENAI_MODEL must be set")
    from app.providers.llm.openai_provider import OpenAIProvider

    return OpenAIProvider(
        settings.openai_api_key.get_secret_value(),
        settings.openai_model,
        reasoning_effort=settings.openai_reasoning_effort,
    )


def create_question_llm(settings: Settings) -> LLMProvider:
    """The model that writes telephonic round questions (Groq)."""
    keys = settings.groq_keys
    if not keys:
        raise LLMConfigError("GROQ_API_KEYS (or GROQ_API_KEY) must be set")
    from app.providers.llm.groq_provider import GroqProvider

    return GroqProvider(
        keys,
        settings.groq_model,
        reasoning_effort=settings.groq_reasoning_effort or None,
    )


def create_demo_llm(settings: Settings) -> LLMProvider:
    """The home page demo's screening agent: Groq first (fast, strict output schema). When every
    Groq key is at its limit (or Groq fails a turn), that turn switches to OpenAI, so the
    visitor's call carries on. Either one alone works too."""
    groq: LLMProvider | None = None
    if settings.groq_keys:
        from app.providers.llm.groq_provider import GroqProvider

        groq = GroqProvider(
            settings.groq_keys,
            settings.groq_model,
            reasoning_effort=settings.groq_call_reasoning_effort or None,
            max_retries=0,  # every key busy → switch now instead of waiting
            json_schema=True,
        )
    openai_ready = bool(settings.openai_api_key and settings.openai_model)
    if groq is None:
        if not openai_ready:
            raise LLMConfigError("Set GROQ_API_KEYS or OPENAI_API_KEY for the demo")
        return create_llm_provider(settings)
    if not openai_ready:
        return groq
    from app.providers.llm.fallback import FallbackLLM

    return FallbackLLM(
        groq,
        create_llm_provider(settings),
        fallback_timeout_s=settings.openai_timeout_s,
        names=("groq", "openai"),
    )


def create_call_llm(settings: Settings) -> LLMProvider:
    """The model for live telephonic round turns (Groq, phase-11 step 6b): low reasoning effort
    and no waiting rounds when every key is busy (the call moves on instead)."""
    keys = settings.groq_keys
    if not keys:
        raise LLMConfigError("GROQ_API_KEYS (or GROQ_API_KEY) must be set")
    from app.providers.llm.groq_provider import GroqProvider

    return GroqProvider(
        keys,
        settings.groq_model,
        reasoning_effort=settings.groq_call_reasoning_effort or None,
        max_retries=0,
    )
