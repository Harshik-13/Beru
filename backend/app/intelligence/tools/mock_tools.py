from dataclasses import dataclass
from uuid import UUID

from app.intelligence.tools.registry import (
    ToolDefinition,
    ToolHandler,
    ToolRegistry,
)


@dataclass(frozen=True, slots=True)
class BeruIdentityResult:
    """Result for get_beru_identity tool."""

    name: str
    full_name: str
    role: str
    purpose: str
    responsibilities: tuple[str, ...]
    available_capabilities: list[dict]
    planned_capabilities: list[dict]
    limitations: tuple[str, ...]


class GetBeruIdentityHandler(ToolHandler):
    """Tool to get Beru's identity information."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_beru_identity",
            description="Get Beru's identity, role, capabilities, and limitations",
            arguments_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            result_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "full_name": {"type": "string"},
                    "role": {"type": "string"},
                    "purpose": {"type": "string"},
                    "responsibilities": {"type": "array", "items": {"type": "string"}},
                    "available_capabilities": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["name", "description"],
                        },
                    },
                    "planned_capabilities": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["name", "description"],
                        },
                    },
                    "limitations": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "name",
                    "full_name",
                    "role",
                    "purpose",
                    "responsibilities",
                    "available_capabilities",
                    "planned_capabilities",
                    "limitations",
                ],
            },
            requires_authorization=False,
            requires_confirmation=False,
        )

    async def execute(
        self,
        student_id: UUID,
        arguments: dict,
        conversation_context: dict | None = None,
    ) -> dict:
        from app.intelligence.models.identity import BERU_IDENTITY

        beru = BERU_IDENTITY
        available = [
            {"name": c.name, "description": c.description}
            for c in beru.get_available_capabilities()
        ]
        planned = [
            {"name": c.name, "description": c.description}
            for c in beru.get_planned_capabilities()
        ]

        return {
            "name": beru.name,
            "full_name": beru.full_name,
            "role": beru.role,
            "purpose": beru.purpose,
            "responsibilities": list(beru.responsibilities),
            "available_capabilities": available,
            "planned_capabilities": planned,
            "limitations": list(beru.limitations),
        }


@dataclass(frozen=True, slots=True)
class StudentContextResult:
    """Result for get_user_context tool."""

    student_id: str
    display_name: str
    has_academic_info: bool
    academic_info: dict
    conversation_summary: dict


class GetUserContextHandler(ToolHandler):
    """Tool to get the current student's context."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_user_context",
            description="Get the current student's profile and conversation context",
            arguments_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            result_schema={
                "type": "object",
                "properties": {
                    "student_id": {"type": "string"},
                    "display_name": {"type": "string"},
                    "has_academic_info": {"type": "boolean"},
                    "academic_info": {"type": "object"},
                    "conversation_summary": {"type": "object"},
                },
                "required": ["student_id", "display_name", "has_academic_info"],
            },
            requires_authorization=True,
        )

    async def execute(
        self,
        student_id: UUID,
        arguments: dict,
        conversation_context: dict | None = None,
    ) -> dict:
        # In real implementation, this would get context from the conversation service
        # For mock, return placeholder
        return {
            "student_id": str(student_id),
            "display_name": "Test Student",
            "has_academic_info": False,
            "academic_info": {},
            "conversation_summary": {"message_count": 0, "active_intent": None},
        }


@dataclass(frozen=True, slots=True)
class CurrentContextResult:
    """Result for get_current_context tool."""

    active_intent: str | None
    pending_clarification: dict | None
    recent_tool_results: list[dict]
    referenced_entities: list[dict]


class GetCurrentContextHandler(ToolHandler):
    """Tool to get the current conversation context."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="get_current_context",
            description="Get the current conversation context including active intent and pending clarifications",
            arguments_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            result_schema={
                "type": "object",
                "properties": {
                    "active_intent": {"type": ["string", "null"]},
                    "pending_clarification": {"type": ["object", "null"]},
                    "recent_tool_results": {"type": "array"},
                    "referenced_entities": {"type": "array"},
                },
                "required": ["active_intent", "pending_clarification", "recent_tool_results", "referenced_entities"],
            },
            requires_authorization=True,
        )

    async def execute(
        self,
        student_id: UUID,
        arguments: dict,
        conversation_context: dict | None = None,
    ) -> dict:
        return {
            "active_intent": None,
            "pending_clarification": None,
            "recent_tool_results": [],
            "referenced_entities": [],
        }


def register_mock_tools(registry: ToolRegistry | None = None) -> ToolRegistry:
    """Register all mock tools for testing."""
    reg = registry or ToolRegistry()
    reg.register(GetBeruIdentityHandler())
    reg.register(GetUserContextHandler())
    reg.register(GetCurrentContextHandler())
    return reg
