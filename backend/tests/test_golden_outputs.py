"""Golden Output & Deterministic Rendering Tests.

Validates:
1. Dynamic batch resolution & ambiguity preservation
2. Structural period merging based on entry topology
3. Style contract compliance: 'Sir', bold labels, minimal emojis
4. Decoupled RendererRegistry dispatch from ConversationService
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.intelligence.models.context import (
    ConversationContext,
    StudentContext,
    StudentProfile,
)
from app.intelligence.rendering.attendance_renderer import AttendanceRenderer
from app.intelligence.rendering.briefing_renderer import BriefingRenderer
from app.intelligence.rendering.registry import (
    RendererRegistry,
)
from app.intelligence.rendering.schedule_renderer import (
    ScheduleRenderer,
    merge_contiguous_entries,
)
from app.intelligence.rendering.style_contract import (
    CHECK_MARK,
    WARNING_SIGN,
    clean_greetings,
    sanitize_conversational_response,
)
from app.intelligence.services.conversation import ConversationService, IntentResult

# Standard test student ID
TEST_STUDENT_ID = uuid.UUID("90627ae2-5050-444f-8be0-00dbb1fef469")


def _make_context(lab_batch: str | None = None) -> StudentContext:
    profile = StudentProfile(
        student_id=TEST_STUDENT_ID,
        name="Harsh",
        lab_batch=lab_batch,
        attendance_target=75.0,
    )
    return StudentContext(
        student_id=TEST_STUDENT_ID,
        profile=profile,
        conversation=ConversationContext(student_id=TEST_STUDENT_ID),
    )


# ---------------------------------------------------------------------------
# Fixture: Raw Tuesday entries matching parsed college timetable
# Notice: 11:00-12:00 and 12:00-13:00 CM LAB are 2 separate periods.
# Notice: 14:40-15:40 and 15:40-16:40 CF LAB / CN LAB are 2 separate periods.
# ---------------------------------------------------------------------------
TUESDAY_RAW_ENTRIES = [
    {
        "day_of_week": 1,
        "start_time": "10:00",
        "end_time": "11:00",
        "activity_name": "OS",
        "activity_type": "lecture",
        "room": "E-505",
        "lab_batch": None,
    },
    {
        "day_of_week": 1,
        "start_time": "11:00",
        "end_time": "12:00",
        "activity_name": "CM LAB",
        "activity_type": "lab",
        "room": None,
        "lab_batch": None,
    },
    {
        "day_of_week": 1,
        "start_time": "12:00",
        "end_time": "13:00",
        "activity_name": "CM LAB",
        "activity_type": "lab",
        "room": None,
        "lab_batch": None,
    },
    {
        "day_of_week": 1,
        "start_time": "13:40",
        "end_time": "14:40",
        "activity_name": "CN",
        "activity_type": "lecture",
        "room": "E-505",
        "lab_batch": None,
    },
    {
        "day_of_week": 1,
        "start_time": "14:40",
        "end_time": "15:40",
        "activity_name": "CF LAB / CN LAB",
        "activity_type": "lab",
        "room": None,
        "lab_batch": None,
    },
    {
        "day_of_week": 1,
        "start_time": "15:40",
        "end_time": "16:40",
        "activity_name": "CF LAB / CN LAB",
        "activity_type": "lab",
        "room": None,
        "lab_batch": None,
    },
]


def test_structural_period_merging():
    """Verify that contiguous periods collapse based on entry topology."""
    # 1. CM LAB (11:00-12:00 and 12:00-13:00) with same room/batch merges to 11:00-13:00
    cm_periods = [
        {
            "day_of_week": 1,
            "start_time": "11:00",
            "end_time": "12:00",
            "activity_name": "CM LAB",
            "lab_batch": None,
            "room": None,
        },
        {
            "day_of_week": 1,
            "start_time": "12:00",
            "end_time": "13:00",
            "activity_name": "CM LAB",
            "lab_batch": None,
            "room": None,
        },
    ]
    merged = merge_contiguous_entries(cm_periods)
    assert len(merged) == 1
    assert merged[0]["start_time"] == "11:00"
    assert merged[0]["end_time"] == "13:00"
    assert merged[0]["activity_name"] == "CM LAB"

    # 2. Non-contiguous periods (e.g. 10:00-11:00 and 13:40-14:40) do NOT merge
    gap_periods = [
        {
            "day_of_week": 1,
            "start_time": "10:00",
            "end_time": "11:00",
            "activity_name": "OS",
            "lab_batch": None,
            "room": "E-505",
        },
        {
            "day_of_week": 1,
            "start_time": "13:40",
            "end_time": "14:40",
            "activity_name": "OS",
            "lab_batch": None,
            "room": "E-505",
        },
    ]
    merged_gap = merge_contiguous_entries(gap_periods)
    assert len(merged_gap) == 2

    # 3. Consecutive periods with DIFFERENT activities do NOT merge
    diff_periods = [
        {
            "day_of_week": 1,
            "start_time": "10:00",
            "end_time": "11:00",
            "activity_name": "OS",
            "lab_batch": None,
            "room": "E-505",
        },
        {
            "day_of_week": 1,
            "start_time": "11:00",
            "end_time": "12:00",
            "activity_name": "CN",
            "lab_batch": None,
            "room": "E-505",
        },
    ]
    merged_diff = merge_contiguous_entries(diff_periods)
    assert len(merged_diff) == 2


def test_golden_tuesday_schedule_batch_1():
    """Verify Tuesday schedule rendered for an authenticated Batch 1 student."""
    context = _make_context(lab_batch="Batch 1")
    from app.intelligence.rendering.registry import create_default_renderer_registry

    registry = create_default_renderer_registry()

    result = {
        "day": "Tuesday",
        "date": "2026-09-29",
        "entries": TUESDAY_RAW_ENTRIES,
    }

    output = registry.render("get_schedule", result, context)

    # Assertions
    assert "<b>Schedule for Tuesday:</b>" in output
    assert "1. <b>OS</b>" in output
    assert "<code>10:00 – 11:00</code>" in output
    assert "<code>E-505</code>" in output
    # Merged CM LAB
    assert "2. <b>CM LAB</b>" in output
    assert "<code>11:00 – 13:00</code>" in output
    # CN Lecture
    assert "3. <b>CN</b>" in output
    assert "<code>13:40 – 14:40</code>" in output
    # Resolved Batch 1 CF LAB
    assert "4. <b>CF LAB</b> (Batch 1)" in output
    assert "<code>14:40 – 16:40</code>" in output
    assert "4 sessions scheduled." in output
    # Ensure no ambiguity warning because Batch 1 is set
    assert "Note: Lab batch is not yet set" not in output


def test_presentation_decoupled_from_personality():
    """Verify ScheduleRenderer formats pure data without hardcoding 'Sir'."""
    context = _make_context(lab_batch="Batch 1")
    renderer = ScheduleRenderer()

    result = {
        "day": "Tuesday",
        "date": "2026-09-29",
        "entries": TUESDAY_RAW_ENTRIES,
    }

    output = renderer.render("get_schedule", result, context)

    # Pure data header has no honorific
    assert "<b>Schedule for Tuesday:</b>" in output
    assert "Sir" not in output


def test_golden_tuesday_schedule_batch_2():
    """Verify Tuesday schedule rendered for an authenticated Batch 2 student."""
    context = _make_context(lab_batch="Batch 2")
    from app.intelligence.rendering.registry import create_default_renderer_registry

    registry = create_default_renderer_registry()

    result = {
        "day": "Tuesday",
        "date": "2026-09-29",
        "entries": TUESDAY_RAW_ENTRIES,
    }

    output = registry.render("get_schedule", result, context)

    assert "<b>Schedule for Tuesday:</b>" in output
    # Batch 2 resolves to CN LAB
    assert "4. <b>CN LAB</b> (Batch 2)" in output
    assert "<code>14:40 – 16:40</code>" in output
    assert "CF LAB" not in output
    assert "4 sessions scheduled." in output


def test_golden_tuesday_schedule_unknown_batch():
    """Verify Tuesday schedule when lab_batch is UNKNOWN: preserves ambiguity."""
    context = _make_context(lab_batch=None)
    from app.intelligence.rendering.registry import create_default_renderer_registry

    registry = create_default_renderer_registry()

    result = {
        "day": "Tuesday",
        "date": "2026-09-29",
        "entries": TUESDAY_RAW_ENTRIES,
    }

    output = registry.render("get_schedule", result, context)

    assert "<b>Schedule for Tuesday:</b>" in output
    # Must preserve slash notation and show both batches
    assert "4. <b>CF LAB / CN LAB</b> (Batch 1 / Batch 2)" in output
    assert "<code>14:40 – 16:40</code>" in output
    # Must explicitly guide student to choose batch
    assert "Note: Lab batch is not yet set." in output
    msg = "Reply with <b>Batch 1</b> or <b>Batch 2</b> to resolve your lab allocation."
    assert msg in output


def test_golden_missing_room_and_faculty_omitted():
    """Verify that missing room and missing faculty fields are completely omitted."""
    context = _make_context(lab_batch="Batch 1")
    renderer = ScheduleRenderer()

    entries_without_room_faculty = [
        {
            "day": "Monday",
            "start_time": "10:00",
            "end_time": "11:00",
            "activity_name": "SPORTS",
            "activity_type": "activity",
            "room": None,
            "faculty": None,
            "lab_batch": None,
        }
    ]

    result = {
        "day": "Monday",
        "date": "2026-09-28",
        "entries": entries_without_room_faculty,
    }

    output = renderer.render("get_schedule", result, context)

    assert "1. <b>SPORTS</b>" in output
    assert "<b>Time:</b>" in output
    assert "<b>Type:</b>" in output
    # Missing room and faculty MUST BE completely omitted without placeholders
    assert "Room" not in output
    assert "Faculty" not in output
    assert "Not specified" not in output


def test_golden_empty_schedule():
    """Verify clean rendering when no classes are scheduled."""
    context = _make_context(lab_batch="Batch 1")
    from app.intelligence.rendering.registry import create_default_renderer_registry

    registry = create_default_renderer_registry()
    result = {"day": "Sunday", "entries": []}

    output = registry.render("get_schedule", result, context)

    assert "<b>Schedule for Sunday:</b>" in output
    assert "No classes are scheduled for this day." in output


def test_golden_week_schedule_key_handling():
    """Verify week schedule handles 'week' key and 'days' key identically."""
    context = _make_context(lab_batch="Batch 1")
    from app.intelligence.rendering.registry import create_default_renderer_registry

    registry = create_default_renderer_registry()

    result_with_week = {
        "status": "confirmed",
        "week": {
            "Tuesday": TUESDAY_RAW_ENTRIES,
        },
    }

    output = registry.render("get_week_schedule", result_with_week, context)

    assert "<b>Weekly Schedule Overview:</b>" in output
    assert "<b>Tuesday</b>" in output
    assert "<b>OS</b>" in output
    assert "No schedule data available for this week" not in output


def test_golden_next_class():
    """Verify single card format for upcoming next class."""
    context = _make_context(lab_batch="Batch 1")
    from app.intelligence.rendering.registry import create_default_renderer_registry

    registry = create_default_renderer_registry()

    result = {
        "has_class": True,
        "entry": {
            "activity_name": "OS",
            "start_time": "10:00",
            "end_time": "11:00",
            "day": "Tuesday",
            "activity_type": "lecture",
            "room": "E-505",
            "lab_batch": None,
        },
    }

    output = registry.render("get_next_class", result, context)

    assert "<b>Next Upcoming Class:</b>" in output
    assert "• <b>Subject:</b> <b>OS</b>" in output
    assert "• <b>Time:</b> <code>10:00 – 11:00</code>" in output
    assert "• <b>Day:</b> Tuesday" in output
    assert "• <b>Type:</b> Lecture" in output
    assert "• <b>Room:</b> <code>E-505</code>" in output


def test_golden_next_class_none():
    """Verify next class when no classes remain."""
    context = _make_context()
    from app.intelligence.rendering.registry import create_default_renderer_registry

    registry = create_default_renderer_registry()

    result = {"has_class": False, "message": "No more classes today or tomorrow."}
    output = registry.render("get_next_class", result, context)

    assert "<b>Next Upcoming Class:</b>" in output
    assert "No more classes today or tomorrow." in output


def test_golden_attendance_summary():
    """Verify attendance summary with badges and deficits."""
    context = _make_context()
    from app.intelligence.rendering.registry import create_default_renderer_registry

    registry = create_default_renderer_registry()

    result = {
        "overall": {
            "cumulative_attended": 66,
            "cumulative_conducted": 80,
            "cumulative_percentage": 82.5,
        },
        "subjects": [
            {
                "subject_name": "OS",
                "cumulative_attended": 17,
                "cumulative_conducted": 20,
                "cumulative_percentage": 85.0,
            },
            {
                "subject_name": "CN",
                "cumulative_attended": 14,
                "cumulative_conducted": 20,
                "cumulative_percentage": 70.0,
                "classes_needed": 1,
            },
            {
                "subject_name": "PSA",
                "cumulative_attended": 18,
                "cumulative_conducted": 20,
                "cumulative_percentage": 90.0,
            },
        ],
    }

    output = registry.render("get_attendance_summary", result, context)

    assert "<b>Attendance Summary:</b>" in output
    assert "• <b>Overall:</b> <code>82.5%</code> (66/80 classes attended)" in output
    assert "• <b>Target:</b> <code>75.0%</code>" in output
    assert f"• <b>Status:</b> {CHECK_MARK} 7.5% above 75% target" in output
    assert "<b>Subject Breakdown:</b>" in output
    assert f"1. <b>OS:</b> <code>85.0%</code> (17/20) — {CHECK_MARK} Met" in output
    warning_str = (
        f"2. <b>CN:</b> <code>70.0%</code> (14/20) — "
        f"{WARNING_SIGN} 1 class needed to reach 75%"
    )
    assert warning_str in output
    s3_str = f"3. <b>PSA:</b> <code>90.0%</code> (18/20) — {CHECK_MARK} Met"
    assert s3_str in output


def test_golden_daily_briefing():
    """Verify daily briefing output."""
    context = _make_context(lab_batch="Batch 1")
    from app.intelligence.rendering.registry import create_default_renderer_registry

    registry = create_default_renderer_registry()

    result = {
        "date": "September 29",
        "day": "Tuesday",
        "classes": TUESDAY_RAW_ENTRIES,
        "attendance": {"percentage": 82.5},
    }

    output = registry.render("get_daily_briefing", result, context)

    assert "<b>Good morning.</b>" in output
    assert "Here is your daily briefing for <b>Tuesday</b> (September 29):" in output
    assert "<b>Today's Schedule (4 sessions):</b>" in output
    s1 = (
        "1. <b>OS</b> (Lecture) — "
        "<code>10:00 – 11:00</code> [Room: <code>E-505</code>]"
    )
    assert s1 in output
    assert "2. <b>CM LAB</b> (Lab) — <code>11:00 – 13:00</code>" in output
    s3 = (
        "3. <b>CN</b> (Lecture) — "
        "<code>13:40 – 14:40</code> [Room: <code>E-505</code>]"
    )
    assert s3 in output
    s4 = "4. <b>CF LAB</b> (Lab, Batch 1) — <code>14:40 – 16:40</code>"
    assert s4 in output
    assert f"• Overall: <code>82.5%</code> — {CHECK_MARK} Above target" in output
    assert "Have a productive day." in output


def test_style_contract_greeting_removal():
    """Verify that repetitive 'Hey Harsh!' greetings are stripped."""
    assert clean_greetings("Hey Harsh! What's up?") == "What's up?"
    assert (
        clean_greetings("Hello Harsh, your timetable is ready.")
        == "your timetable is ready."
    )
    assert (
        clean_greetings("Good morning Harsh! Here are your classes.")
        == "Here are your classes."
    )

    sanitized = sanitize_conversational_response(
        "Hello Harsh! Your timetable is confirmed."
    )
    assert "Hey" not in sanitized
    assert "Hello" not in sanitized
    assert "Sir" in sanitized


@pytest.mark.asyncio
async def test_renderer_registry_dispatch_in_conversation_service():
    """Verify ConversationService._execute_tool routes to RendererRegistry cleanly."""
    context = _make_context(lab_batch="Batch 1")

    # Mock tool registry with a dummy tool
    mock_tool = MagicMock()
    mock_tool.name = "get_schedule"
    mock_tool.execute = AsyncMock(
        return_value={
            "day": "Tuesday",
            "date": "2026-09-29",
            "entries": TUESDAY_RAW_ENTRIES,
        }
    )

    mock_tool_registry = MagicMock()
    mock_tool_registry.get.return_value = mock_tool

    # Mock custom renderer
    custom_renderer = MagicMock()
    custom_renderer.render.return_value = "Custom Rendered Schedule, Sir."

    registry = RendererRegistry()
    registry.register("get_schedule", custom_renderer)

    service = ConversationService(
        tool_registry_instance=mock_tool_registry,
        renderer_registry=registry,
    )

    intent_result = IntentResult(
        tool_request={"name": "get_schedule", "arguments": {}},
        confidence=0.9,
    )

    response, _ = await service._execute_tool(context, intent_result)

    assert response == "Custom Rendered Schedule, Sir."
    custom_renderer.render.assert_called_once()
