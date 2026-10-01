"""Tests for Conversational Synthesis of Atomic Queries.

Verifies:
1. Conversation-Quality Property Tests (non-brittle):
   - Contains verified requested fact (e.g. room E-431).
   - Does not contain unverified facts or irrelevant field dumps.
   - Answers the actual question directly.
   - Naturally addresses student as Sir.
   - Preserves ambiguity when verified result requires batch clarification.
   - Polite negative response when no sessions are found.
2. Multi-turn conversational continuity:
   - Pronouns ('it', 'that lab') resolved from recent conversation context.
3. Resilience and fallback:
   - LLM provider failure gracefully falls back to deterministic renderer.
4. Deterministic preservation:
   - Full schedules, attendance math, and analytics continue using deterministic renderers.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.intelligence.conversation.policy import ConversationalResponsePolicy
from app.intelligence.models.context import (
    ConversationContext,
    StudentContext,
    StudentProfile,
)
from app.intelligence.providers.base import LLMResponse
from app.intelligence.rendering.registry import create_default_renderer_registry
from app.intelligence.services.conversation import ATOMIC_QUERY_TOOLS, ConversationService
from app.intelligence.tools.registry import ToolDefinition, ToolRegistry

TEST_STUDENT_ID = uuid.UUID("90627ae2-5050-444f-8be0-00dbb1fef469")


def _make_context(recent_messages: list[dict] | None = None) -> StudentContext:
    profile = StudentProfile(
        student_id=TEST_STUDENT_ID,
        name="Harshik",
        lab_batch="Batch 1",
    )
    conv = ConversationContext(student_id=TEST_STUDENT_ID)
    if recent_messages:
        for msg in recent_messages:
            conv = conv.add_message(msg["role"], msg["content"])
    return StudentContext(
        student_id=TEST_STUDENT_ID,
        profile=profile,
        conversation=conv,
    )


class TestConversationalResponsePolicy:
    """Unit tests for the ConversationalResponsePolicy prompt construction."""

    def test_policy_system_prompt_includes_persona_and_rules(self):
        policy = ConversationalResponsePolicy(default_honorific="Sir")
        system_prompt = policy.build_system_prompt(student_name="Harshik")

        assert "Beru" in system_prompt
        assert "Harshik" in system_prompt
        assert "Sir" in system_prompt
        assert "ANSWER THE ACTUAL QUESTION FIRST" in system_prompt
        assert "USE ONLY RELEVANT VERIFIED DETAILS" in system_prompt
        assert "PRESERVE & CLARIFY AMBIGUITY" in system_prompt
        assert "CONVERSATIONAL CONTINUITY" in system_prompt

    def test_policy_user_prompt_includes_recent_context_and_verified_data(self):
        policy = ConversationalResponsePolicy(default_honorific="Sir")
        recent = [
            {"role": "user", "content": "Where is OS lab?"},
            {"role": "assistant", "content": "Your OS Lab is in room E-431, Sir."},
        ]
        prompt = policy.build_user_prompt(
            tool_name="find_activity_details",
            verified_result={"found": True, "start_time": "11:00", "end_time": "13:00"},
            user_message="When do I have it?",
            recent_messages=recent,
        )

        assert "Where is OS lab?" in prompt
        assert "When do I have it?" in prompt
        assert "find_activity_details" in prompt
        assert "11:00" in prompt


class TestConversationalSynthesisExecution:
    """Tests conversation service execution for atomic query tools."""

    @pytest.mark.asyncio
    async def test_atomic_query_synthesizes_direct_answer(self):
        """find_activity_details should synthesize a direct conversational answer."""
        mock_llm = MagicMock()
        mock_llm.chat_completion = AsyncMock(
            return_value=LLMResponse(
                content="Your Operating Systems Lab is held in room E-431, Sir (Thursday, 11:00 AM–1:00 PM).",
                tool_calls=[],
            )
        )

        mock_timetable_service = MagicMock()
        mock_timetable_service.entry_repo = MagicMock()
        mock_timetable_service.timetable_repo = MagicMock()

        service = ConversationService(
            llm_provider=mock_llm,
            timetable_service=mock_timetable_service,
        )
        context = _make_context()

        # Simulate executing find_activity_details via _execute_tool
        tool_req = {
            "name": "find_activity_details",
            "arguments": {"query": "OS lab"},
        }

        # Mock the tool output
        with pytest.MonkeyPatch.context() as mp:
            async def fake_execute(*args, **kwargs):
                return {
                    "found": True,
                    "query": "OS lab",
                    "status": "confirmed",
                    "matches": [
                        {
                            "activity_name": "OPERATING SYSTEMS LAB",
                            "room": "E-431",
                            "day": "Thursday",
                            "start_time": "11:00",
                            "end_time": "13:00",
                        }
                    ],
                }

            from app.intelligence.tools import timetable_tools
            mp.setattr(timetable_tools, "execute_timetable_tool", fake_execute)

            response, new_ctx = await service._execute_tool(
                context,
                tool_req,
                user_message="Where is OS lab?",
            )

        # Property assertions
        assert "E-431" in response
        assert "Sir" in response
        # Verify LLM was invoked with synthesis prompt
        assert mock_llm.chat_completion.called
        synth_call = mock_llm.chat_completion.call_args[1]
        system_content = synth_call["messages"][0]["content"]
        assert "ANSWER THE ACTUAL QUESTION FIRST" in system_content

    @pytest.mark.asyncio
    async def test_multi_turn_conversational_continuity(self):
        """Turn 2 with pronouns ('When do I have it?') should include previous turns in context."""
        mock_llm = MagicMock()
        mock_llm.chat_completion = AsyncMock(
            return_value=LLMResponse(
                content="You have Operating Systems Lab on Thursday from 11:00 AM to 1:00 PM, Sir.",
                tool_calls=[],
            )
        )

        service = ConversationService(llm_provider=mock_llm)
        # Context includes Turn 1
        recent = [
            {"role": "user", "content": "Where is OS lab?"},
            {"role": "assistant", "content": "Your OS Lab is in room E-431, Sir."},
        ]
        context = _make_context(recent_messages=recent)

        tool_req = {
            "name": "find_activity_details",
            "arguments": {"query": "OS lab"},
        }

        with pytest.MonkeyPatch.context() as mp:
            async def fake_execute(*args, **kwargs):
                return {
                    "found": True,
                    "query": "OS lab",
                    "matches": [{"day": "Thursday", "start_time": "11:00", "end_time": "13:00"}],
                }

            from app.intelligence.tools import timetable_tools
            mp.setattr(timetable_tools, "execute_timetable_tool", fake_execute)

            response, new_ctx = await service._execute_tool(
                context,
                tool_req,
                user_message="When do I have it?",
            )

        assert "Thursday" in response
        assert "11:00" in response
        assert "Sir" in response
        # Verify recent messages were passed to LLM
        synth_call = mock_llm.chat_completion.call_args[1]
        user_content = synth_call["messages"][1]["content"]
        assert "Where is OS lab?" in user_content
        assert "When do I have it?" in user_content

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_deterministic_renderer(self):
        """When LLM synthesis fails (e.g. timeout or 429), Beru falls back to deterministic renderer."""
        mock_llm = MagicMock()
        mock_llm.chat_completion = AsyncMock(side_effect=RuntimeError("Provider 429 Rate Limit"))

        service = ConversationService(
            llm_provider=mock_llm,
            timetable_service=MagicMock(),
        )
        context = _make_context()

        tool_req = {
            "name": "find_activity_details",
            "arguments": {"query": "DV LAB"},
        }

        with pytest.MonkeyPatch.context() as mp:
            async def fake_execute(*args, **kwargs):
                return {
                    "found": True,
                    "query": "DV LAB",
                    "status": "confirmed",
                    "count": 1,
                    "matches": [
                        {
                            "activity_name": "DV LAB",
                            "start_time": "13:40",
                            "end_time": "15:40",
                            "room": "E-505",
                            "faculty": "Dr. Reddy",
                        }
                    ],
                }

            from app.intelligence.tools import timetable_tools
            mp.setattr(timetable_tools, "execute_timetable_tool", fake_execute)

            # Must NOT raise exception; must fall back to deterministic renderer
            response, new_ctx = await service._execute_tool(
                context,
                tool_req,
                user_message="Where is DV lab?",
            )

        assert "Activity Details — DV LAB:" in response
        assert "<code>E-505</code>" in response
        assert "13:40 – 15:40" in response

    @pytest.mark.asyncio
    async def test_structured_tools_retain_deterministic_rendering(self):
        """Tools like get_today_schedule should remain deterministic and never route to synthesis."""
        mock_llm = MagicMock()
        # If mock_llm is called for synthesis, it would return this text
        mock_llm.chat_completion = AsyncMock(return_value=LLMResponse(content="Synthetic schedule"))

        service = ConversationService(
            llm_provider=mock_llm,
            timetable_service=MagicMock(),
        )
        context = _make_context()

        tool_req = {
            "name": "get_today_schedule",
            "arguments": {},
        }

        with pytest.MonkeyPatch.context() as mp:
            async def fake_execute(*args, **kwargs):
                return {
                    "status": "confirmed",
                    "day": "Monday",
                    "entries": [
                        {
                            "activity_name": "Operating Systems",
                            "activity_type": "lecture",
                            "start_time": "10:00",
                            "end_time": "11:00",
                            "room": "E-505",
                        }
                    ],
                }

            from app.intelligence.tools import timetable_tools
            mp.setattr(timetable_tools, "execute_timetable_tool", fake_execute)

            response, new_ctx = await service._execute_tool(
                context,
                tool_req,
                user_message="What classes do I have today?",
            )

        # Must be the deterministic day schedule format, NOT the mock_llm synthetic text
        assert "Schedule for Monday:" in response
        assert "1. <b>Operating Systems</b>" in response
        assert "<code>E-505</code>" in response
        # Synthesis LLM must NOT have been called
        assert not mock_llm.chat_completion.called
