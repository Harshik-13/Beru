"""
Comprehensive Test Suite for Attendance Intelligence and Action Integrity Invariant.

Verifies:
1. Attendance target mutation (validation, idempotency, DB re-read verification, audit logging).
2. Safe bunk calculation exact math, zero-data boundaries, and below-target handling.
3. 100% target recovery boundary conditions (unachievable vs 0 needed) and overall recovery.
4. Day absence simulation (confirmed timetable enforcement, lab batch filtering, period aggregation, 3-tier safety).
5. Attendance extremes with multi-subject tie handling.
6. Action Integrity Invariant: prevents hallucinated mutations when no authorized mutation tool executes.
"""

from datetime import UTC, date, datetime, time
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.intelligence.models.context import StudentContext, StudentProfile
from app.intelligence.services.attendance_service import (
    AttendanceService,
    calculate_recovery,
)
from app.intelligence.services.conversation import (
    GRACEFUL_CAPABILITY_REFUSAL,
    ConversationService,
    is_state_mutation_intent,
)
from app.intelligence.services.timetable_service import TimetableService
from app.models.attendance import (
    AttendanceSnapshot,
    AttendanceSource,
    SubjectAttendance,
)
from app.models.student import Student
from app.models.timetable import (
    ActivityType,
    LabBatch,
    Timetable,
    TimetableEntry,
    TimetableStatus,
)


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def student_id():
    return uuid4()


@pytest.fixture
def sample_student(student_id):
    return Student(
        id=student_id,
        name="Harsh V",
        attendance_target=75.0,
        lab_batch=LabBatch.BATCH_1,
    )


@pytest.fixture
def sample_snapshot(student_id):
    snapshot = AttendanceSnapshot(
        id=uuid4(),
        student_id=student_id,
        source=AttendanceSource.DOCTUS,
        captured_at=datetime.now(UTC),
        overall_attended=60,
        overall_conducted=80,  # 75.0%
    )
    s1 = SubjectAttendance(
        id=uuid4(),
        snapshot_id=snapshot.id,
        subject_code="CS301",
        subject_name="Data Structures",
        cumulative_attended=40,
        cumulative_conducted=48,  # 83.33%
    )
    s2 = SubjectAttendance(
        id=uuid4(),
        snapshot_id=snapshot.id,
        subject_code="CS302",
        subject_name="Operating Systems",
        cumulative_attended=12,
        cumulative_conducted=20,  # 60.0% (below target)
    )
    s3 = SubjectAttendance(
        id=uuid4(),
        snapshot_id=snapshot.id,
        subject_code="CS303",
        subject_name="Algorithms",
        cumulative_attended=8,
        cumulative_conducted=12,  # 66.67%
    )
    snapshot.subjects = [s1, s2, s3]
    return snapshot


@pytest.fixture
def attendance_service(mock_session, sample_snapshot):
    service = AttendanceService(mock_session)
    service.student_repo = AsyncMock()
    service.snapshot_repo = AsyncMock()
    service.audit_service = AsyncMock()
    service.get_latest_snapshot = AsyncMock(return_value=sample_snapshot)
    return service


@pytest.fixture
def timetable_service(mock_session):
    service = TimetableService(mock_session)
    service.student_repo = AsyncMock()
    service.timetable_repo = AsyncMock()
    service.entry_repo = AsyncMock()
    return service


# ==============================================================================
# 1. Target Mutation Tests
# ==============================================================================
class TestTargetMutation:
    """Tests for attendance target mutation in domain and tool layers."""

    @pytest.mark.asyncio
    async def test_set_attendance_target_success(
        self, attendance_service, sample_student, mock_session
    ):
        attendance_service.student_repo.get_by_id.side_effect = [
            sample_student,  # Initial read
            Student(  # Re-read verification after commit
                id=sample_student.id,
                name=sample_student.name,
                attendance_target=85.0,
            ),
        ]

        result = await attendance_service.set_attendance_target(
            student_id=sample_student.id,
            target_percentage=85.0,
        )

        assert result["success"] is True
        assert result["target"]["percentage"] == 85.0
        assert result["mutation"]["new_target"] == 85.0
        assert result["mutation"]["old_target"] == 75.0
        assert result["mutation"]["idempotent"] is False

        mock_session.commit.assert_awaited()
        attendance_service.audit_service.log_student_updated.assert_awaited_once()
        call_kwargs = attendance_service.audit_service.log_student_updated.call_args[1]
        assert call_kwargs["student_id"] == sample_student.id
        assert call_kwargs["event_metadata"]["old_target"] == 75.0
        assert call_kwargs["event_metadata"]["new_target"] == 85.0

    @pytest.mark.asyncio
    async def test_set_attendance_target_idempotent(
        self, attendance_service, sample_student, mock_session
    ):
        attendance_service.student_repo.get_by_id.return_value = sample_student

        result = await attendance_service.set_attendance_target(
            student_id=sample_student.id,
            target_percentage=75.0,  # Already 75.0
        )

        assert result["success"] is True
        assert result["target"]["percentage"] == 75.0
        assert result["mutation"]["idempotent"] is True
        mock_session.commit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_set_attendance_target_validation_bounds(
        self, attendance_service, sample_student
    ):
        with pytest.raises(ValueError, match="Target percentage must be between 1.0 and 100.0"):
            await attendance_service.set_attendance_target(
                student_id=sample_student.id,
                target_percentage=0.5,
            )

        with pytest.raises(ValueError, match="Target percentage must be between 1.0 and 100.0"):
            await attendance_service.set_attendance_target(
                student_id=sample_student.id,
                target_percentage=100.5,
            )


# ==============================================================================
# 2. Bunk Allowance Exact Math & Boundary Tests
# ==============================================================================
class TestBunkAllowanceMath:
    """Tests for safe bunk calculations."""

    @pytest.mark.asyncio
    async def test_bunk_allowance_exact_calculation(
        self, attendance_service, sample_student, sample_snapshot
    ):
        """
        CS301: Attended = 40, Conducted = 48, Target = 75%
        B_max = floor((40 - 0.75 * 48) / 0.75) = floor((40 - 36) / 0.75) = floor(5.333) = 5
        Attendance after 5 bunks: 40 / 53 = 75.47% >= 75% (SAFE)
        Attendance after 6 bunks: 40 / 54 = 74.07% < 75% (UNSAFE)
        """
        attendance_service.student_repo.get_by_id.return_value = sample_student
        attendance_service.get_latest_snapshot.return_value = sample_snapshot

        result = await attendance_service.calculate_bunk_allowance(
            student_id=sample_student.id,
            subject_code="CS301",
        )

        assert result["safe_bunks"] == 5
        assert result["current_percentage"] == pytest.approx(83.33, abs=0.01)
        assert result["projected_percentage_after_bunk"] == pytest.approx(75.47, abs=0.01)
        assert result["status"] == "safe_to_bunk"

    @pytest.mark.asyncio
    async def test_bunk_allowance_below_target(
        self, attendance_service, sample_student, sample_snapshot
    ):
        """CS302: Attended = 12, Conducted = 20 (60% < 75%) -> 0 safe bunks."""
        attendance_service.student_repo.get_by_id.return_value = sample_student
        attendance_service.get_latest_snapshot.return_value = sample_snapshot

        result = await attendance_service.calculate_bunk_allowance(
            student_id=sample_student.id,
            subject_code="CS302",
        )

        assert result["safe_bunks"] == 0
        assert result["status"] == "below_target"

    @pytest.mark.asyncio
    async def test_bunk_allowance_zero_conducted(
        self, attendance_service, sample_student, student_id
    ):
        """Zero classes conducted -> 0 safe bunks, no division by zero."""
        empty_snapshot = AttendanceSnapshot(
            id=uuid4(),
            student_id=student_id,
            source=AttendanceSource.DOCTUS,
            captured_at=datetime.now(UTC),
            overall_attended=0,
            overall_conducted=0,
        )
        empty_snapshot.subjects = []
        attendance_service.student_repo.get_by_id.return_value = sample_student
        attendance_service.get_latest_snapshot.return_value = empty_snapshot

        result = await attendance_service.calculate_bunk_allowance(
            student_id=sample_student.id,
        )

        assert result["safe_bunks"] == 0
        assert result["status"] == "no_classes_conducted"


# ==============================================================================
# 3. Recovery Calculations & 100% Boundary Tests
# ==============================================================================
class TestRecoveryCalculations:
    """Tests for classes needed to reach target, including 100% edge cases."""

    def test_calculate_recovery_100_percent_unachievable(self):
        """When attended < conducted (e.g. 18/20), 100% target is mathematically impossible."""
        result = calculate_recovery(
            current_attended=18,
            current_conducted=20,
            target_percentage=100.0,
        )
        assert result.achievable is False
        assert result.classes_needed is None
        assert "cannot be achieved mathematically" in result.message.lower()

    def test_calculate_recovery_100_percent_achievable_at_100(self):
        """When attended == conducted (e.g. 20/20), 100% target requires 0 classes."""
        result = calculate_recovery(
            current_attended=20,
            current_conducted=20,
            target_percentage=100.0,
        )
        assert result.achievable is True
        assert result.classes_needed == 0

    @pytest.mark.asyncio
    async def test_calculate_classes_needed_overall(
        self, attendance_service, sample_student, sample_snapshot
    ):
        """
        Overall: Attended = 60, Conducted = 80, Current = 75.0%
        If target is 80%:
        Target = 80% -> ceil((0.8 * 80 - 60) / (1 - 0.8)) = ceil((64 - 60) / 0.2) = ceil(4 / 0.2) = 20.
        """
        sample_student.attendance_target = 80.0
        attendance_service.student_repo.get_by_id.return_value = sample_student
        attendance_service.get_latest_snapshot.return_value = sample_snapshot

        result = await attendance_service.calculate_classes_needed(
            student_id=str(sample_student.id),
            subject_code=None,  # Overall
            target_percentage=80.0,
        )

        assert result.classes_needed == 20
        assert result.achievable is True


# ==============================================================================
# 4. Day Absence Simulation Tests
# ==============================================================================
class TestDayAbsenceSimulation:
    """Tests for full-day leave simulations."""

    @pytest.mark.asyncio
    async def test_simulate_day_absence_requires_confirmed_timetable(
        self, attendance_service, timetable_service, sample_student, sample_snapshot
    ):
        attendance_service.student_repo.get_by_id.return_value = sample_student
        attendance_service.get_latest_snapshot.return_value = sample_snapshot

        # Timetable not confirmed
        timetable_service.get_confirmed_timetable = AsyncMock(return_value=None)
        timetable_service.get_pending_timetable = AsyncMock(return_value=None)

        result = await attendance_service.simulate_day_absence(
            student_id=sample_student.id,
            day="monday",
            timetable_service=timetable_service,
        )

        assert result["available"] is False
        assert result["error_code"] == "NO_TIMETABLE"

    @pytest.mark.asyncio
    async def test_simulate_day_absence_aggregates_periods_and_filters_batches(
        self, attendance_service, timetable_service, sample_student, sample_snapshot
    ):
        monday = date(2026, 10, 5)  # Monday (day_of_week=0)
        timetable = Timetable(
            id=uuid4(),
            student_id=sample_student.id,
            status=TimetableStatus.CONFIRMED,
        )
        timetable_service.get_confirmed_timetable = AsyncMock(return_value=timetable)

        # Student is LabBatch.BATCH_1
        entries = [
            # Two lecture periods of CS301 (should aggregate to 2 periods)
            TimetableEntry(
                timetable_id=timetable.id,
                day_of_week=0,
                start_time=time(9, 0),
                end_time=time(10, 0),
                course_code="CS301",
                activity_name="CS301 Lecture 1",
                activity_type=ActivityType.ACADEMIC,
            ),
            TimetableEntry(
                timetable_id=timetable.id,
                day_of_week=0,
                start_time=time(10, 0),
                end_time=time(11, 0),
                course_code="CS301",
                activity_name="CS301 Lecture 2",
                activity_type=ActivityType.ACADEMIC,
            ),
            # Lab batch entry for B1 (included)
            TimetableEntry(
                timetable_id=timetable.id,
                day_of_week=0,
                start_time=time(11, 0),
                end_time=time(12, 0),
                course_code="CS302",
                activity_name="CS302 Lab B1",
                activity_type=ActivityType.ACADEMIC,
                lab_batch=LabBatch.BATCH_1,
            ),
            # Lab batch entry for B2 (excluded for B1 student)
            TimetableEntry(
                timetable_id=timetable.id,
                day_of_week=0,
                start_time=time(11, 0),
                end_time=time(12, 0),
                course_code="CS303",
                activity_name="CS303 Lab B2",
                activity_type=ActivityType.ACADEMIC,
                lab_batch=LabBatch.BATCH_2,
            ),
        ]
        timetable_service.entry_repo.get_for_timetable.return_value = entries
        attendance_service.student_repo.get_by_id.return_value = sample_student
        attendance_service.get_latest_snapshot.return_value = sample_snapshot

        result = await attendance_service.simulate_day_absence(
            student_id=sample_student.id,
            day=monday,
            timetable_service=timetable_service,
        )

        assert result["scheduled_classes_count"] == 3  # 2 of CS301 + 1 of CS302 B1
        sub_by_code = {s["subject_code"]: s for s in result["affected_subjects"]}
        assert "CS301" in sub_by_code
        assert sub_by_code["CS301"]["scheduled_periods"] == 2
        assert "CS302" in sub_by_code
        assert sub_by_code["CS302"]["scheduled_periods"] == 1
        assert "CS303" not in sub_by_code

        # Check safety hierarchy
        assert "overall_safe" in result
        assert "subjects_safe" in result
        assert "is_safe" in result


# ==============================================================================
# 5. Attendance Extremes Tests
# ==============================================================================
class TestAttendanceExtremes:
    """Tests for identifying highest and lowest attendance courses."""

    @pytest.mark.asyncio
    async def test_get_attendance_extremes_with_ties(
        self, attendance_service, sample_student, student_id
    ):
        snapshot = AttendanceSnapshot(
            id=uuid4(),
            student_id=student_id,
            source=AttendanceSource.DOCTUS,
            captured_at=datetime.now(UTC),
            overall_attended=80,
            overall_conducted=100,
        )
        # S1 and S2 tie for highest at 90%
        # S3 and S4 tie for lowest at 60%
        s1 = SubjectAttendance(
            snapshot_id=snapshot.id,
            subject_code="CS301",
            cumulative_attended=9,
            cumulative_conducted=10,
        )
        s2 = SubjectAttendance(
            snapshot_id=snapshot.id,
            subject_code="CS302",
            cumulative_attended=18,
            cumulative_conducted=20,
        )
        s3 = SubjectAttendance(
            snapshot_id=snapshot.id,
            subject_code="CS303",
            cumulative_attended=6,
            cumulative_conducted=10,
        )
        s4 = SubjectAttendance(
            snapshot_id=snapshot.id,
            subject_code="CS304",
            cumulative_attended=12,
            cumulative_conducted=20,
        )
        snapshot.subjects = [s1, s2, s3, s4]

        attendance_service.get_latest_snapshot.return_value = snapshot
        attendance_service.student_repo.get_by_id.return_value = sample_student

        result = await attendance_service.get_attendance_extremes(student_id=student_id)

        assert result["available"] is True
        assert len(result["highest"]) == 2
        assert result["highest"][0]["percentage"] == 90.0
        highest_codes = {s["subject_code"] for s in result["highest"]}
        assert highest_codes == {"CS301", "CS302"}

        assert len(result["lowest"]) == 2
        assert result["lowest"][0]["percentage"] == 60.0
        lowest_codes = {s["subject_code"] for s in result["lowest"]}
        assert lowest_codes == {"CS303", "CS304"}


# ==============================================================================
# 6. Action Integrity Invariant Tests
# ==============================================================================
class TestActionIntegrityInvariant:
    """
    Tests the Action Integrity Invariant:
    Beru may only claim a state-changing action was completed when an authorized backend
    mutation tool executed successfully. Text alone is never evidence of an action.
    """

    def test_is_state_mutation_intent_detection(self):
        # Explicit mutation requests
        assert is_state_mutation_intent("Set my attendance target to 85%") is True
        assert is_state_mutation_intent("Update my roll number to 12345") is True
        assert is_state_mutation_intent("Change my email to student@example.com") is True
        assert is_state_mutation_intent("80% is my new target") is True

        # Query / informational requests should NOT be flagged as mutation
        assert is_state_mutation_intent("What is my current attendance?") is False
        assert is_state_mutation_intent("Can I bunk any classes today?") is False
        assert is_state_mutation_intent("Show me my schedule for tomorrow") is False
        assert is_state_mutation_intent("Tell me my lowest attendance subject") is False

    @pytest.mark.asyncio
    async def test_unsupported_mutation_refusal(
        self, attendance_service, timetable_service, sample_student
    ):
        """
        When the user requests an unsupported state change (e.g. roll number or email),
        where no tool exists to mutate that state, Beru must return the graceful capability refusal
        and NOT hallucinate that the change was made.
        """
        conv_service = ConversationService(
            timetable_service=timetable_service,
            attendance_service=attendance_service,
        )

        student_context = StudentContext(
            student_id=sample_student.id,
            profile=StudentProfile(
                student_id=sample_student.id,
                name="Harsh",
                attendance_target=75.0,
            ),
        )

        # Message requesting unsupported mutation
        response, ctx = await conv_service.process_message(
            student_context,
            "Change my college roll number to 99999",
        )

        assert "do not currently have the capability to perform that action directly" in response
        assert "99999" not in response

    @pytest.mark.asyncio
    async def test_supported_mutation_tool_execution(
        self, attendance_service, timetable_service, sample_student, sample_snapshot
    ):
        """
        When the user requests a supported state change (target update to 85%),
        the mutation tool executes, commits, and returns verified confirmation.
        """
        attendance_service.student_repo.get_by_id.side_effect = [
            sample_student,
            Student(
                id=sample_student.id,
                name="Harsh",
                attendance_target=85.0,
            ),
        ]
        attendance_service.get_latest_snapshot.return_value = sample_snapshot

        conv_service = ConversationService(
            timetable_service=timetable_service,
            attendance_service=attendance_service,
        )

        student_context = StudentContext(
            student_id=sample_student.id,
            profile=StudentProfile(
                student_id=sample_student.id,
                name="Harsh",
                attendance_target=75.0,
            ),
        )

        response, ctx = await conv_service.process_message(
            student_context,
            "Set my target to 85%",
        )

        assert "85.0%" in response
        assert "updated" in response.lower()
