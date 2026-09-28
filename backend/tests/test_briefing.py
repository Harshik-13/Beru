"""Focused Daily Morning Briefing tests."""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime, time, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.intelligence.models.context import StudentProfile
from app.intelligence.services.attendance_service import (
    AttendanceSummaryResult,
    BelowTargetResult,
    OverallAttendanceResult,
)
from app.intelligence.services.briefing import (
    BriefingResult,
    BriefingService,
    DailyBriefing,
)
from app.intelligence.services.context_builder import create_student_context
from app.models.timetable import (
    ActivityType,
    Timetable,
    TimetableEntry,
    TimetableStatus,
)

FIXED_NOW = datetime(2026, 9, 28, 6, 30, tzinfo=UTC)  # Monday
FIXED_TODAY = date(2026, 9, 28)


def make_timetable(confirmed_at: datetime | None = None) -> Timetable:
    return Timetable(
        student_id=uuid4(),
        status=TimetableStatus.CONFIRMED,
        confirmed_at=confirmed_at or (FIXED_NOW - timedelta(days=3)),
    )


def make_entry(
    name: str,
    start: time,
    end: time,
    room: str | None = None,
    faculty: str | None = None,
    activity_type: ActivityType = ActivityType.ACADEMIC,
    day: int = 0,
) -> TimetableEntry:
    return TimetableEntry(
        timetable_id=uuid4(),
        day_of_week=day,
        start_time=start,
        end_time=end,
        activity_name=name,
        activity_type=activity_type,
        room=room,
        faculty=faculty,
    )


def make_summary(
    attended: int = 95,
    conducted: int = 121,
    pct: float = 78.51,
    captured_at: datetime | None = None,
) -> AttendanceSummaryResult:
    cap = captured_at or (FIXED_NOW - timedelta(days=1))
    return AttendanceSummaryResult(
        overall=OverallAttendanceResult(
            attended=attended,
            conducted=conducted,
            percentage=pct,
            captured_at=cap,
            source="doctus",
            semester_id=None,
        ),
        subjects=(),
        captured_at=cap,
        source="doctus",
        semester_id=None,
    )


def make_below(
    subject_code: str = "CHM101",
    subject_name: str | None = "Chemistry",
    cum_pct: float = 71.2,
    target: float = 75.0,
    deficit: float = 3.8,
) -> BelowTargetResult:
    return BelowTargetResult(
        subject_code=subject_code,
        subject_name=subject_name,
        cumulative_percentage=cum_pct,
        target_percentage=target,
        deficit=deficit,
    )


def make_context(
    name: str | None = "Priya",
    target: float | None = 75.0,
) -> StudentProfile:
    student_id = uuid4()
    return create_student_context(
        student_id,
        profile=StudentProfile(
            student_id=student_id, name=name, attendance_target=target
        ),
    )


def make_service(
    timetable: Timetable | None = None,
    schedule: list[TimetableEntry] | None = None,
    summary: AttendanceSummaryResult | None = None,
    below: tuple[BelowTargetResult, ...] = (),
    *,
    now: datetime = FIXED_NOW,
    today: date = FIXED_TODAY,
):
    ts = MagicMock()
    ts.get_confirmed_timetable = AsyncMock(return_value=timetable)
    ts.get_today_schedule = AsyncMock(return_value=schedule or [])
    ats = MagicMock()
    ats.get_attendance_summary = AsyncMock(return_value=summary)
    ats.get_subjects_below_target = AsyncMock(return_value=below)
    return (
        BriefingService(ts, ats, now=lambda: now, today=lambda: today),
        ts,
        ats,
    )


class TestBriefingSchedule:
    """Tests for schedule rendering."""

    @pytest.mark.asyncio
    async def test_classes_rendered_in_chronological_order(self):
        schedule = [
            make_entry("Physics", time(10, 0), time(10, 50)),
            make_entry("Mathematics", time(9, 0), time(9, 50)),
        ]
        service, _, _ = make_service(timetable=make_timetable(), schedule=schedule)
        ctx = make_context()
        result = await service.generate_briefing(ctx)

        # Facts are sorted by start_time
        assert result.facts.classes[0].subject_name == "Mathematics"
        assert result.facts.classes[1].subject_name == "Physics"
        # Message reflects order
        msg = result.message
        assert msg.index("09:00") < msg.index("10:00")

    @pytest.mark.asyncio
    async def test_class_line_includes_time_range(self):
        schedule = [make_entry("Mathematics", time(9, 0), time(9, 50))]
        service, _, _ = make_service(timetable=make_timetable(), schedule=schedule)
        ctx = make_context()
        result = await service.generate_briefing(ctx)
        assert "09:00-09:50 Mathematics" in result.message

    @pytest.mark.asyncio
    async def test_class_line_includes_room_and_faculty(self):
        schedule = [
            make_entry(
                "Mathematics", time(9, 0), time(9, 50), room="204", faculty="Dr. Sharma"
            )
        ]
        service, _, _ = make_service(timetable=make_timetable(), schedule=schedule)
        ctx = make_context()
        result = await service.generate_briefing(ctx)
        assert "[Room 204, Dr. Sharma]" in result.message

    @pytest.mark.asyncio
    async def test_class_without_room_or_faculty_omits_detail(self):
        schedule = [make_entry("Free Study", time(9, 0), time(9, 50))]
        service, _, _ = make_service(timetable=make_timetable(), schedule=schedule)
        ctx = make_context()
        result = await service.generate_briefing(ctx)
        line = next(ln for ln in result.message.splitlines() if "Free Study" in ln)
        assert "Room" not in line
        assert "Dr." not in line

    @pytest.mark.asyncio
    async def test_no_classes_renders_no_classes_message(self):
        # Sunday (day 6) or empty schedule
        service, _, _ = make_service(timetable=make_timetable(), schedule=[])
        ctx = make_context()
        result = await service.generate_briefing(ctx)
        assert "📚 No classes today. 🎉" in result.message
        assert result.facts.classes == ()

    @pytest.mark.asyncio
    async def test_activity_type_captured_in_facts(self):
        schedule = [
            make_entry(
                "Physics Lab", time(9, 0), time(10, 50), activity_type=ActivityType.LAB
            )
        ]
        service, _, _ = make_service(timetable=make_timetable(), schedule=schedule)
        ctx = make_context()
        result = await service.generate_briefing(ctx)
        assert result.facts.classes[0].activity_type == "lab"


class TestBriefingTimetableStatus:
    """Tests for timetable confirmation state."""

    @pytest.mark.asyncio
    async def test_confirmed_timetable_marks_confirmed(self):
        timetable = make_timetable()
        service, _, _ = make_service(timetable=timetable, schedule=[])
        ctx = make_context()
        result = await service.generate_briefing(ctx)

        assert result.facts.timetable_confirmed is True
        assert result.facts.timetable_confirmed_at == timetable.confirmed_at
        assert "No confirmed timetable" not in result.message

    @pytest.mark.asyncio
    async def test_unconfirmed_timetable_emits_warning(self):
        service, ts, _ = make_service(timetable=None, schedule=[])
        ctx = make_context()
        result = await service.generate_briefing(ctx)

        # get_confirmed_timetable called, get_today_schedule NOT called
        ts.get_confirmed_timetable.assert_awaited_once()
        ts.get_today_schedule.assert_not_awaited()
        assert (
            "No confirmed timetable — class schedule may be incomplete."
            in result.message
        )
        assert result.facts.timetable_confirmed is False
        assert result.facts.classes == ()


class TestBriefingAttendance:
    """Tests for attendance summary and below-target rendering."""

    @pytest.mark.asyncio
    async def test_attendance_summary_rendered_with_counts(self):
        summary = make_summary(attended=95, conducted=121, pct=78.51)
        service, _, _ = make_service(
            timetable=make_timetable(), schedule=[], summary=summary
        )
        ctx = make_context(target=75.0)
        result = await service.generate_briefing(ctx)

        assert "📊 Attendance: 78.5% (95/121)" in result.message
        assert "synced 27 Sep 2026 via doctus" in result.message
        assert result.facts.attendance is not None
        assert result.facts.attendance.overall_percentage == 78.51
        assert result.facts.attendance.attended == 95
        assert result.facts.attendance.conducted == 121

    @pytest.mark.asyncio
    async def test_below_target_subjects_listed_with_deficit(self):
        summary = make_summary()
        below = (make_below(),)
        service, _, ats = make_service(
            timetable=make_timetable(), schedule=[], summary=summary, below=below
        )
        ctx = make_context(target=75.0)
        result = await service.generate_briefing(ctx)

        ats.get_subjects_below_target.assert_awaited_once_with(
            student_id=str(ctx.student_id), target_percentage=75.0
        )
        assert "⚠️ Below 75% target:" in result.message
        assert "• Chemistry: 71.2% (short by 3.8%)" in result.message
        assert len(result.facts.attendance.below_target) == 1

    @pytest.mark.asyncio
    async def test_all_subjects_above_target_message(self):
        summary = make_summary()
        service, _, ats = make_service(
            timetable=make_timetable(), schedule=[], summary=summary, below=()
        )
        ctx = make_context(target=75.0)
        result = await service.generate_briefing(ctx)

        ats.get_subjects_below_target.assert_awaited_once()
        assert "✅ All subjects at or above the 75% target." in result.message

    @pytest.mark.asyncio
    async def test_missing_attendance_data_emits_warning(self):
        service, _, _ = make_service(
            timetable=make_timetable(), schedule=[], summary=None
        )
        ctx = make_context(target=75.0)
        result = await service.generate_briefing(ctx)

        assert "📊 Attendance: no data yet." in result.message
        assert "No attendance data yet — sync your college portal." in result.message
        assert result.facts.attendance is None
        assert result.facts.attendance_stale is True

    @pytest.mark.asyncio
    async def test_stale_attendance_emits_warning(self):
        summary = make_summary(captured_at=FIXED_NOW - timedelta(days=10))
        service, _, _ = make_service(
            timetable=make_timetable(), schedule=[], summary=summary
        )
        ctx = make_context(target=75.0)
        result = await service.generate_briefing(ctx)

        assert "Attendance last synced over 7 days ago" in result.message
        assert result.facts.attendance_stale is True

    @pytest.mark.asyncio
    async def test_fresh_attendance_has_no_stale_warning(self):
        summary = make_summary(captured_at=FIXED_NOW - timedelta(days=1))
        service, _, _ = make_service(
            timetable=make_timetable(), schedule=[], summary=summary
        )
        ctx = make_context(target=75.0)
        result = await service.generate_briefing(ctx)

        assert "synced over 7 days" not in result.message
        assert result.facts.attendance_stale is False

    @pytest.mark.asyncio
    async def test_no_attendance_target_skips_below_target_query(self):
        summary = make_summary()
        service, _, ats = make_service(
            timetable=make_timetable(), schedule=[], summary=summary
        )
        ctx = make_context(target=None)
        result = await service.generate_briefing(ctx)

        ats.get_subjects_below_target.assert_not_awaited()
        # No target section in message
        assert "target" not in result.message.lower()
        assert result.facts.attendance.target_percentage is None
        assert result.facts.attendance.below_target == ()


class TestBriefingIsolation:
    """Tests for transport-agnosticism and identity correctness."""

    def test_module_has_no_transport_dependencies(self):
        import app.intelligence.services.briefing as briefing_module

        source = inspect.getsource(briefing_module).lower()
        # Check for actual import statements, not docstring mentions
        assert "import telegram" not in source
        assert "from telegram" not in source
        assert "import whatsapp" not in source
        assert "from whatsapp" not in source

    @pytest.mark.asyncio
    async def test_student_name_comes_from_profile(self):
        service, _, _ = make_service(timetable=make_timetable(), schedule=[])
        ctx = make_context(name="Rahul")
        result = await service.generate_briefing(ctx)
        assert "Good morning, Rahul!" in result.message

    @pytest.mark.asyncio
    async def test_unnamed_student_uses_fallback_display_name(self):
        service, _, _ = make_service(timetable=make_timetable(), schedule=[])
        ctx = make_context(name=None)
        result = await service.generate_briefing(ctx)
        assert result.message.startswith("☀️ Good morning, Student ")
        assert str(ctx.student_id)[:8] in result.message

    @pytest.mark.asyncio
    async def test_attendance_values_passed_through_verbatim(self):
        summary = make_summary(attended=100, conducted=200, pct=50.0)
        service, _, _ = make_service(
            timetable=make_timetable(), schedule=[], summary=summary
        )
        ctx = make_context(target=75.0)
        result = await service.generate_briefing(ctx)

        assert result.facts.attendance.overall_percentage == 50.0
        assert result.facts.attendance.attended == 100
        assert result.facts.attendance.conducted == 200

    @pytest.mark.asyncio
    async def test_generate_briefing_returns_structured_result(self):
        service, _, _ = make_service(timetable=make_timetable(), schedule=[])
        ctx = make_context()
        result = await service.generate_briefing(ctx)

        assert isinstance(result, BriefingResult)
        assert isinstance(result.facts, DailyBriefing)
        assert isinstance(result.message, str)
        assert result.message == service.render(result.facts)
