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

    def to_dict(self) -> dict[str, Any]:
        return tool_def_to_dict(self)

    def to_openai_schema(self) -> dict[str, Any]:
        return tool_def_to_openai(self)


# Policy: Semantic Core Tools exposed to the LLM during conversational intent interpretation.
# All other registered tools are extended tools (accessible to backend services/tests, but hidden from LLM schemas).
CORE_TOOLS: frozenset[str] = frozenset({
    # Timetable core intents
    "get_today_schedule",
    "get_tomorrow_schedule",
    "get_schedule_for_weekday",
    "find_activity_details",
    "confirm_timetable",
    # Attendance core intents
    "get_overall_attendance",
    "get_attendance_summary",
    "calculate_bunk_allowance",
    "simulate_schedule_scenario",
    "set_attendance_target",
    "sync_attendance",
    "start_portal_connection",
})


def tool_def_to_dict(tool: ToolDefinition) -> dict[str, Any]:
    """Return full internal dictionary representation of ToolDefinition."""
    return {
        "name": tool.name,
        "description": tool.description,
        "arguments_schema": tool.arguments_schema,
        "result_schema": tool.result_schema,
        "requires_authorization": tool.requires_authorization,
        "requires_confirmation": tool.requires_confirmation,
        "enabled": tool.enabled,
    }


def tool_def_to_openai(tool: ToolDefinition) -> dict[str, Any]:
    """
    Convert a ToolDefinition to the minimal OpenAI function calling schema.

    Preserves clean separation: authorization, confirmation, and internal
    metadata remain on ToolDefinition and are not exposed in the LLM schema.
    """
    import copy

    schema = copy.deepcopy(tool.arguments_schema)
    if isinstance(schema, dict):
        props = schema.get("properties")
        if isinstance(props, dict) and "student_id" in props:
            del props["student_id"]
        req = schema.get("required")
        if isinstance(req, list) and "student_id" in req:
            req.remove("student_id")
        if isinstance(req, list) and not req:
            del schema["required"]

        # Providers like Groq strictly enforce types on tool arguments.
        # If an optional parameter is passed as null by the LLM, the schema must accept null.
        if isinstance(props, dict):
            required_props = set(schema.get("required", []))
            for prop_name, prop_def in props.items():
                if prop_name not in required_props and isinstance(prop_def, dict):
                    t = prop_def.get("type")
                    if isinstance(t, str) and t != "null":
                        prop_def["type"] = [t, "null"]
                    elif isinstance(t, list) and "null" not in t:
                        prop_def["type"] = list(t) + ["null"]

    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": schema,
        },
    }


def validate_tool_arguments(
    definition: ToolDefinition, arguments: dict[str, Any]
) -> str | None:
    """
    Validate tool arguments against the ToolDefinition's arguments_schema.

    Returns None if valid, or a descriptive error string if invalid.
    """
    schema = definition.arguments_schema
    if not isinstance(schema, dict):
        return None

    # 1. Required properties check (excluding backend-injected student_id)
    required = schema.get("required", [])
    if isinstance(required, list):
        for req_prop in required:
            if req_prop == "student_id":
                continue
            if req_prop not in arguments or arguments[req_prop] is None:
                return f"Missing required parameter: '{req_prop}'"

    # 2. Type checks on provided properties
    props = schema.get("properties", {})
    if isinstance(props, dict):
        for key, val in arguments.items():
            if key in props and isinstance(props[key], dict) and val is not None:
                expected_type = props[key].get("type")
                if isinstance(expected_type, str):
                    types = [expected_type]
                elif isinstance(expected_type, list):
                    types = expected_type
                else:
                    types = []

                type_matches = False
                for t in types:
                    if t == "string" and isinstance(val, str):
                        type_matches = True
                        break
                    elif (
                        t == "integer"
                        and isinstance(val, int)
                        and not isinstance(val, bool)
                    ):
                        type_matches = True
                        break
                    elif (
                        t == "number"
                        and isinstance(val, (int, float))
                        and not isinstance(val, bool)
                    ):
                        type_matches = True
                        break
                    elif t == "boolean" and isinstance(val, bool):
                        type_matches = True
                        break
                    elif t == "array" and isinstance(val, (list, tuple)):
                        type_matches = True
                        break
                    elif t == "object" and isinstance(val, dict):
                        type_matches = True
                        break
                    elif t == "null" and val is None:
                        type_matches = True
                        break

                if types and not type_matches:
                    return (
                        f"Invalid type for parameter '{key}': "
                        f"expected {expected_type}, got {type(val).__name__}"
                    )

    return None


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

    def get_core_tools(self) -> list[ToolDefinition]:
        """List active tool definitions designated as core for conversational LLM exposure."""
        return [
            h.definition
            for name, h in self._tools.items()
            if name in CORE_TOOLS and h.definition.enabled
        ]

    def is_core_tool(self, name: str) -> bool:
        """Check if a tool is designated as a core tool."""
        return name in CORE_TOOLS

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

