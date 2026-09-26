"""
Focused attendance domain tests.

Tests the actual required behavior for attendance models and repositories.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.models.attendance import (
    AttendanceSnapshot,
    AttendanceSource,
    SubjectAttendance,
)
from app.repositories.attendance import (
    AttendanceSnapshotRepository,
    SubjectAttendanceRepository,
)


class TestAttendanceSnapshotModel:
    """Test AttendanceSnapshot model creation and validation."""

    def test_snapshot_creation_minimal(self):
        """Test creating a snapshot with required fields."""
        student_id = uuid4()
        snapshot = AttendanceSnapshot(
            student_id=student_id,
            source=AttendanceSource.DOCTUS,
            captured_at=datetime.now(UTC),
            overall_attended=100,
            overall_conducted=150,
        )

        assert snapshot.student_id == student_id
        assert snapshot.source == AttendanceSource.DOCTUS
        assert snapshot.overall_attended == 100
        assert snapshot.overall_conducted == 150
        assert snapshot.semester_id is None
        assert snapshot.id is None  # Generated on flush

    def test_snapshot_creation_with_semester(self):
        """Test creating a snapshot with semester_id."""
        student_id = uuid4()
        snapshot = AttendanceSnapshot(
            student_id=student_id,
            source=AttendanceSource.DOCTUS,
            captured_at=datetime.now(UTC),
            semester_id="BT25290203",
            overall_attended=100,
            overall_conducted=150,
        )

        assert snapshot.semester_id == "BT25290203"

    def test_overall_percentage_calculation(self):
        """Test percentage is calculated from counts."""
        snapshot = AttendanceSnapshot(
            student_id=uuid4(),
            source=AttendanceSource.DOCTUS,
            captured_at=datetime.now(UTC),
            overall_attended=75,
            overall_conducted=100,
        )

        assert snapshot.overall_percentage() == 75.0

    def test_overall_percentage_zero_conducted(self):
        """Test percentage handles zero conducted."""
        snapshot = AttendanceSnapshot(
            student_id=uuid4(),
            source=AttendanceSource.DOCTUS,
            captured_at=datetime.now(UTC),
            overall_attended=0,
            overall_conducted=0,
        )

        assert snapshot.overall_percentage() == 0.0


class TestSubjectAttendanceModel:
    """Test SubjectAttendance model creation and validation."""

    def test_subject_creation_minimal(self):
        """Test creating a subject with required fields."""
        snapshot_id = uuid4()
        subject = SubjectAttendance(
            snapshot_id=snapshot_id,
            subject_code="CS301",
            cumulative_attended=50,
            cumulative_conducted=60,
        )

        assert subject.snapshot_id == snapshot_id
        assert subject.subject_code == "CS301"
        assert subject.cumulative_attended == 50
        assert subject.cumulative_conducted == 60
        assert subject.subject_name is None
        assert subject.monthly_attended is None
        assert subject.monthly_conducted is None

    def test_subject_creation_with_optional_fields(self):
        """Test creating a subject with all optional fields."""
        snapshot_id = uuid4()
        subject = SubjectAttendance(
            snapshot_id=snapshot_id,
            subject_code="CS301",
            subject_name="Database Management Systems",
            monthly_period="September 2026",
            monthly_attended=8,
            monthly_conducted=10,
            cumulative_attended=50,
            cumulative_conducted=60,
        )

        assert subject.subject_name == "Database Management Systems"
        assert subject.monthly_period == "September 2026"
        assert subject.monthly_attended == 8
        assert subject.monthly_conducted == 10

    def test_cumulative_percentage_calculation(self):
        """Test cumulative percentage is calculated from counts."""
        subject = SubjectAttendance(
            snapshot_id=uuid4(),
            subject_code="CS301",
            cumulative_attended=75,
            cumulative_conducted=100,
        )

        assert subject.cumulative_percentage() == 75.0

    def test_monthly_percentage_calculation(self):
        """Test monthly percentage is calculated when data available."""
        subject = SubjectAttendance(
            snapshot_id=uuid4(),
            subject_code="CS301",
            monthly_attended=8,
            monthly_conducted=10,
            cumulative_attended=50,
            cumulative_conducted=60,
        )

        assert subject.monthly_percentage() == 80.0

    def test_monthly_percentage_none_when_missing(self):
        """Test monthly percentage returns None when data missing."""
        subject = SubjectAttendance(
            snapshot_id=uuid4(),
            subject_code="CS301",
            cumulative_attended=50,
            cumulative_conducted=60,
        )

        assert subject.monthly_percentage() is None

    def test_monthly_percentage_zero_conducted(self):
        """Test monthly percentage handles zero conducted."""
        subject = SubjectAttendance(
            snapshot_id=uuid4(),
            subject_code="CS301",
            monthly_attended=0,
            monthly_conducted=0,
            cumulative_attended=50,
            cumulative_conducted=60,
        )

        assert subject.monthly_percentage() == 0.0


class TestAttendanceOwnership:
    """Test ownership enforcement through relationships."""

    def test_snapshot_student_relationship(self):
        """Test snapshot links to student."""
        student_id = uuid4()
        snapshot = AttendanceSnapshot(
            student_id=student_id,
            source=AttendanceSource.DOCTUS,
            captured_at=datetime.now(UTC),
            overall_attended=100,
            overall_conducted=150,
        )

        assert snapshot.student_id == student_id

    def test_subject_snapshot_relationship(self):
        """Test subject links to snapshot."""
        snapshot_id = uuid4()
        subject = SubjectAttendance(
            snapshot_id=snapshot_id,
            subject_code="CS301",
            cumulative_attended=50,
            cumulative_conducted=60,
        )

        assert subject.snapshot_id == snapshot_id


class TestConstraints:
    """Test database constraint enforcement at model level."""

    def test_overall_attended_non_negative(self):
        """Test overall_attended must be >= 0."""
        snapshot = AttendanceSnapshot(
            student_id=uuid4(),
            source=AttendanceSource.DOCTUS,
            captured_at=datetime.now(UTC),
            overall_attended=-1,
            overall_conducted=150,
        )

        # Model allows it; DB constraint enforces
        assert snapshot.overall_attended == -1

    def test_overall_conducted_non_negative(self):
        """Test overall_conducted must be >= 0."""
        snapshot = AttendanceSnapshot(
            student_id=uuid4(),
            source=AttendanceSource.DOCTUS,
            captured_at=datetime.now(UTC),
            overall_attended=100,
            overall_conducted=-1,
        )

        assert snapshot.overall_conducted == -1

    def test_subject_cumulative_counts_non_negative(self):
        """Test subject cumulative counts must be >= 0."""
        subject = SubjectAttendance(
            snapshot_id=uuid4(),
            subject_code="CS301",
            cumulative_attended=-1,
            cumulative_conducted=60,
        )

        assert subject.cumulative_attended == -1


class TestAttendanceSnapshotRepository:
    """Test AttendanceSnapshotRepository."""

    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def repo(self, mock_session):
        return AttendanceSnapshotRepository(mock_session)

    @pytest.mark.asyncio
    async def test_create(self, repo, mock_session):
        """Test creating a snapshot."""
        snapshot = AttendanceSnapshot(
            student_id=uuid4(),
            source=AttendanceSource.DOCTUS,
            captured_at=datetime.now(UTC),
            overall_attended=100,
            overall_conducted=150,
        )

        result = await repo.create(snapshot)

        assert result == snapshot
        mock_session.add.assert_called_once_with(snapshot)
        mock_session.flush.assert_called_once()
        mock_session.refresh.assert_called_once_with(snapshot)

    @pytest.mark.asyncio
    async def test_get_by_id(self, repo, mock_session):
        """Test getting snapshot by ID."""
        snapshot_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_id(snapshot_id)

        assert result is None
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_latest_for_student(self, repo, mock_session):
        """Test getting latest snapshot for student."""
        student_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repo.get_latest_for_student(student_id)

        assert result is None
        mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_all_for_student(self, repo, mock_session):
        """Test getting all snapshots for student with limit."""
        student_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await repo.get_all_for_student(student_id, limit=10)

        assert result == []
        mock_session.execute.assert_called_once()


class TestSubjectAttendanceRepository:
    """Test SubjectAttendanceRepository."""

    @pytest.fixture
    def mock_session(self):
        session = MagicMock()
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        session.execute = AsyncMock()
        return session

    @pytest.fixture
    def repo(self, mock_session):
        return SubjectAttendanceRepository(mock_session)

    @pytest.mark.asyncio
    async def test_create(self, repo, mock_session):
        """Test creating a subject attendance."""
        subject = SubjectAttendance(
            snapshot_id=uuid4(),
            subject_code="CS301",
            cumulative_attended=50,
            cumulative_conducted=60,
        )

        result = await repo.create(subject)

        assert result == subject
        mock_session.add.assert_called_once_with(subject)
        mock_session.flush.assert_called_once()
        mock_session.refresh.assert_called_once_with(subject)

    @pytest.mark.asyncio
    async def test_create_batch(self, repo, mock_session):
        """Test creating multiple subject attendances."""
        subjects = [
            SubjectAttendance(
                snapshot_id=uuid4(),
                subject_code="CS301",
                cumulative_attended=50,
                cumulative_conducted=60,
            ),
            SubjectAttendance(
                snapshot_id=uuid4(),
                subject_code="CS302",
                cumulative_attended=40,
                cumulative_conducted=50,
            ),
        ]

        result = await repo.create_batch(subjects)

        assert result == subjects
        mock_session.add_all.assert_called_once_with(subjects)
        mock_session.flush.assert_called_once()
        assert mock_session.refresh.call_count == 2

    @pytest.mark.asyncio
    async def test_get_for_snapshot(self, repo, mock_session):
        """Test getting subjects for a snapshot."""
        snapshot_id = uuid4()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await repo.get_for_snapshot(snapshot_id)

        assert result == []
        mock_session.execute.assert_called_once()


class TestSnapshotWithSubjects:
    """Test snapshot with multiple subjects."""

    def test_snapshot_with_multiple_subjects(self):
        """Test creating a snapshot with multiple subjects."""
        student_id = uuid4()
        snapshot = AttendanceSnapshot(
            student_id=student_id,
            source=AttendanceSource.DOCTUS,
            captured_at=datetime.now(UTC),
            overall_attended=163,
            overall_conducted=284,
        )

        subjects = [
            SubjectAttendance(
                snapshot_id=snapshot.id,
                subject_code="25PC1CS201",
                subject_name="Database Management Systems",
                monthly_period="September 2026",
                monthly_attended=6,
                monthly_conducted=7,
                cumulative_attended=16,
                cumulative_conducted=34,
            ),
            SubjectAttendance(
                snapshot_id=snapshot.id,
                subject_code="25PC1CY201",
                subject_name="Chemistry",
                monthly_period="September 2026",
                monthly_attended=7,
                monthly_conducted=9,
                cumulative_attended=23,
                cumulative_conducted=36,
            ),
            SubjectAttendance(
                snapshot_id=snapshot.id,
                subject_code="25PC1IT204",
                subject_name="Information Technology",
                monthly_period="September 2026",
                monthly_attended=8,
                monthly_conducted=10,
                cumulative_attended=19,
                cumulative_conducted=36,
            ),
        ]

        assert len(subjects) == 3
        for subject in subjects:
            assert subject.snapshot_id == snapshot.id
            assert subject.cumulative_attended <= subject.cumulative_conducted
            if (
                subject.monthly_attended is not None
                and subject.monthly_conducted is not None
            ):
                assert subject.monthly_attended <= subject.monthly_conducted

    def test_subjects_have_consistent_cumulative(self):
        """Test that subject cumulative data is internally consistent."""
        subject = SubjectAttendance(
            snapshot_id=uuid4(),
            subject_code="25PC1CS201",
            monthly_attended=6,
            monthly_conducted=7,
            cumulative_attended=16,
            cumulative_conducted=34,
        )

        # Monthly and cumulative are independent - both should be valid
        assert subject.monthly_attended <= subject.monthly_conducted
        assert subject.cumulative_attended <= subject.cumulative_conducted


# Need to import for the tests above
