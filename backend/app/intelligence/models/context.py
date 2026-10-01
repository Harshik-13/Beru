from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from app.intelligence.models.identity import BeruIdentity


@dataclass(frozen=True, slots=True)
class StudentProfile:
    """Structured student profile information."""

    student_id: UUID
    name: str | None = None
    year: int | None = None
    course: str | None = None
    branch: str | None = None
    semester: int | None = None
    section: str | None = None
    subjects: tuple[str, ...] = ()
    attendance_target: float | None = None
    briefing_time: str | None = None
    timezone: str = "Asia/Kolkata"
    has_timetable: bool = False
    timetable_status: str | None = None
    lab_batch: str | None = None
    needs_lab_batch: bool = False
    academic_year: str | None = None
    graduation_year: int | None = None
    chat_id: int | None = None

    def has_academic_info(self) -> bool:
        return all(
            [
                self.year is not None,
                self.course is not None,
                self.branch is not None,
                self.semester is not None,
            ]
        )

    def get_display_name(self) -> str:
        return self.name or f"Student {str(self.student_id)[:8]}"


@dataclass(frozen=True, slots=True)
class ReferencedEntity:
    """An entity referenced in the conversation that can be resolved later."""

    entity_type: str
    identifier: str
    display_name: str
    resolved_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PendingClarification:
    """Represents a pending clarification from the user."""

    question: str
    entity_type: str
    original_message: str
    candidates: tuple[str, ...]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class ToolResultRef:
    """Reference to a recent tool result for context."""

    tool_name: str
    arguments: dict
    result_summary: str
    executed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    success: bool = True


@dataclass(frozen=True, slots=True)
class ConversationContext:
    """
    Server-side conversation context for a student.

    This represents the active conversation state including
    history, active intent, referenced entities, and pending clarifications.
    """

    student_id: UUID
    conversation_id: UUID = field(default_factory=lambda: uuid4())
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    recent_messages: tuple[dict, ...] = ()
    max_history: int = 10

    active_intent: str | None = None
    referenced_entities: tuple[ReferencedEntity, ...] = ()
    pending_clarification: PendingClarification | None = None
    recent_tool_results: tuple[ToolResultRef, ...] = ()

    onboarding_state: str | None = None

    def add_message(self, role: str, content: str) -> ConversationContext:
        """Add a message to history, returning new context."""
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        new_messages = (*self.recent_messages, message)
        if len(new_messages) > self.max_history:
            new_messages = new_messages[-self.max_history :]
        return ConversationContext(
            student_id=self.student_id,
            conversation_id=self.conversation_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            recent_messages=new_messages,
            max_history=self.max_history,
            active_intent=self.active_intent,
            referenced_entities=self.referenced_entities,
            pending_clarification=self.pending_clarification,
            recent_tool_results=self.recent_tool_results,
            onboarding_state=self.onboarding_state,
        )

    def set_active_intent(self, intent: str) -> ConversationContext:
        return ConversationContext(
            student_id=self.student_id,
            conversation_id=self.conversation_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            recent_messages=self.recent_messages,
            max_history=self.max_history,
            active_intent=intent,
            referenced_entities=self.referenced_entities,
            pending_clarification=self.pending_clarification,
            recent_tool_results=self.recent_tool_results,
            onboarding_state=self.onboarding_state,
        )

    def add_referenced_entity(self, entity: ReferencedEntity) -> ConversationContext:
        new_entities = (*self.referenced_entities, entity)
        if len(new_entities) > 20:
            new_entities = new_entities[-20:]
        return ConversationContext(
            student_id=self.student_id,
            conversation_id=self.conversation_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            recent_messages=self.recent_messages,
            max_history=self.max_history,
            active_intent=self.active_intent,
            referenced_entities=new_entities,
            pending_clarification=self.pending_clarification,
            recent_tool_results=self.recent_tool_results,
            onboarding_state=self.onboarding_state,
        )

    def resolve_entity(
        self, entity_type: str, identifier: str, resolved_id: str
    ) -> ConversationContext:
        """Resolve a referenced entity to its actual ID."""
        new_entities = []
        for e in self.referenced_entities:
            if e.entity_type == entity_type and e.identifier == identifier:
                new_entities.append(
                    ReferencedEntity(
                        entity_type=e.entity_type,
                        identifier=e.identifier,
                        display_name=e.display_name,
                        resolved_id=resolved_id,
                        metadata=e.metadata,
                    )
                )
            else:
                new_entities.append(e)
        return ConversationContext(
            student_id=self.student_id,
            conversation_id=self.conversation_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            recent_messages=self.recent_messages,
            max_history=self.max_history,
            active_intent=self.active_intent,
            referenced_entities=tuple(new_entities),
            pending_clarification=self.pending_clarification,
            recent_tool_results=self.recent_tool_results,
            onboarding_state=self.onboarding_state,
        )

    def set_pending_clarification(
        self, clarification: PendingClarification
    ) -> ConversationContext:
        return ConversationContext(
            student_id=self.student_id,
            conversation_id=self.conversation_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            recent_messages=self.recent_messages,
            max_history=self.max_history,
            active_intent=self.active_intent,
            referenced_entities=self.referenced_entities,
            pending_clarification=clarification,
            recent_tool_results=self.recent_tool_results,
            onboarding_state=self.onboarding_state,
        )

    def clear_pending_clarification(self) -> ConversationContext:
        return ConversationContext(
            student_id=self.student_id,
            conversation_id=self.conversation_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            recent_messages=self.recent_messages,
            max_history=self.max_history,
            active_intent=self.active_intent,
            referenced_entities=self.referenced_entities,
            pending_clarification=None,
            recent_tool_results=self.recent_tool_results,
            onboarding_state=self.onboarding_state,
        )

    def add_tool_result(self, tool_result: ToolResultRef) -> ConversationContext:
        new_results = (*self.recent_tool_results, tool_result)
        if len(new_results) > 10:
            new_results = new_results[-10:]
        return ConversationContext(
            student_id=self.student_id,
            conversation_id=self.conversation_id,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            recent_messages=self.recent_messages,
            max_history=self.max_history,
            active_intent=self.active_intent,
            referenced_entities=self.referenced_entities,
            pending_clarification=self.pending_clarification,
            recent_tool_results=new_results,
            onboarding_state=self.onboarding_state,
        )

    def resolve_pending_clarification(self, answer: str) -> ConversationContext:
        """Resolve pending clarification with user's answer."""
        # The actual resolution logic will be in the service layer
        return self.clear_pending_clarification()


@dataclass(frozen=True, slots=True)
class StudentContext:
    """
    Complete context for a student including profile and conversation.

    This is the main context object passed through the intelligence pipeline.
    """

    student_id: UUID
    profile: StudentProfile
    conversation: ConversationContext = field(
        default_factory=lambda: ConversationContext(student_id=UUID(int=0))
    )
    beru_identity: BeruIdentity = field(
        default_factory=lambda: (
            __import__(
                "app.intelligence.models.identity", fromlist=["BERU_IDENTITY"]
            ).BERU_IDENTITY
        )
    )

    def get_display_name(self) -> str:
        return self.profile.get_display_name()

    def has_academic_info(self) -> bool:
        return self.profile.has_academic_info()

    def get_recent_history(self, limit: int = 5) -> tuple[dict, ...]:
        return self.conversation.recent_messages[-limit:]

    def get_active_intent(self) -> str | None:
        return self.conversation.active_intent

    def get_pending_clarification(self) -> PendingClarification | None:
        return self.conversation.pending_clarification

    def get_referenced_entities(
        self, entity_type: str | None = None
    ) -> tuple[ReferencedEntity, ...]:
        entities = self.conversation.referenced_entities
        if entity_type:
            return tuple(e for e in entities if e.entity_type == entity_type)
        return entities

    def get_recent_tool_results(self, limit: int = 3) -> tuple[ToolResultRef, ...]:
        return self.conversation.recent_tool_results[-limit:]
