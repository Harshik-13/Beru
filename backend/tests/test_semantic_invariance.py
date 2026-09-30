"""Semantic-Invariance and Schedule Analytics Tests.

Verifies:
1. Natural language query variations produce semantically equivalent verified schedules.
2. Encyclopedic tools (find_activity_details, find_faculty_details, find_room_details)
   render correctly with deterministic missing-field omission.
3. Schedule analytics (classes vs labs, frequency, workload, free slots) compute
   deterministic metrics and render with high visual standard.
4. Style contract compliance: 'Sir' injected by ResponseStyleLayer, bold labels, code tags.
"""

import uuid
from datetime import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.intelligence.models.context import (
    ConversationContext,
    StudentContext,
    StudentProfile,
)
from app.intelligence.rendering.registry import create_default_renderer_registry
from app.intelligence.rendering.schedule_renderer import ScheduleRenderer
from app.intelligence.tools.timetable_tools import (
    find_activity_details,
    find_faculty_details,
    find_room_details,
    query_schedule_analytics,
)
from app.models.timetable import ActivityType, LabBatch, Timetable, TimetableEntry

TEST_STUDENT_ID = uuid.UUID("90627ae2-5050-444f-8be0-00dbb1fef469")
TEST_TIMETABLE_ID = uuid.UUID("a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")


def _make_context(lab_batch: str | None = "Batch 1") -> StudentContext:
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


def _make_mock_entries():
    """Create sample entries matching actual parsed college timetable."""
    return [
        # Monday
        TimetableEntry(
            id=uuid.uuid4(),
            timetable_id=TEST_TIMETABLE_ID,
            day_of_week=0,
            start_time=time(10, 0),
            end_time=time(11, 0),
            activity_name="PSA",
            activity_type=ActivityType.ACADEMIC,
            room="E-505",
            faculty="Dr. Sharma",
        ),
        TimetableEntry(
            id=uuid.uuid4(),
            timetable_id=TEST_TIMETABLE_ID,
            day_of_week=0,
            start_time=time(11, 0),
            end_time=time(12, 0),
            activity_name="OOPJ",
            activity_type=ActivityType.ACADEMIC,
            room="E-505",
            faculty="Prof. Verma",
        ),
        # Tuesday (includes contiguous lab)
        TimetableEntry(
            id=uuid.uuid4(),
            timetable_id=TEST_TIMETABLE_ID,
            day_of_week=1,
            start_time=time(10, 0),
            end_time=time(11, 0),
            activity_name="OS",
            activity_type=ActivityType.ACADEMIC,
            room="E-505",
            faculty="Dr. Rao",
        ),
        TimetableEntry(
            id=uuid.uuid4(),
            timetable_id=TEST_TIMETABLE_ID,
            day_of_week=1,
            start_time=time(11, 0),
            end_time=time(12, 0),
            activity_name="CM LAB",
            activity_type=ActivityType.LAB,
            room="Lab-1",
            faculty="Prof. Patel",
        ),
        TimetableEntry(
            id=uuid.uuid4(),
            timetable_id=TEST_TIMETABLE_ID,
            day_of_week=1,
            start_time=time(12, 0),
            end_time=time(13, 0),
            activity_name="CM LAB",
            activity_type=ActivityType.LAB,
            room="Lab-1",
            faculty="Prof. Patel",
        ),
        # Wednesday (DV LAB 2 slots for Batch 1)
        TimetableEntry(
            id=uuid.uuid4(),
            timetable_id=TEST_TIMETABLE_ID,
            day_of_week=2,
            start_time=time(13, 40),
            end_time=time(14, 40),
            activity_name="DV LAB",
            activity_type=ActivityType.LAB,
            room="E-505",
            lab_batch=LabBatch.BATCH_1,
            faculty="Dr. Reddy",
        ),
        TimetableEntry(
            id=uuid.uuid4(),
            timetable_id=TEST_TIMETABLE_ID,
            day_of_week=2,
            start_time=time(14, 40),
            end_time=time(15, 40),
            activity_name="DV LAB",
            activity_type=ActivityType.LAB,
            room="E-505",
            lab_batch=LabBatch.BATCH_1,
            faculty="Dr. Reddy",
        ),
    ]


@pytest.fixture
def mock_timetable_service():
    service = MagicMock()
    timetable = Timetable(
        id=TEST_TIMETABLE_ID,
        student_id=TEST_STUDENT_ID,
        default_classroom="E-505",
        section="A",
        branch="CSE",
        academic_year="2024-2025",
        semester=5,
    )
    service.get_confirmed_timetable = AsyncMock(return_value=timetable)
    service.get_pending_timetable = AsyncMock(return_value=None)
    
    entries = _make_mock_entries()
    entry_repo = MagicMock()
    entry_repo.get_for_timetable = AsyncMock(return_value=entries)
    service.entry_repo = entry_repo

    student_repo = MagicMock()
    mock_student = MagicMock()
    mock_student.lab_batch = LabBatch.BATCH_1
    student_repo.get_by_id = AsyncMock(return_value=mock_student)
    service.student_repo = student_repo

    return service


# ===========================================================================
# 1. Semantic-Invariance Tests: Different phrasing -> Equivalent result
# ===========================================================================


class TestSemanticInvariance:
    """Verifies that varied natural queries resolve to identical schedule presentations."""

    def test_semantic_equivalence_of_tuesday_schedule(self):
        """Five different Tuesday phrasing variations must produce equivalent rendered content."""
        renderer = ScheduleRenderer()
        registry = create_default_renderer_registry()
        context = _make_context(lab_batch="Batch 1")

        # Result representation from get_schedule_for_weekday or get_schedule
        tuesday_result = {
            "status": "confirmed",
            "day": "Tuesday",
            "entries": [
                {
                    "day_of_week": 1,
                    "start_time": "10:00",
                    "end_time": "11:00",
                    "activity_name": "OS",
                    "activity_type": "academic",
                    "room": "E-505",
                    "faculty": "Dr. Rao",
                },
                {
                    "day_of_week": 1,
                    "start_time": "11:00",
                    "end_time": "12:00",
                    "activity_name": "CM LAB",
                    "activity_type": "lab",
                    "room": "Lab-1",
                    "faculty": "Prof. Patel",
                },
                {
                    "day_of_week": 1,
                    "start_time": "12:00",
                    "end_time": "13:00",
                    "activity_name": "CM LAB",
                    "activity_type": "lab",
                    "room": "Lab-1",
                    "faculty": "Prof. Patel",
                },
            ],
        }

        variations = [
            ("get_schedule_for_weekday", tuesday_result, "What do I have on Tuesday?"),
            ("get_schedule", tuesday_result, "Tuesday schedule"),
            ("get_schedule_for_weekday", tuesday_result, "Show my classes for Tuesday"),
            ("get_schedule", tuesday_result, "What is my Tuesday timetable?"),
            ("get_schedule_for_weekday", tuesday_result, "Tuesday classes please"),
        ]

        rendered_outputs = [
            registry.render(tool, res, student_context=context, user_message=query)
            for tool, res, query in variations
        ]

        # All 5 variations must be completely identical in presentation and data
        first_output = rendered_outputs[0]
        for idx, out in enumerate(rendered_outputs[1:], 2):
            assert out == first_output, f"Variation {idx} differed from canonical presentation"

        # Check semantic completeness of the unified output
        assert "Schedule for Tuesday, Sir:" in first_output
        assert "1. <b>OS</b>" in first_output
        assert "10:00 – 11:00" in first_output
        assert "<code>E-505</code>" in first_output
        assert "Dr. Rao" in first_output
        # 11:00-12:00 and 12:00-13:00 CM LAB must be merged into 11:00 – 13:00
        assert "2. <b>CM LAB</b>" in first_output
        assert "11:00 – 13:00" in first_output
        assert "2 sessions scheduled." in first_output


# ===========================================================================
# 2. Encyclopedic Tool & Renderer Tests
# ===========================================================================


class TestActivityDetailsRendering:
    """Test find_activity_details tool execution and rendering."""

    @pytest.mark.asyncio
    async def test_find_activity_details_dv_lab(self, mock_timetable_service):
        registry = create_default_renderer_registry()
        context = _make_context(lab_batch="Batch 1")

        result = await find_activity_details(
            mock_timetable_service,
            str(TEST_STUDENT_ID),
            query="DV LAB",
        )

        assert result["status"] == "confirmed"
        assert result["found"] is True
        assert result["count"] == 1
        # Contiguous slots 13:40-14:40 and 14:40-15:40 must be merged
        match = result["matches"][0]
        assert match["start_time"] == "13:40"
        assert match["end_time"] == "15:40"
        assert match["room"] == "E-505"
        assert match["faculty"] == "Dr. Reddy"

        # Render output
        rendered = registry.render("find_activity_details", result, context)
        assert "Activity Details — DV LAB, Sir:" in rendered
        assert "1. <b>DV LAB</b>" in rendered
        assert "13:40 – 15:40" in rendered
        assert "<code>E-505</code>" in rendered
        assert "Dr. Reddy" in rendered

    def test_activity_details_missing_fields_omitted(self):
        registry = create_default_renderer_registry()
        context = _make_context(lab_batch="Batch 1")

        result = {
            "status": "confirmed",
            "query": "SPORTS",
            "found": True,
            "count": 1,
            "matches": [
                {
                    "activity_name": "SPORTS",
                    "day": "Wednesday",
                    "start_time": "15:40",
                    "end_time": "16:40",
                    "activity_type": "activity",
                    "room": None,
                    "faculty": None,
                }
            ],
        }

        rendered = registry.render("find_activity_details", result, context)
        assert "SPORTS" in rendered
        assert "15:40 – 16:40" in rendered
        # Omission contract: room and faculty lines must NOT be present
        assert "Room" not in rendered
        assert "Faculty" not in rendered
        assert "None" not in rendered
        assert "Not specified" not in rendered


class TestFacultyDetailsRendering:
    """Test find_faculty_details tool execution and rendering."""

    @pytest.mark.asyncio
    async def test_find_faculty_directory(self, mock_timetable_service):
        registry = create_default_renderer_registry()
        context = _make_context()

        result = await find_faculty_details(
            mock_timetable_service,
            str(TEST_STUDENT_ID),
            list_all=True,
        )

        assert result["found"] is True
        assert len(result["faculty_list"]) >= 3

        rendered = registry.render("find_faculty_details", result, context)
        assert "Faculty Directory, Sir:" in rendered
        assert "• <b>OS:</b> Dr. Rao" in rendered
        assert "• <b>PSA:</b> Dr. Sharma" in rendered

    @pytest.mark.asyncio
    async def test_find_faculty_by_subject(self, mock_timetable_service):
        registry = create_default_renderer_registry()
        context = _make_context()

        result = await find_faculty_details(
            mock_timetable_service,
            str(TEST_STUDENT_ID),
            subject="OS",
        )

        assert result["found"] is True
        assert "Dr. Rao" in result["faculty_names"]

        rendered = registry.render("find_faculty_details", result, context)
        assert "Faculty — OS, Sir:" in rendered
        assert "• <b>Instructor:</b> Dr. Rao" in rendered
        assert "<code>E-505</code>" in rendered


class TestRoomDetailsRendering:
    """Test find_room_details tool execution and rendering."""

    @pytest.mark.asyncio
    async def test_find_default_classroom_schedule(self, mock_timetable_service):
        registry = create_default_renderer_registry()
        context = _make_context()

        result = await find_room_details(
            mock_timetable_service,
            str(TEST_STUDENT_ID),
            room="E-505",
        )

        assert result["found"] is True
        assert result["is_default_classroom"] is True

        rendered = registry.render("find_room_details", result, context)
        assert "Room Details — <code>E-505</code>, Sir:" in rendered
        assert "<code>E-505</code> is your default classroom for regular lectures." in rendered
        assert "PSA" in rendered
        assert "OOPJ" in rendered


# ===========================================================================
# 3. Schedule Analytics Tests
# ===========================================================================


class TestScheduleAnalytics:
    """Test query_schedule_analytics tool and formatting."""

    @pytest.mark.asyncio
    async def test_classes_vs_labs_breakdown(self, mock_timetable_service):
        registry = create_default_renderer_registry()
        context = _make_context()

        result = await query_schedule_analytics(
            mock_timetable_service,
            str(TEST_STUDENT_ID),
            metric="classes_vs_labs",
        )

        assert result["status"] == "confirmed"
        assert result["theory_count"] == 3  # PSA, OOPJ, OS
        assert result["lab_count"] == 2    # CM LAB (merged), DV LAB (merged)
        assert result["theory_hours"] == 3.0
        assert result["lab_hours"] == 4.0  # 2h CM LAB + 2h DV LAB
        assert result["total_hours"] == 7.0

        rendered = registry.render("query_schedule_analytics", result, context)
        assert "Schedule Breakdown, Sir:" in rendered
        assert "• <b>Theory Classes:</b> <code>3</code> (3.0 hrs)" in rendered
        assert "• <b>Lab Sessions:</b> <code>2</code> (4.0 hrs)" in rendered
        assert "• <b>Total Workload:</b> <code>5</code> sessions (7.0 hrs/week)" in rendered

    @pytest.mark.asyncio
    async def test_subject_frequency(self, mock_timetable_service):
        registry = create_default_renderer_registry()
        context = _make_context()

        result = await query_schedule_analytics(
            mock_timetable_service,
            str(TEST_STUDENT_ID),
            metric="subject_count",
            subject="PSA",
            scope="entire_week",
        )

        assert result["total_in_week"] == 1
        rendered = registry.render("query_schedule_analytics", result, context)
        assert "Course Frequency — PSA, Sir:" in rendered
        assert "• <b>Total in Week:</b> <code>1</code> sessions" in rendered
        assert "Monday: <code>10:00 – 11:00</code>" in rendered

    @pytest.mark.asyncio
    async def test_daily_workload(self, mock_timetable_service):
        registry = create_default_renderer_registry()
        context = _make_context()

        result = await query_schedule_analytics(
            mock_timetable_service,
            str(TEST_STUDENT_ID),
            metric="daily_workload",
        )

        assert result["status"] == "confirmed"
        assert result["heaviest"][0] == "Tuesday"  # OS (1h) + CM LAB (2h) = 3.0h
        assert result["heaviest"][1] == 3.0

        rendered = registry.render("query_schedule_analytics", result, context)
        assert "Weekly Workload Distribution, Sir:" in rendered
        assert "• <b>Tuesday:</b> <code>2</code> sessions (3.0 hrs)" in rendered
        assert "• <b>Busiest Day:</b> Tuesday (3.0 hrs)" in rendered

    def test_free_slots_rendering(self):
        registry = create_default_renderer_registry()
        context = _make_context()

        result = {
            "status": "confirmed",
            "metric": "free_slots",
            "day": "Tuesday",
            "free_slots": [
                {"start_time": "13:00", "end_time": "14:40"},
            ],
        }

        rendered = registry.render("query_schedule_analytics", result, context)
        assert "Free Slots — Tuesday, Sir:" in rendered
        assert "• <code>13:00 – 14:40</code>" in rendered
