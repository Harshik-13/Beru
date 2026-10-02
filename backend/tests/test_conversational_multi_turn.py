"""
Tests for natural-language multi-turn conversations, dialogue state tracking,
and dynamic course code correlation from confirmed timetables.
"""

from datetime import datetime, time, UTC
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import pytest

from app.intelligence.models.context import (
    ConversationContext,
    ReferencedEntity,
    StudentContext,
    StudentProfile,
)
from app.intelligence.services.context_builder import create_student_context
from app.intelligence.providers.base import LLMResponse, LLMToolCall
from app.intelligence.services.attendance_service import (
    AttendanceService,
    OverallAttendanceResult,
    SubjectAttendanceResult,
    AttendanceSummaryResult,
)
from app.intelligence.services.conversation import ConversationService
from app.intelligence.services.timetable_service import TimetableService
from app.models.timetable import ActivityType, Timetable, TimetableEntry, TimetableStatus


class FakeLLMProvider:
    """Mock LLM provider that simulates function calling and response generation."""

    def __init__(self, turns: list[dict]):
        self.turns = list(turns)
        self.turn_index = 0
        self.recorded_messages = []

    async def chat_completion(
        self,
        messages: list,
        tools: list | None = None,
        tool_choice: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self.recorded_messages.append(messages)
        if self.turn_index < len(self.turns):
            turn_spec = self.turns[self.turn_index]
            self.turn_index += 1
            t_calls = []
            if "tool_calls" in turn_spec:
                for idx, tc in enumerate(turn_spec["tool_calls"]):
                    t_calls.append(
                        LLMToolCall(
                            id=tc.get("id", f"call_{idx}"),
                            name=tc["name"],
                            arguments=tc.get("arguments", {}),
                        )
                    )
            return LLMResponse(
                content=turn_spec.get("text"),
                tool_calls=tuple(t_calls),
            )
        return LLMResponse(content="Default fallback response")


@pytest.mark.asyncio
async def test_multi_turn_attendance_and_per_subject_followup():
    """
    Test Turn 1: "What's my attendance?" -> get_overall_attendance -> overall + monthly attendance.
    Test Turn 2: "Per subject?" -> get_attendance_summary -> enriched subjects, no raw dict.
    """
    student_id = uuid4()
    profile = StudentProfile(student_id=student_id, name="Harsh", attendance_target=75.0)
    ctx = create_student_context(student_id, profile)

    # Turn 1: user asks attendance -> LLM calls get_overall_attendance
    # Turn 2: user asks "Per subject?" -> LLM calls get_attendance_summary based on dialogue context
    llm = FakeLLMProvider([
        {
            "tool_calls": [{"name": "get_overall_attendance", "arguments": {"student_id": str(student_id)}}],
        },
        {
            "tool_calls": [{"name": "get_attendance_summary", "arguments": {"student_id": str(student_id)}}],
        },
    ])

    mock_att_service = MagicMock(spec=AttendanceService)
    now = datetime.now(UTC)
    mock_att_service.get_overall_attendance = AsyncMock(
        return_value=OverallAttendanceResult(
            attended=178,
            conducted=306,
            percentage=58.17,
            captured_at=now,
            source="doctus",
            semester_id="102",
            monthly_attended=6,
            monthly_conducted=6,
            monthly_percentage=100.0,
            monthly_period="October, 2026",
        )
    )
    mock_att_service.get_attendance_summary = AsyncMock(
        return_value=AttendanceSummaryResult(
            overall=OverallAttendanceResult(
                attended=178,
                conducted=306,
                percentage=58.17,
                captured_at=now,
                source="doctus",
                semester_id="102",
                monthly_attended=6,
                monthly_conducted=6,
                monthly_percentage=100.0,
                monthly_period="October, 2026",
            ),
            subjects=(
                SubjectAttendanceResult(
                    subject_code="25PC1CS201",
                    subject_name="OOPJ",
                    monthly_attended=2,
                    monthly_conducted=2,
                    monthly_percentage=100.0,
                    monthly_period="October, 2026",
                    cumulative_attended=24,
                    cumulative_conducted=35,
                    cumulative_percentage=68.57,
                    classes_needed=9,
                ),
                SubjectAttendanceResult(
                    subject_code="25PC1CY201",
                    subject_name="CN",
                    monthly_attended=1,
                    monthly_conducted=1,
                    monthly_percentage=100.0,
                    monthly_period="October, 2026",
                    cumulative_attended=28,
                    cumulative_conducted=35,
                    cumulative_percentage=80.0,
                    classes_needed=0,
                ),
            ),
            captured_at=now,
            source="doctus",
            semester_id="102",
        )
    )

    conv_svc = ConversationService(llm_provider=llm, attendance_service=mock_att_service)

    # Turn 1
    resp1, ctx1 = await conv_svc.process_message(ctx, "What's my attendance?")
    assert "Overall Attendance:" in resp1
    assert "58.2%" in resp1 or "58.17%" in resp1
    assert "Monthly (October, 2026):" in resp1
    assert "100.0%" in resp1

    # Verify dialogue state was recorded
    assert ctx1.conversation.last_domain == "attendance"
    assert ctx1.conversation.last_tool == "get_overall_attendance"
    assert ctx1.conversation.last_semester == "102"

    # Turn 2: "Per subject?"
    resp2, ctx2 = await conv_svc.process_message(ctx1, "Per subject?")
    assert "Subject Breakdown:" in resp2
    assert "OOPJ (25PC1CS201)" in resp2
    assert "CN (25PC1CY201)" in resp2
    assert "classes needed" in resp2.lower()
    # Confirm no raw dictionary or list dump
    assert not resp2.strip().startswith("{")
    assert not resp2.strip().startswith("[")
    assert "subject_codes" not in resp2

    # Verify dialogue state updated
    assert ctx2.conversation.last_tool == "get_attendance_summary"


@pytest.mark.asyncio
async def test_get_course_mapping_tool_execution():
    """Test get_course_mapping returns friendly subject names from confirmed timetable."""
    student_id = uuid4()
    mock_tt_service = MagicMock(spec=TimetableService)
    mock_tt_service.get_course_mapping = AsyncMock(
        return_value=[
            {
                "course_code": "25PC1CS201",
                "course_name": "OOPJ",
                "activity_type": "academic",
                "status": "resolved",
                "source": "confirmed_timetable",
            },
            {
                "course_code": "25PC1CY201",
                "course_name": "CN",
                "activity_type": "academic",
                "status": "resolved",
                "source": "confirmed_timetable",
            },
        ]
    )

    llm = FakeLLMProvider([
        {
            "tool_calls": [{"name": "get_course_mapping", "arguments": {"student_id": str(student_id)}}],
        },
        # Synthesis turn for atomic query tool
        {
            "text": "The course code 25PC1CS201 stands for Object Oriented Programming through Java (OOPJ).",
        },
    ])

    profile = StudentProfile(student_id=student_id, name="Harsh")
    ctx = create_student_context(student_id, profile)
    conv_svc = ConversationService(llm_provider=llm, timetable_service=mock_tt_service)

    resp, ctx_res = await conv_svc.process_message(ctx, "What does 25PC1CS201 stand for?")
    assert "OOPJ" in resp
    assert ctx_res.conversation.last_tool == "get_course_mapping"
    assert ctx_res.conversation.last_domain == "timetable"


@pytest.mark.asyncio
async def test_course_mapping_conflict_reporting():
    """Test that conflicting course names in confirmed timetable produce conflict status rather than guessing."""
    student_id = uuid4()
    mock_session = AsyncMock()

    tt_service = TimetableService(mock_session)
    mock_timetable = MagicMock(spec=Timetable)
    mock_timetable.id = uuid4()
    tt_service.get_confirmed_timetable = AsyncMock(return_value=mock_timetable)

    entry1 = MagicMock(spec=TimetableEntry)
    entry1.course_code = "25PC1CS201"
    entry1.activity_name = "OOPJ"
    entry1.activity_type = ActivityType.ACADEMIC

    entry2 = MagicMock(spec=TimetableEntry)
    entry2.course_code = "25PC1CS201"
    entry2.activity_name = "Java Programming"
    entry2.activity_type = ActivityType.ACADEMIC

    tt_service.entry_repo.get_for_timetable = AsyncMock(return_value=[entry1, entry2])

    mapping = await tt_service.get_course_mapping(student_id)
    assert len(mapping) == 1
    item = mapping[0]
    assert item["course_code"] == "25PC1CS201"
    assert item["status"] == "conflict"
    assert "alternatives" in item
    assert sorted(item["alternatives"]) == ["Java Programming", "OOPJ"]
    assert "Java Programming / OOPJ" in item["course_name"]
