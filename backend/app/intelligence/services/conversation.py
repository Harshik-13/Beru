from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from app.intelligence.models.context import (
        ConversationContext,
        StudentContext,
        StudentProfile,
        ToolResultRef,
    )
    from app.intelligence.models.identity import BERU_IDENTITY, BeruIdentity
    from app.intelligence.providers.base import LLMProvider, LLMResponse
    from app.intelligence.services.context_builder import (
        ContextBuilder,
        create_student_context,
    )
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
    from app.intelligence.services.context_builder import (
        ContextBuilder,
        create_student_context,
    )
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
    ):
        self.tool_registry = tool_registry_instance or tool_registry
        self.context_builder = context_builder or ContextBuilder()
        self.llm_provider = llm_provider
        self.beru_identity = beru_identity or BERU_IDENTITY

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
            return await self._execute_tool(student_context, intent_result)

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
                    f"- {t.name}: {t.description} (args: {t.arguments_schema})"
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
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.arguments_schema,
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
            return IntentResult(
                intent="get_timetable",
                entities={"period": "tomorrow" if "tomorrow" in msg_lower else "today"},
                confidence=0.8,
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
            else:
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
    ) -> tuple[str, "StudentContext"]:
        """Execute a tool and return the response."""
        tool_req = intent_result.tool_request
        tool = self.tool_registry.get(tool_req["name"])

        if not tool:
            response = f"Unknown tool: {tool_req['name']}"
            new_conv = student_context.conversation.add_message("assistant", response)
            return response, student_context

        try:
            result = await tool.execute(
                student_id=student_context.student_id,
                arguments=tool_req["arguments"],
            )

            # Format tool result
            tool_result = ToolResultRef(
                tool_name=tool_req["name"],
                arguments=tool_req["arguments"],
                result_summary=str(result)[:200],
                success=True,
            )
            new_conv = student_context.conversation.add_tool_result(tool_result)

            # Generate response from tool result
            if self.llm_provider:
                # Use LLM to generate natural response
                response = await self._generate_response_from_tool_result(
                    student_context, tool_req["name"], result
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
                arguments=tool_req["arguments"],
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
    ) -> str:
        """Generate natural language response from tool result."""
        if not self.llm_provider:
            return str(result)

        # Build context for response generation
        system = (
            "Generate a natural, helpful response for a college student "
            "based on the tool result."
        )
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Tool: {tool_name}\nResult: {result}\nGenerate a natural response."
                ),
            },
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
