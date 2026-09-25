from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LLMMessage:
    """A message in the LLM conversation."""

    role: str  # "system", "user", "assistant", "tool"
    content: str
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True, slots=True)
class LLMToolCall:
    """A tool call requested by the LLM."""

    id: str
    name: str
    arguments: dict


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """A response from the LLM."""

    content: str | None = None
    tool_calls: tuple = ()
    finish_reason: str = "stop"
    usage: dict | None = None


@dataclass(frozen=True, slots=True)
class LLMProviderConfig:
    """Configuration for an LLM provider."""

    provider_name: str
    model: str
    config: dict


class LLMProvider(ABC):
    """
    Abstract interface for LLM providers.

    The core application depends only on this interface, not on any
    specific provider implementation (OpenAI, Anthropic, etc.).
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique provider identifier (e.g., 'openai', 'anthropic', 'mock')."""
        ...

    @property
    @abstractmethod
    def supported_models(self) -> tuple[str, ...]:
        """Models supported by this provider."""
        ...

    @abstractmethod
    async def initialize(self, config: LLMProviderConfig) -> None:
        """Initialize the provider with configuration."""
        ...

    @abstractmethod
    async def chat_completion(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """
        Generate a chat completion.

        Args:
            messages: The conversation messages
            tools: Available tool definitions
            tool_choice: "auto", "none", or specific tool name
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum tokens in response

        Returns:
            LLMResponse with content and/or tool_calls
        """
        ...

    @abstractmethod
    async def structured_completion(
        self,
        messages: list[LLMMessage],
        response_schema: dict,
        tools: list[dict] | None = None,
        temperature: float = 0.1,
    ) -> dict:
        """
        Generate a structured completion matching the given schema.

        Args:
            messages: The conversation messages
            response_schema: JSON schema for the response
            tools: Available tool definitions
            temperature: Sampling temperature

        Returns:
            Parsed structured response matching the schema
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the provider and release resources."""
        ...


class LLMProviderRegistry:
    """Registry for LLM provider implementations."""

    def __init__(self):
        self._providers: dict[str, type] = {}

    def register(self, provider_class: type) -> None:
        """Register a provider implementation."""
        instance = provider_class()
        self._providers[instance.provider_name] = provider_class

    def get(self, provider_name: str) -> type:
        """Get a registered provider class by name."""
        if provider_name not in self._providers:
            raise ValueError(f"Provider not registered: {provider_name}")
        return self._providers[provider_name]

    def list_providers(self) -> list[str]:
        """List registered provider names."""
        return list(self._providers.keys())


# Global registry instance
llm_provider_registry = LLMProviderRegistry()
