from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

from app.intelligence.services.rate_limiter import get_rate_limiter

if TYPE_CHECKING:
    from app.intelligence.models.context import (
        ConversationContext,
        StudentContext,
        StudentProfile,
        ToolResultRef,
    )
    from app.intelligence.models.identity import BERU_IDENTITY, BeruIdentity
    from app.intelligence.providers.base import LLMProvider, LLMResponse
    from app.intelligence.services.attendance_service import AttendanceService
    from app.intelligence.services.context_builder import (
        ContextBuilder,
        create_student_context,
    )
    from app.intelligence.services.timetable_service import TimetableService
    from app.intelligence.tools.registry import (
        ToolDefinition,
        ToolRegistry,
        tool_registry,
    )
else:
    from app.intelligence.models.context import (
        ConversationContext,
        StudentContext,
        StudentProfile,
        ToolResultRef,
    )
    from app.intelligence.models.identity import BERU_IDENTITY, BeruIdentity
    from app.intelligence.providers.base import LLMProvider, LLMResponse
    from app.intelligence.services.attendance_service import AttendanceService
    from app.intelligence.services.context_builder import (
        ContextBuilder,
        create_student_context,
    )
    from app.intelligence.services.timetable_service import TimetableService
    from app.intelligence.tools.registry import (
        ToolDefinition,
        ToolRegistry,
        tool_registry,
    )


@dataclass(frozen=True, slots=True)
class IntentResult:
    """Result of intent interpretation."""

    intent: str | None = None
    entities: dict = field(default_factory=dict)
    requires_clarification: bool = False
    clarification_question: str | None = None
    clarification_candidates: tuple = ()
    tool_request: dict | None = None
    confidence: float = 0.0
    raw_response: str | None = None


class ConversationService:
    """
    Service for managing conversations and interpreting user messages.

    This is the main entry point for the intelligence pipeline.
    """

    def __init__(
        self,
        tool_registry_instance: ToolRegistry | None = None,
        context_builder: ContextBuilder | None = None,
        llm_provider: LLMProvider | None = None,
        beru_identity: BeruIdentity | None = None,
        timetable_service: TimetableService | None = None,
        attendance_service: AttendanceService | None = None,
    ):
        self.tool_registry = tool_registry_instance or tool_registry
        self.context_builder = context_builder or ContextBuilder()
        self.llm_provider = llm_provider
        self.beru_identity = beru_identity or BERU_IDENTITY
        self.timetable_service = timetable_service
        self.attendance_service = attendance_service

    def create_student_context(
        self,
        student_id: UUID,
        profile: StudentProfile | None = None,
        conversation: "ConversationContext | None" = None,
    ) -> "StudentContext":
        """Create a new student context."""
        return create_student_context(
            student_id=student_id,
            profile=profile,
            conversation=conversation,
        )

    async def process_message(
        self,
        student_context: "StudentContext",
        message: str,
    ) -> tuple[str, "StudentContext"]:
        """
        Process a user message and return the response and updated context.

        This is the main entry point for processing user messages.
        """
        # Add user message to conversation first
        new_conv = student_context.conversation.add_message("user", message)
        student_context = StudentContext(
            student_id=student_context.student_id,
            profile=student_context.profile,
            conversation=new_conv,
        )

        # Step 1: Interpret intent
        intent_result = await self._interpret_intent(student_context, message)

        # Step 2: Handle based on intent result
        if intent_result.requires_clarification:
            return await self._handle_clarification(
                student_context, intent_result, message
            )

        if intent_result.tool_request:
            return await self._execute_tool(
                student_context, intent_result, user_message=message
            )

        # No tool needed - direct response
        response = intent_result.raw_response or (
            "I understand. Is there anything specific you'd like help with?"
        )
        new_conv = student_context.conversation.add_message("assistant", response)
        student_context = StudentContext(
            student_id=student_context.student_id,
            profile=student_context.profile,
            conversation=new_conv,
        )
        return response, student_context

    async def _interpret_intent(
        self,
        student_context: "StudentContext",
        message: str,
    ) -> "IntentResult":
        """Interpret the user's message to extract intent."""
        if not self.llm_provider:
            # Mock interpretation for testing
            return await self._mock_interpret_intent(student_context, message)

        # Rate limiting check
        limiter = get_rate_limiter()
        if limiter:
            limiter.check_limit(student_context.student_id)

        # Build context
        available_tools = self.tool_registry.get_all_definitions()
        tool_defs = [self._tool_def_to_dict(t) for t in available_tools]

        context_result = self.context_builder.build_context(
            student_context, message, tool_defs
        )

        # Add tool definitions to system prompt
        messages = context_result.messages
        system_prompt = context_result.system_prompt
        if self.tool_registry.list_tools():
            tool_descriptions = "\n".join(
                [
                    f"- {t.name}: {t.description}"
                    for t in available_tools
                ]
            )
            system_prompt += f"\n\nAvailable Tools:\n{tool_descriptions}"

        messages[0] = {"role": "system", "content": system_prompt}

        # Call LLM
        response = await self.llm_provider.chat_completion(
            messages=messages,
            tools=[self._tool_def_to_openai(t) for t in available_tools],
            tool_choice="auto",
        )

        return self._parse_intent_response(response)

    def _tool_def_to_dict(self, tool: "ToolDefinition") -> dict:
        return {
            "name": tool.name,
            "description": tool.description,
            "arguments_schema": tool.arguments_schema,
            "result_schema": tool.result_schema,
            "requires_authorization": tool.requires_authorization,
            "requires_confirmation": tool.requires_confirmation,
        }

    def _tool_def_to_openai(self, tool: "ToolDefinition") -> dict:
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

        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": schema,
            },
        }

    def _parse_intent_response(self, response: "LLMResponse") -> "IntentResult":
        if response.tool_calls:
            tc = response.tool_calls[0]
            return IntentResult(
                tool_request={
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": tc.arguments,
                },
                confidence=0.9,
            )
        return IntentResult(
            raw_response=response.content or "",
            confidence=0.5,
        )

    async def _mock_interpret_intent(
        self,
        student_context: "StudentContext",
        message: str,
    ) -> "IntentResult":
        """Mock intent interpretation for testing without LLM."""
        msg_lower = message.lower()

        # Simple keyword-based mock (only for testing!)
        if any(
            w in msg_lower
            for w in ["who are you", "what are you", "your name", "identity"]
        ):
            return IntentResult(
                raw_response=(
                    "I'm Beru, your personal college assistant. I help with "
                    "timetable, attendance, academic info, and college workflows."
                ),
                confidence=0.9,
            )

        if any(
            w in msg_lower
            for w in ["what can you", "capabilities", "help me", "what do you do"]
        ):
            caps = [
                c.name.replace("_", " ")
                for c in self.beru_identity.get_available_capabilities()
            ]
            return IntentResult(
                raw_response=(
                    f"I can help you with: {', '.join(caps)}. "
                    "What would you like to do?"
                ),
                confidence=0.9,
            )

        if any(
            w in msg_lower
            for w in ["timetable", "schedule", "classes", "what do i have"]
        ):
            # Check if needs lab batch
            needs_lab = False
            if self.timetable_service:
                needs_lab = await self.timetable_service.needs_lab_batch(
                    student_context.student_id
                )

            if needs_lab:
                return IntentResult(
                    intent="needs_lab_batch",
                    entities={},
                    requires_clarification=True,
                    clarification_question=(
                        "I found lab groups in your timetable. "
                        "Which lab batch are you in?"
                    ),
                    clarification_candidates=("Batch 1", "Batch 2"),
                    confidence=0.9,
                )

            if "tomorrow" in msg_lower:
                return IntentResult(
                    tool_request={
                        "name": "get_tomorrow_schedule",
                        "arguments": {"student_id": str(student_context.student_id)},
                    },
                    confidence=0.9,
                )
            return IntentResult(
                tool_request={
                    "name": "get_today_schedule",
                    "arguments": {"student_id": str(student_context.student_id)},
                },
                confidence=0.9,
            )

        if any(w in msg_lower for w in ["next class", "what's next", "upcoming class"]):
            return IntentResult(
                tool_request={
                    "name": "get_next_class",
                    "arguments": {"student_id": str(student_context.student_id)},
                },
                confidence=0.9,
            )

        if "first class tomorrow" in msg_lower or "tomorrow first" in msg_lower:
            return IntentResult(
                tool_request={
                    "name": "get_first_class_tomorrow",
                    "arguments": {"student_id": str(student_context.student_id)},
                },
                confidence=0.9,
            )

        if any(w in msg_lower for w in ["attendance", "how many classes"]):
            return IntentResult(
                intent="get_attendance",
                entities={},
                confidence=0.8,
            )

        if ("skip" in msg_lower or "miss" in msg_lower) and any(
            w in msg_lower for w in ["class", "first", "second", "period"]
        ):
            return IntentResult(
                intent="simulate_absence",
                entities={"target": "first" if "first" in msg_lower else "unspecified"},
                requires_clarification=True,
                clarification_question=(
                    "Which class do you want to simulate skipping?"
                ),
                clarification_candidates=(
                    "first class",
                    "second class",
                    "all classes",
                ),
                confidence=0.7,
            )

        return IntentResult(
            raw_response=(
                "I'm not sure what you mean. Could you rephrase? I can help "
                "with timetable, attendance, simulations, and more."
            ),
            confidence=0.3,
        )

    async def _handle_clarification(
        self,
        student_context: "StudentContext",
        intent_result: "IntentResult",
        message: str,
    ) -> tuple[str, "StudentContext"]:
        """Handle a pending clarification."""
        # Add user message
        new_conv = student_context.conversation.add_message("user", message)

        # If there was a pending clarification, resolve it
        if student_context.conversation.pending_clarification:
            pending = student_context.conversation.pending_clarification

            # Find matching candidate
            matched = None
            for c in pending.candidates:
                if c.lower() in message.lower():
                    matched = c
                    break

            if matched:
                # Resolve the clarification
                new_conv = new_conv.clear_pending_clarification()

                # Handle lab batch clarification
                if (
                    pending.question
                    and "lab batch" in pending.question.lower()
                    and self.timetable_service
                ):
                    from app.models.timetable import LabBatch

                    batch = LabBatch.BATCH_1 if "1" in matched else LabBatch.BATCH_2
                    await self.timetable_service.set_lab_batch(
                        student_context.student_id, batch
                    )
                    response = (
                        f"Lab batch set to {matched}. Slash-separated labs resolved. "
                        "Please review your timetable and confirm when ready."
                    )
                    new_conv = new_conv.add_message("assistant", response)
                    return response, StudentContext(
                        student_id=student_context.student_id,
                        profile=student_context.profile,
                        conversation=new_conv,
                    )

                # Re-interpret with resolved entity
                resolved_message = f"{pending.original_message} {matched}"
                return await self.process_message(
                    StudentContext(
                        student_id=student_context.student_id,
                        profile=student_context.profile,
                        conversation=new_conv,
                    ),
                    resolved_message,
                )

            # No match - ask again
            response = (
                "I didn't understand. Please choose from: "
                f"{', '.join(pending.candidates)}"
            )
            new_conv = new_conv.add_message("assistant", response)
            return response, student_context

        return "I'm not sure what you mean.", student_context

    async def _execute_tool(
        self,
        student_context: "StudentContext",
        intent_result: "IntentResult",
        user_message: str = "",
    ) -> tuple[str, "StudentContext"]:
        """Execute a tool and return the response."""
        tool_req = intent_result.tool_request
        if not tool_req:
            return "No tool requested.", student_context

        tool = self.tool_registry.get(tool_req["name"])

        if not tool:
            response = f"Unknown tool: {tool_req['name']}"
            new_conv = student_context.conversation.add_message("assistant", response)
            return response, student_context

        try:
            # Handle timetable tools with TimetableService
            timetable_tools = {
                "confirm_timetable",
                "get_schedule",
                "get_today_schedule",
                "get_tomorrow_schedule",
                "get_next_class",
                "get_first_class_tomorrow",
                "get_timetable_status",
                "needs_lab_batch",
                "set_lab_batch",
            }

            # Attendance tools that may need TimetableService or AttendanceService
            attendance_tools = {
                "simulate_absence",
                "get_overall_attendance",
                "get_subject_attendance",
                "get_attendance_summary",
                "get_subjects_below_target",
                "calculate_classes_needed",
                "get_attendance_snapshot_info",
                "get_subject_codes",
                "sync_attendance",
            }

            # Sanitize arguments: remove student_id if supplied by LLM
            clean_arguments = {
                k: v
                for k, v in tool_req.get("arguments", {}).items()
                if k != "student_id"
            }

            if tool_req["name"] in timetable_tools and self.timetable_service:
                from app.intelligence.tools.timetable_tools import (
                    execute_timetable_tool,
                )

                result = await execute_timetable_tool(
                    self.timetable_service,
                    tool_req["name"],
                    str(student_context.student_id),
                    **clean_arguments,
                )
            elif tool_req["name"] in attendance_tools and self.attendance_service:
                from app.intelligence.tools.attendance_tools import (
                    execute_attendance_tool,
                )

                result = await execute_attendance_tool(
                    self.attendance_service,
                    self.timetable_service,
                    tool_req["name"],
                    str(student_context.student_id),
                    **clean_arguments,
                )
            else:
                result = await tool.execute(
                    student_id=student_context.student_id,
                    arguments=clean_arguments,
                )

            # Format tool result
            tool_result = ToolResultRef(
                tool_name=tool_req["name"],
                arguments=clean_arguments,
                result_summary=str(result)[:200],
                success=True,
            )
            new_conv = student_context.conversation.add_tool_result(tool_result)

            # Generate response from tool result
            if self.llm_provider:
                # Use LLM to generate natural response
                response = await self._generate_response_from_tool_result(
                    student_context, tool_req["name"], result, user_message=user_message
                )
            else:
                response = f"Done! {result}"

            new_conv = new_conv.add_message("assistant", response)
            return response, StudentContext(
                student_id=student_context.student_id,
                profile=student_context.profile,
                conversation=new_conv,
            )

        except Exception as e:
            error_result = ToolResultRef(
                tool_name=tool_req["name"],
                arguments=tool_req.get("arguments", {}),
                result_summary=str(e),
                success=False,
            )
            new_conv = student_context.conversation.add_tool_result(error_result)
            response = f"Error executing {tool_req['name']}: {e!s}"
            new_conv = new_conv.add_message("assistant", response)
            return response, student_context

    async def _generate_response_from_tool_result(
        self,
        student_context: "StudentContext",
        tool_name: str,
        result: dict,
        user_message: str = "",
    ) -> str:
        """Generate natural language response from tool result."""
        if not self.llm_provider:
            return str(result)

        student_name = student_context.profile.get_display_name() or "student"
        system = (
            f"You are {self.beru_identity.name}, a helpful and friendly "
            f"AI college copilot talking directly to {student_name}.\n"
            "You just executed an action or retrieved data using the system tool: "
            f"{tool_name}.\n"
            "Present the outcome and information naturally, warmly, and concisely.\n"
            "Be conversational and direct. Never read out raw JSON or technical keys.\n"
            "Never ask the student for their student ID "
            "or internal database identifiers; "
            "you are already talking directly to the "
            "authenticated student.\n"
            "If an action succeeded (such as setting their lab batch or "
            "confirming their timetable), clearly acknowledge it and guide "
            "them on what to do next if needed."
        )
        user_prompt = (
            f"Student asked: {user_message}\n\n"
            f"System Data (Tool: {tool_name}):\n{result}\n\n"
            "Reply conversationally to the student:"
        ) if user_message else (
            f"System Data (Tool: {tool_name}):\n{result}\n\n"
            "Summarize this conversationally for the student:"
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ]

        response = await self.llm_provider.chat_completion(messages=messages)
        return response.content or str(result)

    def get_conversation_summary(self, student_context: "StudentContext") -> str:
        """Get a summary of the current conversation state."""
        conv = student_context.conversation
        return (
            f"Conversation {conv.conversation_id} for "
            f"{student_context.profile.get_display_name()}\n"
            f"Messages: {len(conv.recent_messages)}\n"
            f"Active Intent: {conv.active_intent or 'none'}\n"
            f"Pending Clarification: {conv.pending_clarification is not None}\n"
            f"Referenced Entities: {len(conv.referenced_entities)}"
        )
