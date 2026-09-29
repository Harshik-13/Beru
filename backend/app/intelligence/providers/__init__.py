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

# Provider default base URLs
PROVIDER_BASE_URL_DEFAULTS: dict[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "ollama": "http://localhost:11434/v1",
    "opencode_zen": "https://opencode.zen/api/v1",
    "openai_compatible": "https://api.openai.com/v1",
}

# Register default providers
llm_provider_registry.register(MockLLMProvider)
llm_provider_registry.register(OpenAICompatibleLLMProvider)


async def create_llm_provider() -> "LLMProvider | None":
    """Create and initialize the LLM provider based on settings.

    Returns None if the provider is set to "mock" or not configured.
    Supports 'openrouter', 'groq', 'openai', 'nvidia', 'ollama', 'opencode_zen',
    or generic 'openai_compatible'.
    """
    provider_name = (settings.llm_provider or "").strip().lower()
    if not provider_name or provider_name == "mock":
        return None

    # Resolve provider class
    if (
        provider_name in PROVIDER_BASE_URL_DEFAULTS
        or provider_name == "openai_compatible"
    ):
        provider: LLMProvider = OpenAICompatibleLLMProvider()
    else:
        provider_class = llm_provider_registry.get(provider_name)
        provider = provider_class()

    base_url = settings.llm_base_url or PROVIDER_BASE_URL_DEFAULTS.get(
        provider_name, "https://api.openai.com/v1"
    )

    await provider.initialize(LLMProviderConfig(
        provider_name=provider_name,
        model=settings.llm_model,
        config={
            "provider_name": provider_name,
            "model": settings.llm_model,
            "api_key": settings.llm_api_key,
            "base_url": base_url,
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
