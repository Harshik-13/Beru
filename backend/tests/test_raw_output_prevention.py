"""
Tests for raw output prevention and sensitive data scrubbing in tool results.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import pytest

from app.intelligence.models.context import (
    sanitize_result_summary,
    StudentProfile,
)
from app.intelligence.services.context_builder import create_student_context
from app.intelligence.providers.base import LLMResponse, LLMToolCall
from app.intelligence.rendering.attendance_renderer import AttendanceRenderer
from app.intelligence.rendering.schedule_renderer import ScheduleRenderer
from app.intelligence.services.conversation import ConversationService


def test_sanitize_result_summary_scrubs_sensitive_data():
    """Verify passwords, cookies, session tokens, and raw HTML are scrubbed from tool summaries."""
    # Test dictionary with sensitive keys
    sensitive_dict = {
        "password": "secret_password_123",
        "cookie": "ASP.NET_SessionId=xyz123",
        "token": "csrf_token_abc456",
        "data": "<div>Safe HTML content</div>",
        "attended": 100,
    }
    sanitized = sanitize_result_summary(sensitive_dict)
    assert "secret_password_123" not in sanitized
    assert "ASP.NET_SessionId" not in sanitized
    assert "csrf_token_abc456" not in sanitized
    assert "<div" not in sanitized
    assert "attended" in sanitized

    # Test string with HTML and token
    sensitive_str = "Received cookie: auth=tok999 with html <table><tr><td>val</td></tr></table>"
    sanitized_str = sanitize_result_summary(sensitive_str)
    assert "<table" not in sanitized_str
    assert "auth=tok999" not in sanitized_str


def test_renderers_never_dump_raw_dicts():
    """Verify fallback renderers never dump raw Python dict representations."""
    student_id = uuid4()
    profile = StudentProfile(student_id=student_id, name="Harsh")
    ctx = create_student_context(student_id, profile)

    att_renderer = AttendanceRenderer()
    raw_att_data = {"subject_codes": ["25PC1CS201", "25PC1CY201"], "count": 2}
    output = att_renderer.render_generic_attendance(raw_att_data, ctx)
    assert not output.strip().startswith("{")
    assert "{'subject_codes'" not in output
    assert "Attendance details processed successfully." in output

    sched_renderer = ScheduleRenderer()
    raw_sched_data = {"unmapped_entries": [1, 2, 3]}
    output2 = sched_renderer.render_generic_timetable(raw_sched_data, ctx)
    assert not output2.strip().startswith("{")
    assert "Timetable details updated." in output2


@pytest.mark.asyncio
async def test_defense_in_depth_catches_raw_dict_response():
    """Verify ConversationService intercepts any raw dict/JSON output from LLM/tool and rerenders."""
    student_id = uuid4()
    profile = StudentProfile(student_id=student_id, name="Harsh")
    ctx = create_student_context(student_id, profile)

    # Simulate tool returning dict
    mock_tt_service = MagicMock()
    mock_timetable = MagicMock()
    mock_timetable.id = uuid4()
    mock_timetable.version = 1
    mock_timetable.academic_year = "2026-27"
    mock_timetable.semester = 3
    mock_timetable.section = "A"
    mock_timetable.confirmed_at = None
    mock_tt_service.get_confirmed_timetable = AsyncMock(return_value=mock_timetable)
    mock_tt_service.get_pending_timetable = AsyncMock(return_value=None)

    # Fake LLM that returns a tool call
    fake_llm = MagicMock()
    fake_llm.chat_completion = AsyncMock(
        return_value=LLMResponse(
            content=None,
            tool_calls=(
                LLMToolCall(
                    id="call_1",
                    name="get_timetable_status",
                    arguments={"student_id": str(student_id)},
                ),
            ),
        )
    )

    conv_svc = ConversationService(llm_provider=fake_llm, timetable_service=mock_tt_service)
    # Mock renderer to return a raw dict string initially to test the interceptor
    original_render = conv_svc.renderer_registry.render
    call_count = 0

    def bad_then_good_render(tool_name, result, student_context, user_message=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "{'status': 'confirmed', 'version': 1}"  # Raw leak attempt
        return original_render(tool_name, result, student_context, user_message)

    conv_svc.renderer_registry.render = bad_then_good_render

    resp, _ = await conv_svc.process_message(ctx, "Check timetable status")
    # Interceptor should catch the raw string starting with { and ending with }
    assert call_count == 2
    assert not resp.strip().startswith("{")
    assert "<b>Timetable Status:</b>" in resp or "Timetable" in resp
