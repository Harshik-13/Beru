from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.intelligence.conversation.policy import ConversationalResponsePolicy
from app.intelligence.models.context import (
    StudentContext,
    ToolResultRef,
)
from app.intelligence.models.identity import BERU_IDENTITY
from app.intelligence.rendering.style_layer import ResponseStyleLayer
from app.intelligence.services.context_builder import (
    ContextBuilder,
    create_student_context,
)
from app.intelligence.services.rate_limiter import get_rate_limiter
from app.intelligence.tools.registry import tool_registry

logger = logging.getLogger(__name__)

MUTATION_TOOLS: frozenset[str] = frozenset({
    "set_attendance_target",
    "set_lab_batch",
    "set_briefing_time",
    "confirm_timetable",
    "update_timetable_entry",
    "add_timetable_entry",
    "delete_timetable_entry",
    "sync_attendance",
    "start_portal_connection",
})

GRACEFUL_CAPABILITY_REFUSAL: str = (
    "Sir, I do not currently have the capability to perform that action directly. "
    "I can, however, help you with your attendance tracking, timetable, or briefings."
)


def is_state_mutation_intent(message: str) -> bool:
    """
    Detect whether a student prompt is attempting to mutate state or settings.
    Used to enforce the Action Integrity Invariant when no authorized mutation tool executes.
    """
    msg = message.strip().casefold()
    mutation_verbs = {
        "change",
        "update",
        "set",
        "modify",
        "delete",
        "remove",
        "reset",
        "clear",
        "edit",
        "switch",
        "replace",
        "make",
    }
    tokens = set(msg.split())
    has_mutation_verb = bool(tokens & mutation_verbs)
    has_new_assignment = (
        "is my new" in msg
        or "as my new" in msg
        or "to my new" in msg
        or "new target" in msg
    )

    mutation_targets = [
        "target",
        "roll number",
        "roll no",
        "rollnum",
        "email",
        "phone",
        "password",
        "branch",
        "section",
        "semester",
        "name",
        "snapshot",
        "attendance",
        "timetable",
        "batch",
        "briefing",
    ]
    has_target = any(t in msg for t in mutation_targets)

    # Exclude read/query intents
    query_prefixes = (
        "what",
        "how",
        "show",
        "tell",
        "check",
        "view",
        "display",
        "get",
        "when",
        "where",
        "why",
        "can i",
        "could i",
    )
    starts_with_query = any(
        msg.startswith(p + " ") or msg.startswith(p + "'") for p in query_prefixes
    )

    return (
        (has_mutation_verb or has_new_assignment)
        and has_target
        and not starts_with_query
    )


ATOMIC_QUERY_TOOLS: frozenset[str] = frozenset({
    "find_activity_details",
    "find_faculty_details",
    "find_room_details",
    "get_course_mapping",
    "calculate_bunk_allowance",
    "get_attendance_extremes",
})

if TYPE_CHECKING:
    from uuid import UUID

    from app.intelligence.models.context import (
        ConversationContext,
        StudentProfile,
    )
    from app.intelligence.models.identity import BeruIdentity
    from app.intelligence.providers.base import LLMProvider, LLMResponse
    from app.intelligence.services.attendance_service import AttendanceService
    from app.intelligence.services.timetable_service import TimetableService
    from app.intelligence.tools.registry import (
        ToolDefinition,
        ToolRegistry,
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
        renderer_registry: Any | None = None,
        portal_onboarding_service: Any | None = None,
    ):
        self.tool_registry = tool_registry_instance or tool_registry
        self.context_builder = context_builder or ContextBuilder()
        self.llm_provider = llm_provider
        self.beru_identity = beru_identity or BERU_IDENTITY
        self.timetable_service = timetable_service
        self.attendance_service = attendance_service
        self.portal_onboarding_service = portal_onboarding_service

        if renderer_registry is None:
            from app.intelligence.rendering.registry import (
                create_default_renderer_registry,
            )

            self.renderer_registry = create_default_renderer_registry()
        else:
            self.renderer_registry = renderer_registry

        self.conversational_policy = ConversationalResponsePolicy(
            default_honorific=self.beru_identity.honorific
        )
        self.response_style_layer = ResponseStyleLayer(
            default_honorific=self.beru_identity.honorific
        )

    def create_student_context(
        self,
        student_id: UUID,
        profile: StudentProfile | None = None,
        conversation: ConversationContext | None = None,
    ) -> StudentContext:
        """Create a new student context."""
        return create_student_context(
            student_id=student_id,
            profile=profile,
            conversation=conversation,
        )

    async def process_message(
        self,
        student_context: StudentContext,
        message: str,
    ) -> tuple[str, StudentContext]:
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

        # ACTION INTEGRITY INVARIANT:
        # If user intended a state mutation, but no tool was invoked to execute it,
        # Beru must refuse with a graceful capability message rather than hallucinate success.
        if is_state_mutation_intent(message):
            from app.intelligence.rendering.style_contract import (
                sanitize_conversational_response,
            )

            response = sanitize_conversational_response(GRACEFUL_CAPABILITY_REFUSAL)
            new_conv = student_context.conversation.add_message("assistant", response)
            student_context = StudentContext(
                student_id=student_context.student_id,
                profile=student_context.profile,
                conversation=new_conv,
            )
            return response, student_context

        # No tool needed - direct response sanitized by style contract
        from app.intelligence.rendering.style_contract import (
            sanitize_conversational_response,
        )

        raw_response = intent_result.raw_response or (
            "I understand, Sir. Is there anything specific you'd like help with?"
        )
        response = sanitize_conversational_response(raw_response)
        new_conv = student_context.conversation.add_message("assistant", response)
        student_context = StudentContext(
            student_id=student_context.student_id,
            profile=student_context.profile,
            conversation=new_conv,
        )
        return response, student_context

    async def _interpret_intent(
        self,
        student_context: StudentContext,
        message: str,
    ) -> IntentResult:
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

    def _tool_def_to_dict(self, tool: ToolDefinition) -> dict:
        return {
            "name": tool.name,
            "description": tool.description,
            "arguments_schema": tool.arguments_schema,
            "result_schema": tool.result_schema,
            "requires_authorization": tool.requires_authorization,
            "requires_confirmation": tool.requires_confirmation,
        }

    def _tool_def_to_openai(self, tool: ToolDefinition) -> dict:
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

    def _parse_intent_response(self, response: LLMResponse) -> IntentResult:
        if response.tool_calls:
            tc = response.tool_calls[0]
            clean_args = {}
            if isinstance(tc.arguments, dict):
                for k, v in tc.arguments.items():
                    if v is not None:
                        clean_args[k] = v
            else:
                clean_args = tc.arguments
            return IntentResult(
                tool_request={
                    "id": tc.id,
                    "name": tc.name,
                    "arguments": clean_args,
                },
                confidence=0.9,
            )
        return IntentResult(
            raw_response=response.content or "",
            confidence=0.5,
        )

    async def _mock_interpret_intent(
        self,
        student_context: StudentContext,
        message: str,
    ) -> IntentResult:
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

        if "target" in msg_lower and any(w in msg_lower for w in ["set", "update", "change", "new", "make"]):
            import re
            m = re.search(r"(\d+(?:\.\d+)?)", msg_lower)
            if m:
                target_pct = float(m.group(1))
                return IntentResult(
                    tool_request={
                        "name": "set_attendance_target",
                        "arguments": {"target_percentage": target_pct},
                    },
                    confidence=0.9,
                )

        if "bunk" in msg_lower:
            return IntentResult(
                tool_request={
                    "name": "calculate_bunk_allowance",
                    "arguments": {},
                },
                confidence=0.9,
            )

        if any(w in msg_lower for w in ["skip today", "miss today", "leave today", "take leave", "take off"]):
            return IntentResult(
                tool_request={
                    "name": "simulate_day_absence",
                    "arguments": {},
                },
                confidence=0.9,
            )

        if any(w in msg_lower for w in ["highest attendance", "lowest attendance", "extremes", "best attendance", "worst attendance"]):
            return IntentResult(
                tool_request={
                    "name": "get_attendance_extremes",
                    "arguments": {},
                },
                confidence=0.9,
            )

        if any(w in msg_lower for w in ["classes needed", "need to attend", "reach target"]):
            return IntentResult(
                tool_request={
                    "name": "calculate_classes_needed",
                    "arguments": {},
                },
                confidence=0.9,
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
        student_context: StudentContext,
        intent_result: IntentResult,
        message: str,
    ) -> tuple[str, StudentContext]:
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
        student_context: StudentContext,
        intent_result: IntentResult,
        user_message: str = "",
    ) -> tuple[str, StudentContext]:
        if isinstance(intent_result, dict):
            tool_req = intent_result.get("tool_request") or intent_result
        else:
            tool_req = intent_result.tool_request

        if not tool_req or not isinstance(tool_req, dict) or "name" not in tool_req:
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
                "get_extracted_timetable",
                "update_timetable_entry",
                "add_timetable_entry",
                "delete_timetable_entry",
                "set_briefing_time",
                "get_week_schedule",
                "get_schedule_for_weekday",
                "get_timetable_metadata",
                "find_activity_details",
                "find_faculty_details",
                "find_room_details",
                "query_schedule_analytics",
                "get_course_mapping",
            }

            # Attendance tools that may need TimetableService or AttendanceService
            attendance_tools = {
                "start_portal_connection",
                "simulate_absence",
                "get_overall_attendance",
                "get_subject_attendance",
                "get_attendance_summary",
                "get_subjects_below_target",
                "calculate_classes_needed",
                "get_attendance_snapshot_info",
                "sync_attendance",
                "set_attendance_target",
                "calculate_bunk_allowance",
                "simulate_day_absence",
                "get_attendance_extremes",
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

                chat_id = getattr(student_context.profile, "chat_id", None)
                result = await execute_attendance_tool(
                    self.attendance_service,
                    self.timetable_service,
                    tool_req["name"],
                    str(student_context.student_id),
                    portal_onboarding_service=self.portal_onboarding_service,
                    chat_id=chat_id,
                    **clean_arguments,
                )
            else:
                result = await tool.execute(
                    student_id=student_context.student_id,
                    arguments=clean_arguments,
                )

            # Format tool result with sanitized summary (scrubs tokens, passwords, cookies, raw HTML)
            from app.intelligence.models.context import (
                ReferencedEntity,
                sanitize_result_summary,
            )

            tool_result = ToolResultRef(
                tool_name=tool_req["name"],
                arguments=clean_arguments,
                result_summary=sanitize_result_summary(result),
                success=True,
            )
            new_conv = student_context.conversation.add_tool_result(tool_result)

            # Update bounded dialogue state on verified successful tool execution
            tool_name = tool_req["name"]
            domain = "attendance" if tool_name in attendance_tools else "timetable"
            sem_id = clean_arguments.get("semester_id") or (
                result.get("semester_id") if isinstance(result, dict) else None
            )
            entity_val = (
                clean_arguments.get("subject_code")
                or clean_arguments.get("course_code")
                or clean_arguments.get("activity_name")
            )
            new_conv = new_conv.update_dialogue_state(
                domain=domain,
                intent=tool_name,
                tool=tool_name,
                entity=entity_val,
                semester=sem_id,
            )
            if sem_id:
                new_conv = new_conv.add_referenced_entity(
                    ReferencedEntity(
                        entity_type="semester",
                        identifier=str(sem_id),
                        display_name=f"Semester {sem_id}",
                        resolved_id=str(sem_id),
                    )
                )

            # Route response generation based on tool category:
            # 1. Atomic query tools -> Conversational synthesis using LLM + ConversationalResponsePolicy
            # 2. Structured collections / calculations -> Deterministic domain renderers
            # Resilient fallback: Any failure in conversational synthesis falls back to deterministic renderer.
            if (
                tool_req["name"] in ATOMIC_QUERY_TOOLS
                and self.llm_provider is not None
                and user_message
            ):
                try:
                    raw_conversational = await self._generate_conversational_response(
                        student_context=student_context,
                        tool_name=tool_req["name"],
                        result=result,
                        user_message=user_message,
                    )
                    response = self.response_style_layer.apply(
                        raw_conversational,
                        student_context=student_context,
                    )
                except Exception as synth_err:
                    logger.warning(
                        "Conversational synthesis failed for tool %s (%s). "
                        "Falling back to deterministic renderer.",
                        tool_req["name"],
                        synth_err,
                    )
                    response = self.renderer_registry.render(
                        tool_name=tool_req["name"],
                        result=result,
                        student_context=student_context,
                        user_message=user_message,
                    )
            else:
                response = self.renderer_registry.render(
                    tool_name=tool_req["name"],
                    result=result,
                    student_context=student_context,
                    user_message=user_message,
                )

            # Defense-in-depth: Ensure raw dictionary or list string never leaks to student
            stripped_resp = response.strip()
            if (
                (stripped_resp.startswith("{") and stripped_resp.endswith("}"))
                or (stripped_resp.startswith("[") and stripped_resp.endswith("]"))
                or stripped_resp.startswith("{'subject_codes'")
            ):
                logger.warning(
                    "Raw data structure detected in response for tool %s. Rerendering via fallback.",
                    tool_req["name"],
                )
                response = self.renderer_registry.render(
                    tool_name=tool_req["name"],
                    result=result,
                    student_context=student_context,
                    user_message=user_message,
                )

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

    async def _generate_conversational_response(
        self,
        student_context: StudentContext,
        tool_name: str,
        result: Any,
        user_message: str = "",
    ) -> str:
        """Generate focused conversational response from tool result using ConversationalResponsePolicy."""
        if not self.llm_provider:
            return str(result)

        student_name = student_context.profile.get_display_name() or "student"
        recent_messages = student_context.conversation.recent_messages

        messages = self.conversational_policy.build_messages(
            student_name=student_name,
            tool_name=tool_name,
            verified_result=result,
            user_message=user_message,
            recent_messages=recent_messages,
            honorific=self.beru_identity.honorific,
        )

        response = await self.llm_provider.chat_completion(messages=messages)
        return response.content or str(result)

    async def _generate_response_from_tool_result(
        self,
        student_context: StudentContext,
        tool_name: str,
        result: dict,
        user_message: str = "",
    ) -> str:
        """Backward-compatible wrapper for generating natural language responses from tool results."""
        return await self._generate_conversational_response(
            student_context=student_context,
            tool_name=tool_name,
            result=result,
            user_message=user_message,
        )

    def get_conversation_summary(self, student_context: StudentContext) -> str:
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
