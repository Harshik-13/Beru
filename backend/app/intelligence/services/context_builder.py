from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from app.intelligence.models.context import (
    ConversationContext,
    StudentContext,
    StudentProfile,
)
from app.intelligence.models.identity import BERU_IDENTITY, BeruIdentity


@dataclass(frozen=True, slots=True)
class ContextBuildResult:
    """Result of context building for LLM."""

    system_prompt: str
    user_prompt: str
    messages: list[dict]
    available_tools: list[dict]


class ContextBuilder:
    """
    Builds LLM context from student context.

    This is a deterministic, inspectable layer that selects and formats
    relevant context for the LLM.
    """

    def __init__(self, beru_identity: BeruIdentity | None = None):
        self.beru_identity = beru_identity or BERU_IDENTITY

    def build_context(
        self,
        student_context: StudentContext,
        current_message: str,
        available_tools: list[dict],
    ) -> ContextBuildResult:
        """
        Build the complete LLM context.

        This is the central context-building function.
        """
        system_prompt = self._build_system_prompt(student_context)
        user_prompt = self._build_user_prompt(student_context, current_message)
        messages = self._build_messages(student_context, current_message)

        return ContextBuildResult(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            messages=messages,
            available_tools=available_tools,
        )

    def _build_system_prompt(self, student_context: StudentContext) -> str:
        """Build the system prompt with Beru identity and context."""
        parts = []

        # Beru self-model
        parts.append(student_context.beru_identity.render_for_llm())

        # Student context
        parts.append(self._format_student_context(student_context))

        # Conversation context
        parts.append(self._format_conversation_context(student_context))

        # Current intent
        if student_context.conversation.active_intent:
            parts.append(
                f"Current Intent: {student_context.conversation.active_intent}"
            )

        # Pending clarification
        pending = student_context.conversation.pending_clarification
        if pending:
            parts.append(
                f"Pending Clarification: {pending.question}\n"
                f"Candidates: {', '.join(pending.candidates)}"
            )

        # Recent tool results
        recent_results = student_context.get_recent_tool_results(3)
        if recent_results:
            parts.append("Recent Tool Results:")
            for r in recent_results:
                status = "✓" if r.success else "✗"
                parts.append(f"  {status} {r.tool_name}: {r.result_summary}")

        return "\n\n".join(parts)

    def _format_student_context(self, ctx: StudentContext) -> str:
        profile = ctx.profile
        lines = ["Student Context:"]

        if ctx.profile.name:
            lines.append(f"  Name: {profile.name}")

        academic_parts = []
        if profile.year:
            academic_parts.append(f"Year {profile.year}")
        if profile.course:
            academic_parts.append(profile.course)
        if profile.branch:
            academic_parts.append(profile.branch)
        if profile.semester:
            academic_parts.append(f"Sem {profile.semester}")
        if profile.section:
            academic_parts.append(f"Section {profile.section}")

        if academic_parts:
            lines.append(f"  Academic: {' | '.join(academic_parts)}")

        if profile.subjects:
            lines.append(f"  Subjects: {', '.join(profile.subjects)}")

        if profile.attendance_target:
            lines.append(f"  Attendance Target: {profile.attendance_target}%")

        if profile.briefing_time:
            lines.append(f"  Briefing Time: {profile.briefing_time}")

        lines.append(f"  Timezone: {profile.timezone}")

        return "\n".join(lines)

    def _format_conversation_context(self, ctx: StudentContext) -> str:
        conv = ctx.conversation
        lines = ["Conversation Context:"]

        # Recent messages
        if ctx.conversation.recent_messages:
            lines.append("  Recent Messages:")
            for msg in ctx.conversation.recent_messages[-5:]:
                role = msg["role"]
                content = msg["content"][:200]
                lines.append(f"  {role}: {content}")
        else:
            lines.append("  (no previous messages)")

        # Referenced entities
        entities = ctx.conversation.referenced_entities
        if entities:
            lines.append("  Referenced Entities:")
            for e in entities[-5:]:
                res = f" -> {e.resolved_id}" if e.resolved_id else ""
                lines.append(
                    f"  - {e.entity_type}: {e.display_name} ({e.identifier}){res}"
                )

        # Pending clarification
        if ctx.conversation.pending_clarification:
            pc = ctx.conversation.pending_clarification
            lines.append(f"  Pending Clarification: {pc.question}")
            lines.append(f"  Candidates: {', '.join(pc.candidates)}")

        # Active intent
        if conv.active_intent:
            lines.append(f"  Active Intent: {conv.active_intent}")

        return "\n".join(lines)

    def _build_user_prompt(
        self, student_context: StudentContext, current_message: str
    ) -> str:
        """Build the user prompt with the current message."""
        return f"Student: {current_message}"

    def _build_messages(
        self,
        student_context: StudentContext,
        current_message: str,
    ) -> list[dict]:
        """Build the message array for LLM."""
        messages = []

        # System prompt
        system_prompt = self._build_system_prompt(student_context)
        messages.append({"role": "system", "content": system_prompt})

        # Conversation history
        has_current = False
        if student_context.conversation.recent_messages:
            last_msg = student_context.conversation.recent_messages[-1]
            if (
                last_msg.get("role") == "user"
                and last_msg.get("content") == current_message
            ):
                has_current = True

        for msg in student_context.conversation.recent_messages:
            messages.append({"role": msg["role"], "content": msg["content"]})

        # Append current message if not already present as the last item
        if not has_current:
            messages.append({"role": "user", "content": current_message})

        return messages


def create_student_context(
    student_id: UUID,
    profile: "StudentProfile | None" = None,
    conversation: Optional["ConversationContext"] = None,
    beru_identity: Optional["BeruIdentity"] = None,
) -> "StudentContext":
    """Factory function to create a StudentContext."""
    from app.intelligence.models.context import ConversationContext
    from app.intelligence.models.identity import BERU_IDENTITY

    return StudentContext(
        student_id=student_id,
        profile=profile or StudentProfile(student_id=student_id),
        conversation=conversation
        or ConversationContext(
            student_id=student_id,
            conversation_id=UUID(bytes=b"\x00" * 16),
        ),
        beru_identity=beru_identity or BERU_IDENTITY,
    )
