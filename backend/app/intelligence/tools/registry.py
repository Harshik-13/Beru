from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Definition of a tool that can be called by the LLM."""

    name: str
    description: str
    arguments_schema: dict[str, Any]  # JSON Schema for arguments
    result_schema: dict[str, Any]  # JSON Schema for result
    requires_authorization: bool = True
    requires_confirmation: bool = False
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class ToolRequest:
    """A tool call request from the LLM."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Result of a tool execution."""

    tool_name: str
    request_id: str
    success: bool
    result: dict[str, Any]
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
        arguments: dict[str, Any],
        conversation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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

    def __init__(self) -> None:
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


class BuiltinToolHandler(ToolHandler):
    """Tool handler for built-in tools."""

    def __init__(self, definition: ToolDefinition):
        self._definition = definition

    @property
    def definition(self) -> ToolDefinition:
        return self._definition

    async def execute(
        self,
        student_id: UUID,
        arguments: dict[str, Any],
        conversation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"student_id": str(student_id), **arguments}


def register_builtin_tools(registry: ToolRegistry | None = None) -> ToolRegistry:
    """Register all built-in timetable and attendance tools into the registry."""
    from app.intelligence.tools.attendance_tools import ATTENDANCE_TOOL_DEFINITIONS
    from app.intelligence.tools.timetable_tools import TIMETABLE_TOOL_DEFINITIONS

    reg = registry or tool_registry
    for d in TIMETABLE_TOOL_DEFINITIONS:
        if not reg.is_registered(d["name"]):
            reg.register(
                BuiltinToolHandler(
                    ToolDefinition(
                        name=d["name"],
                        description=d["description"],
                        arguments_schema=d.get("arguments_schema", {}),
                        result_schema=d.get("result_schema", {}),
                        requires_authorization=d.get("requires_authorization", True),
                        requires_confirmation=d.get("requires_confirmation", False),
                    )
                )
            )
    for d in ATTENDANCE_TOOL_DEFINITIONS:
        if not reg.is_registered(d["name"]):
            reg.register(
                BuiltinToolHandler(
                    ToolDefinition(
                        name=d["name"],
                        description=d["description"],
                        arguments_schema=d.get("arguments_schema", {}),
                        result_schema=d.get("result_schema", {}),
                        requires_authorization=d.get("requires_authorization", True),
                        requires_confirmation=d.get("requires_confirmation", False),
                    )
                )
            )
    return reg


# Global registry instance
tool_registry = ToolRegistry()
register_builtin_tools(tool_registry)
