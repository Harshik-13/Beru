from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Definition of a tool that can be called by the LLM."""

    name: str
    description: str
    arguments_schema: dict  # JSON Schema for arguments
    result_schema: dict  # JSON Schema for result
    requires_authorization: bool = True
    requires_confirmation: bool = False
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """A tool call request from the LLM."""

    id: str
    name: str
    arguments: dict


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Result of a tool execution."""

    tool_name: str
    request_id: str
    success: bool
    result: dict
    error: str | None = None
    user_facing_message: str | None = None


class ToolHandler(ABC):
    """
    Abstract base for tool handlers.

    Each tool must implement the execute method.
    """

    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        """Return the tool definition."""
        ...

    @abstractmethod
    async def execute(
        self,
        student_id: UUID,
        arguments: dict,
        conversation_context: dict | None = None,
    ) -> dict:
        """
        Execute the tool.

        Args:
            student_id: The authenticated student ID
            arguments: Validated tool arguments
            conversation_context: Optional conversation context

        Returns:
            Structured result matching the result_schema
        """
        ...


class ToolRegistry:
    """Registry of available tools."""

    def __init__(self):
        self._tools: dict[str, ToolHandler] = {}

    def register(self, handler: ToolHandler) -> None:
        """Register a tool handler."""
        self._tools[handler.definition.name] = handler

    def unregister(self, name: str) -> None:
        """Unregister a tool."""
        self._tools.pop(name, None)

    def get(self, name: str) -> ToolHandler | None:
        """Get a tool handler by name."""
        return self._tools.get(name)

    def get_definition(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by name."""
        handler = self._tools.get(name)
        return handler.definition if handler else None

    def list_tools(self) -> list[ToolDefinition]:
        """List all tool definitions."""
        return [h.definition for h in self._tools.values() if h.definition.enabled]

    def get_all_definitions(self) -> list[ToolDefinition]:
        """Get all tool definitions (including disabled)."""
        return [h.definition for h in self._tools.values()]

    def is_registered(self, name: str) -> bool:
        return name in self._tools


# Global registry instance
tool_registry = ToolRegistry()
