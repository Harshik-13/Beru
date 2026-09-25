from uuid import uuid4

import pytest

from app.intelligence.models.context import (
    ConversationContext,
    PendingClarification,
    ReferencedEntity,
    StudentContext,
    StudentProfile,
    ToolResultRef,
)
from app.intelligence.models.identity import (
    BERU_IDENTITY,
    BeruIdentity,
    CapabilityStatus,
)
from app.intelligence.providers.mock import (
    MockLLMConfig,
    MockLLMProvider,
    create_mock_llm,
)
from app.intelligence.services.context_builder import (
    ContextBuilder,
    create_student_context,
)
from app.intelligence.services.conversation import ConversationService, IntentResult
from app.intelligence.tools.mock_tools import (
    GetBeruIdentityHandler,
    GetCurrentContextHandler,
    GetUserContextHandler,
    register_mock_tools,
)
from app.intelligence.tools.registry import ToolRegistry


class TestBeruIdentity:
    def test_identity_creation(self):
        identity = BeruIdentity()
        assert identity.name == "Beru"
        assert identity.full_name == "Beru — College Copilot"
        assert identity.role == "Personal college assistant"

    def test_capabilities(self):
        identity = BERU_IDENTITY
        available = identity.get_available_capabilities()
        assert len(available) > 0
        assert all(c.status == CapabilityStatus.AVAILABLE for c in available)

    def test_planned_capabilities(self):
        identity = BERU_IDENTITY
        planned = identity.get_planned_capabilities()
        assert len(planned) > 0
        assert all(c.status == CapabilityStatus.PLANNED for c in planned)

    def test_has_capability(self):
        identity = BERU_IDENTITY
        assert identity.has_capability("get_timetable")
        assert identity.has_capability("get_attendance")
        assert identity.has_capability("simulate_absence")
        assert not identity.has_capability("nonexistent_capability")

    def test_render_for_llm(self):
        identity = BERU_IDENTITY
        rendered = identity.render_for_llm()
        assert "Beru" in rendered
        assert "College Copilot" in rendered
        assert "Personal college assistant" in rendered
        assert "Available Capabilities:" in rendered
        assert "Limitations:" in rendered
        assert "Behavioral Principles:" in rendered


class TestStudentProfile:
    def test_profile_creation(self):
        student_id = uuid4()
        profile = StudentProfile(
            student_id=student_id,
            name="Test Student",
            year=2,
            course="B.Tech",
            branch="Cybersecurity",
            semester=3,
            section="A",
            subjects=("DBMS", "OS", "Java"),
            attendance_target=75.0,
        )
        assert profile.student_id == student_id
        assert profile.name == "Test Student"
        assert profile.has_academic_info()

    def test_profile_no_academic_info(self):
        student_id = uuid4()
        profile = StudentProfile(student_id=student_id, name="Test")
        assert not profile.has_academic_info()
        assert profile.get_display_name() == "Test"


class TestConversationContext:
    def test_conversation_creation(self):
        student_id = uuid4()
        conv = ConversationContext(student_id=student_id)
        assert conv.student_id == student_id
        assert conv.recent_messages == ()
        assert conv.active_intent is None
        assert conv.pending_clarification is None

    def test_add_message(self):
        student_id = uuid4()
        conv = ConversationContext(student_id=student_id)
        new_conv = conv.add_message("user", "Hello")
        assert len(new_conv.recent_messages) == 1
        assert new_conv.recent_messages[0]["role"] == "user"
        assert new_conv.recent_messages[0]["content"] == "Hello"

    def test_message_history_limit(self):
        student_id = uuid4()
        conv = ConversationContext(student_id=student_id, max_history=3)
        conv = conv.add_message("user", "1")
        conv = conv.add_message("user", "2")
        conv = conv.add_message("user", "3")
        conv = conv.add_message("user", "4")
        assert len(conv.recent_messages) == 3
        assert conv.recent_messages[0]["content"] == "2"

    def test_set_active_intent(self):
        student_id = uuid4()
        conv = ConversationContext(student_id=student_id)
        new_conv = conv.set_active_intent("get_timetable")
        assert new_conv.active_intent == "get_timetable"

    def test_add_referenced_entity(self):
        student_id = uuid4()
        conv = ConversationContext(student_id=student_id)
        entity = ReferencedEntity(
            entity_type="subject",
            identifier="919876543210@s.whatsapp.net",
            display_name="Test User",
        )
        new_conv = conv.add_referenced_entity(entity)
        assert len(new_conv.referenced_entities) == 1
        assert (
            new_conv.referenced_entities[0].identifier == "919876543210@s.whatsapp.net"
        )

    def test_resolve_entity(self):
        student_id = uuid4()
        conv = ConversationContext(student_id=student_id)
        entity = ReferencedEntity(
            entity_type="subject",
            identifier="919876543210@s.whatsapp.net",
            display_name="Test User",
        )
        conv = conv.add_referenced_entity(entity)
        resolved = conv.resolve_entity(
            "subject", "919876543210@s.whatsapp.net", "subject-dbms-uuid"
        )
        assert resolved.referenced_entities[0].resolved_id == "subject-dbms-uuid"

    def test_pending_clarification(self):
        student_id = uuid4()
        conv = ConversationContext(student_id=student_id)
        clarification = PendingClarification(
            question="Which class?",
            entity_type="subject",
            original_message="Can I skip the first one?",
            candidates=("DBMS", "OS", "Java"),
        )
        new_conv = conv.set_pending_clarification(clarification)
        assert new_conv.pending_clarification is not None
        assert new_conv.pending_clarification.candidates == ("DBMS", "OS", "Java")

    def test_clear_pending_clarification(self):
        student_id = uuid4()
        conv = ConversationContext(student_id=student_id)
        clarification = PendingClarification(
            question="Which class?",
            entity_type="subject",
            original_message="Can I skip the first one?",
            candidates=("DBMS", "OS", "Java"),
        )
        conv = conv.set_pending_clarification(clarification)
        cleared = conv.clear_pending_clarification()
        assert cleared.pending_clarification is None

    def test_add_tool_result(self):
        student_id = uuid4()
        conv = ConversationContext(student_id=student_id)
        result = ToolResultRef(
            tool_name="get_timetable",
            arguments={},
            result_summary="Got 5 classes",
        )
        new_conv = conv.add_tool_result(result)
        assert len(new_conv.recent_tool_results) == 1
        assert new_conv.recent_tool_results[0].tool_name == "get_timetable"


class TestStudentContext:
    def test_student_context_creation(self):
        student_id = uuid4()
        profile = StudentProfile(student_id=student_id, name="Test Student")
        ctx = create_student_context(student_id, profile)
        assert ctx.student_id == student_id
        assert ctx.profile.name == "Test Student"
        assert ctx.get_display_name() == "Test Student"

    def test_get_recent_history(self):
        student_id = uuid4()
        conv = ConversationContext(student_id=student_id)
        conv = conv.add_message("user", "Hello")
        conv = conv.add_message("assistant", "Hi")
        ctx = StudentContext(
            student_id=student_id,
            profile=StudentProfile(student_id=student_id),
            conversation=conv,
        )
        history = ctx.get_recent_history(2)
        assert len(history) == 2

    def test_get_active_intent(self):
        student_id = uuid4()
        conv = ConversationContext(student_id=student_id)
        conv = conv.set_active_intent("get_timetable")
        profile = StudentProfile(student_id=student_id)
        ctx = StudentContext(student_id=student_id, profile=profile, conversation=conv)
        assert ctx.get_active_intent() == "get_timetable"

    def test_get_referenced_entities(self):
        student_id = uuid4()
        conv = ConversationContext(student_id=student_id)
        conv = conv.add_referenced_entity(
            ReferencedEntity(
                entity_type="subject", identifier="DBMS", display_name="DBMS"
            )
        )
        conv = conv.add_referenced_entity(
            ReferencedEntity(
                entity_type="period", identifier="1", display_name="Period 1"
            )
        )
        profile = StudentProfile(student_id=student_id)
        ctx = StudentContext(student_id=student_id, profile=profile, conversation=conv)

        subjects = ctx.get_referenced_entities("subject")
        periods = ctx.get_referenced_entities("period")
        all_entities = ctx.get_referenced_entities()

        assert len(subjects) == 1
        assert len(periods) == 1
        assert len(all_entities) == 2


class TestContextBuilder:
    def test_context_builder_creation(self):
        builder = ContextBuilder()
        assert builder.beru_identity.name == "Beru"

    def test_build_context(self):
        student_id = uuid4()
        profile = StudentProfile(student_id=student_id, name="Test Student")
        ctx = create_student_context(student_id, profile)

        builder = ContextBuilder()
        available_tools = [
            {"name": "get_timetable", "description": "Get timetable"},
        ]

        result = builder.build_context(
            ctx, "What classes do I have tomorrow?", available_tools
        )

        assert result.system_prompt
        assert result.user_prompt == "Student: What classes do I have tomorrow?"
        assert len(result.messages) >= 2
        assert result.available_tools == available_tools


class TestIntentResult:
    def test_intent_result_creation(self):
        result = IntentResult(
            intent="get_timetable",
            entities={"period": "tomorrow"},
            confidence=0.9,
        )
        assert result.intent == "get_timetable"
        assert result.entities["period"] == "tomorrow"
        assert result.confidence == 0.9

    def test_intent_result_with_tool_request(self):
        result = IntentResult(
            tool_request={"id": "call_1", "name": "get_timetable", "arguments": {}},
            confidence=0.9,
        )
        assert result.tool_request is not None
        assert result.tool_request["name"] == "get_timetable"

    def test_intent_result_requires_clarification(self):
        result = IntentResult(
            requires_clarification=True,
            clarification_question="Which class?",
            clarification_candidates=("DBMS", "OS"),
        )
        assert result.requires_clarification
        assert result.clarification_question == "Which class?"


class TestMockLLMProvider:
    @pytest.mark.asyncio
    async def test_mock_llm_response_text(self):
        provider = MockLLMProvider()
        await provider.initialize(MockLLMConfig(provider_name="mock"))

        provider.set_response_text("Hello, I'm Beru!")

        response = await provider.chat_completion(messages=[])
        assert response.content == "Hello, I'm Beru!"
        assert response.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_mock_llm_tool_call(self):
        provider = MockLLMProvider()
        await provider.initialize(MockLLMConfig(provider_name="mock"))

        provider.set_tool_call("get_timetable", {"period": "tomorrow"})

        response = await provider.chat_completion(messages=[])
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_timetable"
        assert response.tool_calls[0].arguments == {"period": "tomorrow"}

    @pytest.mark.asyncio
    async def test_mock_llm_clarification(self):
        provider = MockLLMProvider()
        await provider.initialize(MockLLMConfig(provider_name="mock"))

        provider.set_clarification("Which class?", ("DBMS", "OS"))

        response = await provider.chat_completion(messages=[])
        assert "Which class?" in response.content

    @pytest.mark.asyncio
    async def test_mock_llm_structured(self):
        provider = MockLLMProvider()
        await provider.initialize(MockLLMConfig(provider_name="mock"))

        result = await provider.structured_completion(
            messages=[],
            response_schema={"type": "object"},
        )
        assert result["status"] == "mock"


class TestConversationService:
    @pytest.fixture
    def mock_llm(self):
        return create_mock_llm(
            response_text=(
                "Hello! I'm Beru, your personal college assistant. "
                "I can help with timetable, attendance, simulations, and more."
            )
        )

    @pytest.fixture
    def service(self, mock_llm):
        register_mock_tools()
        return ConversationService(llm_provider=mock_llm)

    @pytest.mark.asyncio
    async def test_process_message_greeting(self, service):
        student_id = uuid4()
        ctx = create_student_context(student_id)

        response, new_ctx = await service.process_message(ctx, "Hello")
        assert "Beru" in response
        assert len(new_ctx.conversation.recent_messages) == 2

    @pytest.mark.asyncio
    async def test_process_message_identity(self, service):
        student_id = uuid4()
        ctx = create_student_context(student_id)

        response, _ = await service.process_message(ctx, "Who are you?")
        assert "Beru" in response
        assert "college assistant" in response.lower()

    @pytest.mark.asyncio
    async def test_process_message_capabilities(self, service):
        student_id = uuid4()
        ctx = create_student_context(student_id)

        response, _ = await service.process_message(ctx, "What can you do?")
        assert "timetable" in response.lower() or "attendance" in response.lower()

    @pytest.mark.asyncio
    async def test_process_message_timetable_intent(self, service):
        student_id = uuid4()
        ctx = create_student_context(student_id)

        response, _ = await service.process_message(
            ctx, "What classes do I have tomorrow?"
        )
        assert response is not None


class TestToolRegistry:
    def test_register_tool(self):
        registry = ToolRegistry()
        handler = GetBeruIdentityHandler()
        registry.register(handler)
        assert registry.is_registered("get_beru_identity")

    def test_list_tools(self):
        registry = ToolRegistry()
        registry.register(GetBeruIdentityHandler())
        registry.register(GetUserContextHandler())
        tools = registry.list_tools()
        assert len(tools) == 2


class TestMockTools:
    @pytest.mark.asyncio
    async def test_get_beru_identity(self):
        handler = GetBeruIdentityHandler()
        student_id = uuid4()
        result = await handler.execute(student_id, {})
        assert result["name"] == "Beru"
        assert result["full_name"] == "Beru — College Copilot"
        assert result["role"] == "Personal college assistant"
        assert len(result["available_capabilities"]) > 0
        assert len(result["planned_capabilities"]) > 0
        assert len(result["limitations"]) > 0

    @pytest.mark.asyncio
    async def test_get_user_context(self):
        handler = GetUserContextHandler()
        student_id = uuid4()
        result = await handler.execute(student_id, {})
        assert result["student_id"] == str(student_id)
        assert "display_name" in result

    @pytest.mark.asyncio
    async def test_get_current_context(self):
        handler = GetCurrentContextHandler()
        student_id = uuid4()
        result = await handler.execute(student_id, {})
        assert "active_intent" in result
        assert "pending_clarification" in result


class TestToolRegistryWithMockTools:
    def test_register_mock_tools(self):
        registry = ToolRegistry()
        register_mock_tools(registry)
        assert registry.is_registered("get_beru_identity")
        assert registry.is_registered("get_user_context")
        assert registry.is_registered("get_current_context")
        assert len(registry.list_tools()) == 3


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_identity_question(self):
        """Test that 'Who are you?' gets a proper response from the mock system."""
        register_mock_tools()
        provider = create_mock_llm(
            response_text="I'm Beru, your personal college assistant."
        )
        service = ConversationService(llm_provider=provider)

        student_id = uuid4()
        ctx = create_student_context(student_id)

        response, _ = await service.process_message(ctx, "Who are you?")
        assert "Beru" in response

    @pytest.mark.asyncio
    async def test_capabilities_question(self):
        """Test that 'What can you do?' works."""
        register_mock_tools()
        provider = create_mock_llm(
            response_text=(
                "I can help with timetable, attendance, simulations, and more."
            )
        )
        service = ConversationService(llm_provider=provider)

        student_id = uuid4()
        ctx = create_student_context(student_id)

        response, _ = await service.process_message(ctx, "What can you do?")
        assert "timetable" in response.lower() or "attendance" in response.lower()

    @pytest.mark.asyncio
    async def test_context_isolation(self):
        """Test that student contexts are isolated."""
        register_mock_tools()
        provider = create_mock_llm(response_text="Hello!")
        service = ConversationService(llm_provider=provider)

        student_a = uuid4()
        student_b = uuid4()

        ctx_a = create_student_context(
            student_a, StudentProfile(student_id=student_a, name="Student A")
        )
        ctx_b = create_student_context(
            student_b, StudentProfile(student_id=student_b, name="Student B")
        )

        _, new_a = await service.process_message(ctx_a, "Hello from Student A")
        _, new_b = await service.process_message(ctx_b, "Hello from Student B")

        # Contexts should be separate
        assert new_a.conversation.student_id == student_a
        assert new_b.conversation.student_id == student_b
        assert new_a.conversation.recent_messages != new_b.conversation.recent_messages
        # Each conversation should only have its own messages
        assert len(new_a.conversation.recent_messages) == 2
        assert len(new_b.conversation.recent_messages) == 2
        # Messages should be different
        assert new_a.conversation.recent_messages[0]["content"] == (
            "Hello from Student A"
        )
        assert new_b.conversation.recent_messages[0]["content"] == (
            "Hello from Student B"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
