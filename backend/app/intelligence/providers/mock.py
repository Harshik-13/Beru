from dataclasses import dataclass

from app.intelligence.providers.base import (
    LLMProvider,
    LLMProviderConfig,
    LLMResponse,
    LLMToolCall,
)


@dataclass
class MockLLMConfig:
    """Configuration for mock LLM behavior."""

    provider_name: str = "mock"
    default_intent: str | None = None
    default_entities: dict | None = None
    should_request_tool: bool = False
    tool_name: str | None = None
    tool_arguments: dict | None = None
    response_text: str | None = None
    should_clarify: bool = False
    clarification_question: str | None = None
    clarification_candidates: tuple = ()


class MockLLMProvider(LLMProvider):
    """
    Mock LLM provider for testing.

    This provider returns deterministic responses based on configuration.
    It does NOT make any external API calls.
    """

    def __init__(self):
        self._config = MockLLMConfig()
        self._initialized = False

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def supported_models(self) -> tuple[str, ...]:
        return ("mock", "mock-large", "mock-fast")

    async def initialize(self, config: LLMProviderConfig) -> None:
        self._initialized = True
        # Handle both LLMProviderConfig and MockLLMConfig
        if isinstance(config, MockLLMConfig):
            # Direct MockLLMConfig passed (for testing)
            self._config = config
        elif hasattr(config, "config") and config.config:
            for key, value in config.config.items():
                if hasattr(self._config, key):
                    setattr(self._config, key, value)

    def set_config(self, config: MockLLMConfig) -> None:
        """Set the mock configuration for the next call."""
        self._config = config

    def set_response_text(self, text: str) -> None:
        self._config.response_text = text

    def set_tool_call(self, tool_name: str, arguments: dict) -> None:
        self._config.should_request_tool = True
        self._config.tool_name = tool_name
        self._config.tool_arguments = arguments

    def set_clarification(self, question: str, candidates: tuple) -> None:
        self._config.should_clarify = True
        self._config.clarification_question = question
        self._config.clarification_candidates = candidates

    def set_intent(self, intent: str, entities: dict | None = None) -> None:
        self._config.default_intent = intent
        self._config.default_entities = entities or {}

    async def chat_completion(
        self,
        messages: list,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Generate a mock chat completion."""

        if self._config.should_clarify:
            return LLMResponse(
                content=self._config.clarification_question or "Please clarify.",
                finish_reason="stop",
            )

        if self._config.should_request_tool and self._config.tool_name:
            tool_call = LLMToolCall(
                id="mock-call-1",
                name=self._config.tool_name,
                arguments=self._config.tool_arguments or {},
            )
            return LLMResponse(
                tool_calls=(tool_call,),
                finish_reason="tool_calls",
            )

        if self._config.default_intent:
            return LLMResponse(
                content=(
                    f"[MOCK] Intent: {self._config.default_intent}, "
                    f"Entities: {self._config.default_entities}"
                ),
                finish_reason="stop",
            )

        if self._config.response_text:
            return LLMResponse(
                content=self._config.response_text,
                finish_reason="stop",
            )

        # Default response
        return LLMResponse(
            content=(
                "[MOCK] I'm a mock LLM. Configure me with "
                "set_response_text() or set_tool_call()."
            ),
            finish_reason="stop",
        )

    async def structured_completion(
        self,
        messages: list,
        response_schema: dict,
        tools: list[dict] | None = None,
        temperature: float = 0.1,
    ) -> dict:
        """Generate a mock structured completion."""
        return {"status": "mock", "data": "structured_response"}

    async def close(self) -> None:
        pass


# Factory function for easy test setup
def create_mock_llm(
    response_text: str | None = None,
    tool_name: str | None = None,
    tool_args: dict | None = None,
    intent: str | None = None,
    entities: dict | None = None,
    clarification_question: str | None = None,
    clarification_candidates: tuple = (),
) -> MockLLMProvider:
    """Create a pre-configured mock LLM provider."""
    provider = MockLLMProvider()

    if response_text:
        provider.set_response_text(response_text)
    elif tool_name:
        provider.set_tool_call(tool_name, tool_args or {})
    elif intent:
        provider.set_intent(intent, entities)
    elif clarification_question:
        provider.set_clarification(clarification_question, clarification_candidates)

    return provider
