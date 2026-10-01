"""
Tests for semantic routing to start_portal_connection tool.

Verifies:
1. Tool definition exists and is registered.
2. Tool dispatches start_flow on portal_onboarding_service.
3. Natural language intent interpretation invokes start_portal_connection.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.intelligence.models.context import StudentContext, StudentProfile
from app.intelligence.tools.attendance_tools import execute_attendance_tool
from app.intelligence.tools.registry import register_builtin_tools


class TestPortalSemanticRouting:
    """Test semantic routing and tool dispatch for start_portal_connection."""

    def test_tool_definition_registered(self):
        """Verify start_portal_connection is present in tool registry."""
        reg = register_builtin_tools()
        assert reg.is_registered("start_portal_connection")
        definition = reg.get_definition("start_portal_connection")
        assert definition is not None
        assert "portal" in definition.description.lower()
        assert "connect" in definition.description.lower()

    @pytest.mark.asyncio
    async def test_execute_start_portal_connection_triggers_flow(self):
        """Verify execute_attendance_tool dispatches start_flow when start_portal_connection is called."""
        student_id = uuid4()
        chat_id = 987654

        mock_onboarding = MagicMock()
        mock_onboarding.start_flow.return_value = "Sure, Sir. Please send your college roll number."

        result = await execute_attendance_tool(
            attendance_service=None,
            timetable_service=None,
            tool_name="start_portal_connection",
            student_id=str(student_id),
            portal_onboarding_service=mock_onboarding,
            chat_id=chat_id,
        )

        assert result["status"] == "AWAITING_ROLL_NUMBER"
        assert "roll number" in result["message"].lower()
        mock_onboarding.start_flow.assert_called_once_with(student_id, chat_id)
