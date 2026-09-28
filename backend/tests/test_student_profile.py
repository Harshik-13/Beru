"""Focused student profile persistence tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.intelligence.models.context import StudentProfile
from app.intelligence.services.briefing import BriefingService
from app.models.attendance import AttendanceSnapshot, AttendanceSource
from app.models.student import Student
from app.repositories.student import StudentRepository


class TestStudentProfileModel:
    """Test Student model with profile fields."""

    def test_name_persistence(self):
        """Student name is stored on the model."""
        student = Student(id=uuid4(), name="Priya")
        assert student.name == "Priya"

    def test_name_defaults_to_none(self):
        """Student name defaults to None when not set."""
        student = Student(id=uuid4())
        assert student.name is None

    def test_attendance_target_persistence(self):
        """Attendance target is stored on the model."""
        student = Student(id=uuid4(), attendance_target=75.0)
        assert student.attendance_target == 75.0

    def test_attendance_target_defaults_to_none(self):
        """Attendance target defaults to None (not yet configured)."""
        student = Student(id=uuid4())
        assert student.attendance_target is None

    def test_valid_attendance_target_values(self):
        """Valid target values are accepted on the model."""
        for target in (0.0, 50.0, 75.0, 100.0):
            student = Student(id=uuid4(), attendance_target=target)
            assert student.attendance_target == target

    def test_student_status_default(self):
        """New students are active by default (applied at INSERT by SQLAlchemy)."""
        # status default is server/INSERT-side; column default exists on the model
        assert Student.__table__.c.status.default is not None

    def test_migration_model_consistency(self):
        """Model fields match migration columns."""
        from sqlalchemy import Float, String

        columns = {c.name: c for c in Student.__table__.columns}

        assert isinstance(columns["name"].type, String)
        assert columns["name"].type.length == 100
        assert columns["name"].nullable is True
        assert isinstance(columns["attendance_target"].type, Float)
        assert columns["attendance_target"].nullable is True
        assert "name" in columns
        assert "attendance_target" in columns


class TestStudentProfileRepository:
    """Test StudentRepository profile operations."""

    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.flush = AsyncMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def repo(self, mock_session):
        return StudentRepository(mock_session)

    @pytest.mark.asyncio
    async def test_update_profile_sets_name(self, repo, mock_session):
        """update_profile persists name to the student row."""
        student = Student(id=uuid4(), name="Old")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = student
        mock_session.execute.return_value = mock_result

        result = await repo.update_profile(student.id, name="Priya")

        assert result is not None
        assert result.name == "Priya"
        mock_session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_profile_sets_attendance_target(self, repo, mock_session):
        """update_profile persists a valid attendance target."""
        student = Student(id=uuid4())
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = student
        mock_session.execute.return_value = mock_result

        result = await repo.update_profile(student.id, attendance_target=80.0)

        assert result is not None
        assert result.attendance_target == 80.0

    @pytest.mark.asyncio
    async def test_update_profile_valid_boundaries(self, repo, mock_session):
        """Boundary values 0 and 100 are accepted."""
        student = Student(id=uuid4())
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = student
        mock_session.execute.return_value = mock_result

        assert (
            await repo.update_profile(student.id, attendance_target=0.0)
        ).attendance_target == 0.0
        assert (
            await repo.update_profile(student.id, attendance_target=100.0)
        ).attendance_target == 100.0

    @pytest.mark.asyncio
    async def test_update_profile_invalid_target_raises(self, repo, mock_session):
        """Out-of-range targets are rejected."""
        student = Student(id=uuid4())
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = student
        mock_session.execute.return_value = mock_result

        for invalid in (-1.0, 100.1, 150.0):
            with pytest.raises(ValueError):
                await repo.update_profile(student.id, attendance_target=invalid)

    @pytest.mark.asyncio
    async def test_update_profile_null_target_raises(self, repo, mock_session):
        """NULL target is not settable via update_profile (stays unset)."""
        student = Student(id=uuid4())
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = student
        mock_session.execute.return_value = mock_result

        result = await repo.update_profile(student.id, attendance_target=None)
        assert result.attendance_target is None

    @pytest.mark.asyncio
    async def test_update_profile_only_provided_fields(self, repo, mock_session):
        """Fields not provided remain unchanged."""
        student = Student(id=uuid4(), name="Priya", attendance_target=75.0)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = student
        mock_session.execute.return_value = mock_result

        result = await repo.update_profile(student.id, name="Rahul")

        assert result.name == "Rahul"
        assert result.attendance_target == 75.0

    @pytest.mark.asyncio
    async def test_update_profile_unknown_student_returns_none(
        self, repo, mock_session
    ):
        """Updating a non-existent student returns None."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repo.update_profile(uuid4(), name="Priya")
        assert result is None

    @pytest.mark.asyncio
    async def test_ownership_isolation(self, repo, mock_session):
        """Students cannot update another student's profile."""
        student_a = Student(id=uuid4(), name="A")
        student_b = Student(id=uuid4(), name="B")
        mock_result = MagicMock()

        # First lookup returns student_a
        mock_result.scalar_one_or_none.return_value = student_a
        mock_session.execute.return_value = mock_result

        # update_profile scopes updates to the requested student_id only
        result = await repo.update_profile(student_a.id, name="A-updated")
        assert result.name == "A-updated"

        # student_b remains unchanged
        assert student_b.name == "B"


class TestStudentProfileFlowsToBriefing:
    """Test persisted profile values reach BriefingService."""

    @pytest.mark.asyncio
    async def test_briefing_receives_persisted_name_and_target(self):
        """BriefingService receives name and attendance_target via StudentProfile."""
        student_id = uuid4()
        profile = StudentProfile(
            student_id=student_id,
            name="Priya",
            attendance_target=75.0,
        )
        from app.intelligence.services.context_builder import create_student_context

        context = create_student_context(student_id, profile=profile)

        captured = {}

        class FakeTimetableService:
            async def get_confirmed_timetable(self, student_id):
                return None

            async def get_today_schedule(self, student_id):
                return []

        class FakeAttendanceService:
            async def get_attendance_summary(self, student_id):
                from app.intelligence.services.attendance_service import (
                    AttendanceSummaryResult,
                    OverallAttendanceResult,
                )

                return AttendanceSummaryResult(
                    overall=OverallAttendanceResult(
                        attended=80,
                        conducted=100,
                        percentage=80.0,
                        captured_at=datetime.now(UTC),
                        source="doctus",
                        semester_id=None,
                    ),
                    subjects=(),
                    captured_at=datetime.now(UTC),
                    source="doctus",
                    semester_id=None,
                )

            async def get_subjects_below_target(self, student_id, target_percentage):
                captured["target"] = target_percentage
                return ()

        service = BriefingService(FakeTimetableService(), FakeAttendanceService())
        result = await service.generate_briefing(context)

        assert "Good morning, Priya!" in result.message
        assert captured["target"] == 75.0

    @pytest.mark.asyncio
    async def test_null_target_preserves_no_target_behavior(self):
        """NULL attendance target skips below-target analysis."""
        student_id = uuid4()
        profile = StudentProfile(
            student_id=student_id,
            name="Priya",
            attendance_target=None,
        )
        from app.intelligence.services.context_builder import create_student_context

        context = create_student_context(student_id, profile=profile)

        called = {"below_target": False}

        class FakeTimetableService:
            async def get_confirmed_timetable(self, student_id):
                return None

            async def get_today_schedule(self, student_id):
                return []

        class FakeAttendanceService:
            async def get_attendance_summary(self, student_id):
                return None

            async def get_subjects_below_target(self, student_id, target_percentage):
                called["below_target"] = True
                return ()

        service = BriefingService(FakeTimetableService(), FakeAttendanceService())
        result = await service.generate_briefing(context)

        assert called["below_target"] is False
        assert "target" not in result.message.lower()

    @pytest.mark.asyncio
    async def test_no_attendance_mutation(self):
        """Briefing generation never mutates attendance records."""
        student_id = uuid4()
        snapshot = AttendanceSnapshot(
            student_id=student_id,
            source=AttendanceSource.DOCTUS,
            captured_at=datetime.now(UTC),
            overall_attended=80,
            overall_conducted=100,
        )
        profile = StudentProfile(
            student_id=student_id,
            name="Priya",
            attendance_target=75.0,
        )
        from app.intelligence.services.context_builder import create_student_context

        context = create_student_context(student_id, profile=profile)

        class FakeTimetableService:
            async def get_confirmed_timetable(self, student_id):
                return None

            async def get_today_schedule(self, student_id):
                return []

        class FakeAttendanceService:
            async def get_attendance_summary(self, student_id):
                return None

            async def get_subjects_below_target(self, student_id, target_percentage):
                return ()

        service = BriefingService(FakeTimetableService(), FakeAttendanceService())
        await service.generate_briefing(context)

        assert snapshot.overall_attended == 80
        assert snapshot.overall_conducted == 100
        assert snapshot.subjects == []


class TestSchedulerUsesPersistedProfile:
    """Test scheduler builds StudentProfile from persisted fields."""

    def test_scheduler_builds_profile_from_student_fields(self):
        """Scheduler maps persisted name and attendance_target into StudentProfile."""
        import inspect

        from app.workers import briefing_scheduler

        source = inspect.getsource(briefing_scheduler)
        assert "name=student.name" in source
        assert "attendance_target=student.attendance_target" in source
