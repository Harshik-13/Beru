from app.intelligence.models.context import (
    ConversationContext,
    PendingClarification,
    ReferencedEntity,
    StudentContext,
    StudentProfile,
    ToolResultRef,
)
from app.intelligence.models.identity import (
    BERU_IDENTITY,
    BeruIdentity,
    Capability,
    CapabilityStatus,
)
from app.intelligence.providers.base import (
    LLMProvider,
    LLMProviderConfig,
    LLMProviderRegistry,
    llm_provider_registry,
)
from app.intelligence.providers.mock import MockLLMProvider, create_mock_llm
from app.intelligence.services.context_builder import (
    ContextBuilder,
    create_student_context,
)
from app.intelligence.services.conversation import ConversationService, IntentResult
from app.intelligence.tools.mock_tools import (
    GetBeruIdentityHandler,
    GetCurrentContextHandler,
    GetUserContextHandler,
    register_mock_tools,
)
from app.intelligence.tools.registry import (
    ToolDefinition,
    ToolHandler,
    ToolRegistry,
    tool_registry,
)

__all__ = [
    # Models
    "BeruIdentity",
    "BERU_IDENTITY",
    "Capability",
    "CapabilityStatus",
    "StudentProfile",
    "StudentContext",
    "ConversationContext",
    "ReferencedEntity",
    "PendingClarification",
    "ToolResultRef",
    # Services
    "ContextBuilder",
    "create_student_context",
    "ConversationService",
    "IntentResult",
    # Providers
    "LLMProvider",
    "LLMProviderConfig",
    "LLMProviderRegistry",
    "llm_provider_registry",
    "MockLLMProvider",
    "create_mock_llm",
    # Tools
    "ToolDefinition",
    "ToolHandler",
    "ToolRegistry",
    "tool_registry",
    "GetBeruIdentityHandler",
    "GetUserContextHandler",
    "GetCurrentContextHandler",
    "register_mock_tools",
]
