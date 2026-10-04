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

        # Response style guidelines
        parts.append(
            "Response Style & Persona:\n"
            "- Always address the student respectfully as 'Sir'.\n"
            "- Do NOT start messages with repetitive greetings like 'Hey [Name]!' or 'Hello!'.\n"
            "- Maintain a concise, professional ChatGPT-style demeanor.\n"
            "- Use bold labels (<b>Time:</b>, <b>Room:</b>) and keep emojis minimal (functional alerts only)."
        )

        # Natural Language Conversational Guidance & Action Integrity Invariant
        parts.append(
            "ACTION INTEGRITY INVARIANT (NON-NEGOTIABLE):\n"
            "- You are connected to a verified backend. You may ONLY state or imply that an action, "
            "setting update, target change, or database mutation occurred IF an authorized tool in "
            "'MUTATION_TOOLS' was executed in this turn and returned a verified success result.\n"
            "- If the student requests a state-changing action (e.g. changing roll number, deleting data, "
            "updating profile) for which NO backend tool exists or if the tool failed, you MUST NEVER "
            "pretend the action occurred. Politely decline using this standard response:\n"
            "  \"Sir, I do not currently have the capability to perform that action directly. "
            "I can, however, help you with your attendance tracking, timetable, or briefings.\"\n\n"
            "Attendance Intelligence & Tool Selection Principles:\n"
            "- Infer intent naturally from conversation context without requiring exact keywords.\n"
            "- Target setting/updating: When the student asks to change, update, or set their attendance target "
            "(e.g. 'Set target to 67%', 'My new target is 80%'), ALWAYS invoke 'set_attendance_target'.\n"
            "- Safe bunks / skipping classes: When the student asks how many classes they can skip, miss, or bunk "
            "without dropping below their target (e.g. 'Can I bunk OOPJ?', 'How many classes can I skip?'), "
            "invoke 'calculate_bunk_allowance'. Provide 'subject_code' if they specified a subject, or omit it "
            "for overall and full breakdown.\n"
            "- Day-leave simulation: When the student asks if they can take leave on a single day or miss classes "
            "(e.g. 'Can I take leave tomorrow?', 'Can I skip Friday?'), invoke 'simulate_day_absence' with "
            "day='tomorrow', 'today', or the named weekday.\n"
            "- Multi-day / complex schedule simulation: When the student asks about missing, taking leave, or attending "
            "across multiple days, date ranges, 'next N days', or mixed attend/skip combinations "
            "(e.g. 'What if I skip Monday and Tuesday?', 'Can I bunk next 3 days?', 'If I attend Monday but skip Tuesday?'), "
            "ALWAYS invoke 'simulate_schedule_scenario' with 'days_to_skip', 'days_to_attend', or 'next_n_instructional_days'.\n"
            "- Subject period simulation: When the student asks about skipping or attending a specific number of periods/classes "
            "in a subject (e.g. 'What if I miss 2 classes of OS?', 'If I attend 3 classes of Maths?'), "
            "ALWAYS invoke 'simulate_subject_periods' with 'subject_name_or_code', 'periods_to_miss', or 'periods_to_attend'.\n"
            "- Attendance extremes: When the student asks for their lowest, highest, best, worst, or at-risk subjects "
            "(e.g. 'What is my lowest attendance?', 'Which subjects are below target?'), invoke 'get_attendance_extremes'.\n"
            "- Recovery calculation: When the student asks how many classes they need to attend to recover or reach target "
            "(e.g. 'How many classes to reach 75%?'), invoke 'calculate_classes_needed'.\n"
            "- Follow-up queries: When a student asks follow-up questions such as 'Per subject?', 'Break it down', "
            "or 'Show subjects', select 'get_attendance_summary'.\n"
            "- Course name mapping: When a student asks about course codes, abbreviations, or subject names (e.g. "
            "'Which subject is 25PC1CS201?' or 'What does OOPJ stand for?'), call 'get_course_mapping'.\n"
            "- Ambiguity: If the student's request is genuinely ambiguous across multiple subjects or options, "
            "proactively ask for clarification with candidates rather than guessing.\n"
            "- Grounding: When reporting attendance metrics, rely strictly on verified tool results. "
            "Never compute percentages or arithmetic yourself."
        )

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

        if profile.graduation_year:
            lines.append(f"  Graduation Year: {profile.graduation_year}")

        if profile.subjects:
            lines.append(f"  Subjects: {', '.join(profile.subjects)}")

        if profile.attendance_target:
            lines.append(f"  Attendance Target: {profile.attendance_target}%")

        if profile.briefing_time:
            lines.append(f"  Briefing Time: {profile.briefing_time}")

        lines.append(f"  Timezone: {profile.timezone}")

        if profile.has_timetable:
            lines.append("  Timetable Status: ACTIVE CONFIRMED TIMETABLE")
        elif profile.timetable_status == "review_required":
            lines.append(
                "  Timetable Status: PENDING REVIEW. "
                "An extracted timetable is awaiting student review and confirmation. "
                "Use get_extracted_timetable to show the parsed entries. "
                "Do NOT answer schedule questions (tomorrow, next class, etc.) "
                "from a pending timetable — only CONFIRMED timetables are queryable. "
                "Guide the student to: review entries, set lab batch if needed, "
                "make corrections, then confirm."
            )
            if profile.needs_lab_batch:
                lines.append(
                    "  The timetable has slash-separated lab entries. "
                    "Ask the student which lab batch (Batch 1 or Batch 2) "
                    "they belong to."
                )
        else:
            lines.append(
                "  Timetable Status: NO TIMETABLE UPLOADED YET. "
                "Proactively and warmly ask the student to send their timetable "
                "PDF document or photo here on Telegram "
                "so you can set up their daily schedule and attendance tracking."
            )

        return "\n".join(lines)

    def _format_conversation_context(self, ctx: StudentContext) -> str:
        conv = ctx.conversation
        lines = ["Conversation Context:"]

        # Dialogue State
        dialogue_items = []
        if conv.last_domain:
            dialogue_items.append(f"Domain: {conv.last_domain}")
        if conv.last_intent:
            dialogue_items.append(f"Last Intent: {conv.last_intent}")
        if conv.last_tool:
            dialogue_items.append(f"Last Tool: {conv.last_tool}")
        if conv.last_entity:
            dialogue_items.append(f"Last Entity: {conv.last_entity}")
        if conv.last_semester:
            dialogue_items.append(f"Semester: {conv.last_semester}")
        if dialogue_items:
            lines.append(f"  Dialogue State: {' | '.join(dialogue_items)}")

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
