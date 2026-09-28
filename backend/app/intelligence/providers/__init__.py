from app.core.config import settings
from app.intelligence.providers.base import (
    LLMMessage,
    LLMProvider,
    LLMProviderConfig,
    LLMResponse,
    LLMToolCall,
    llm_provider_registry,
)
from app.intelligence.providers.mock import MockLLMProvider, create_mock_llm
from app.intelligence.providers.openai_compatible import OpenAICompatibleLLMProvider

# Register providers
llm_provider_registry.register(MockLLMProvider)
llm_provider_registry.register(OpenAICompatibleLLMProvider)


async def create_llm_provider() -> "LLMProvider | None":
    """Create and initialize the LLM provider based on settings.

    Returns None if the provider is set to "mock" or not configured.
    """
    if not settings.llm_provider or settings.llm_provider == "mock":
        return None

    provider_class = llm_provider_registry.get(settings.llm_provider)
    provider = provider_class()

    await provider.initialize(LLMProviderConfig(
        provider_name=settings.llm_provider,
        model=settings.llm_model,
        config={
            "api_key": settings.llm_api_key,
            "base_url": settings.llm_base_url,
            "timeout_seconds": settings.llm_timeout_seconds,
            "max_retries": settings.llm_max_retries,
            "retry_base_delay": settings.llm_retry_base_delay,
        },
    ))

    return provider


__all__ = [
    "LLMMessage",
    "LLMProvider",
    "LLMProviderConfig",
    "LLMResponse",
    "LLMToolCall",
    "MockLLMProvider",
    "OpenAICompatibleLLMProvider",
    "create_llm_provider",
    "create_mock_llm",
    "llm_provider_registry",
]
