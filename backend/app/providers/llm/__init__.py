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
