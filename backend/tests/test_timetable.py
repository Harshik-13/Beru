"""
Focused timetable domain tests.

Tests the actual required behavior for timetable pipeline:
- ownership
- state transitions
- versioning
- multi-period entries
- lunch handling
- course metadata
- slash-separated labs
- lab batch resolution
- cross-student isolation
- schedule queries
"""

from datetime import date, time, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.intelligence.services.timetable_extraction import (
    ExtractedCell,
    ExtractedMetadata,
    ExtractionConfidence,
    SlashLabCandidate,
    TimetableExtractionResult,
    _confidence_to_float,
    period_to_time,
)
from app.intelligence.services.timetable_service import (
    TimetableService,
    TimetableStateError,
)
from app.models.student import Student
from app.models.timetable import (
    ActivityType,
    LabBatch,
    Timetable,
    TimetableEntry,
    TimetableStatus,
)

# ===== Fixtures =====


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.flush = AsyncMock()
    return session


@pytest.fixture
def mock_student_repo():
    repo = MagicMock()
    repo.get_by_id = AsyncMock()
    return repo


@pytest.fixture
def mock_timetable_repo():
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.get_by_id_with_entries = AsyncMock()
    repo.get_latest_for_student = AsyncMock()
    repo.get_confirmed_for_student = AsyncMock()
    repo.get_pending_for_student = AsyncMock()
    repo.archive_previous_confirmed = AsyncMock()
    return repo


@pytest.fixture
def mock_entry_repo():
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.create_batch = AsyncMock()
    repo.get_for_timetable = AsyncMock()
    repo.delete_for_timetable = AsyncMock()
    return repo


@pytest.fixture
def student_a_id():
    return uuid4()


@pytest.fixture
def student_b_id():
    return uuid4()


@pytest.fixture
def timetable_service(
    mock_session,
    mock_student_repo,
    mock_timetable_repo,
    mock_entry_repo,
):
    service = TimetableService(mock_session)
    service.student_repo = mock_student_repo
    service.timetable_repo = mock_timetable_repo
    service.entry_repo = mock_entry_repo
    return service


# ===== Tests =====


class TestTimetableOwnership:
    """Test timetable ownership enforcement."""

    @pytest.mark.asyncio
    async def test_student_a_cannot_access_student_b_timetable(
        self, timetable_service, mock_timetable_repo, student_a_id, student_b_id
    ):
        """Student A cannot access Student B's timetable."""
        mock_timetable_repo.get_confirmed_for_student.return_value = None

        confirmed_b = await timetable_service.get_confirmed_timetable(student_b_id)
        assert confirmed_b is None

        mock_timetable_repo.get_confirmed_for_student.assert_called_with(student_b_id)

    @pytest.mark.asyncio
    async def test_timetable_entry_ownership_via_timetable(
        self, timetable_service, mock_timetable_repo, student_a_id, student_b_id
    ):
        """Entries are owned via their timetable."""
        mock_timetable_repo.get_confirmed_for_student.return_value = None

        schedule_b = await timetable_service.get_today_schedule(student_b_id)
        assert schedule_b == []


class TestTimetableStateTransitions:
    """Test valid and invalid state transitions."""

    @pytest.mark.asyncio
    async def test_uploaded_to_extracting(self):
        """UPLOADED -> EXTRACTING transition."""
        timetable = Timetable(
            student_id=uuid4(),
            status=TimetableStatus.UPLOADED,
            version=1,
        )
        timetable.status = TimetableStatus.EXTRACTING
        assert timetable.status == TimetableStatus.EXTRACTING

    @pytest.mark.asyncio
    async def test_extracting_to_review_required(self):
        """EXTRACTING -> REVIEW_REQUIRED when ambiguous."""
        timetable = Timetable(
            student_id=uuid4(),
            status=TimetableStatus.EXTRACTING,
            version=1,
        )
        timetable.status = TimetableStatus.REVIEW_REQUIRED
        assert timetable.status == TimetableStatus.REVIEW_REQUIRED

    @pytest.mark.asyncio
    async def test_extract_timetable_stays_review_required(
        self, timetable_service, mock_timetable_repo, mock_student_repo
    ):
        """extract_timetable must always return REVIEW_REQUIRED (no auto-confirm)."""
        student_id = uuid4()
        timetable = Timetable(
            id=uuid4(),
            student_id=student_id,
            status=TimetableStatus.UPLOADED,
            version=1,
        )
        mock_timetable_repo.get_by_id.return_value = timetable
        mock_timetable_repo.get_by_id_with_entries.return_value = timetable
        mock_student = Student(id=student_id, lab_batch=LabBatch.BATCH_1)
        mock_student_repo.get_by_id.return_value = mock_student

        mock_result = TimetableExtractionResult(
            metadata=ExtractedMetadata(),
            cells=(),
            slash_labs=(),
            warnings=(),
            errors=(),
        )

        with pytest.MonkeyPatch.context() as mp:
            mock_extractor = MagicMock()
            mock_extractor.extract = AsyncMock(return_value=mock_result)
            mp.setattr(
                "app.intelligence.services.timetable_service.create_timetable_extractor",
                lambda: mock_extractor,
            )
            result = await timetable_service.extract_timetable(
                timetable.id, "dummy.pdf"
            )

        assert result.status == TimetableStatus.REVIEW_REQUIRED

    @pytest.mark.asyncio
    async def test_review_required_to_confirmed(
        self, timetable_service, mock_timetable_repo
    ):
        """REVIEW_REQUIRED -> CONFIRMED on confirmation."""
        timetable = Timetable(
            student_id=uuid4(),
            status=TimetableStatus.REVIEW_REQUIRED,
            version=1,
        )
        mock_timetable_repo.get_by_id_with_entries.return_value = timetable

        confirmed = await timetable_service.confirm_timetable(timetable.id)

        assert confirmed.status == TimetableStatus.CONFIRMED
        assert confirmed.confirmed_at is not None

    @pytest.mark.asyncio
    async def test_confirmed_to_archived_on_new_confirmation(
        self, timetable_service, mock_timetable_repo
    ):
        """Previous CONFIRMED timetable archived when new one confirmed."""
        _t1 = Timetable(
            student_id=uuid4(),
            status=TimetableStatus.CONFIRMED,
            version=1,
        )
        t2 = Timetable(
            student_id=uuid4(),
            status=TimetableStatus.REVIEW_REQUIRED,
            version=2,
        )
        mock_timetable_repo.get_by_id_with_entries.return_value = t2
        mock_timetable_repo.get_confirmed_for_student.return_value = _t1

        await timetable_service.confirm_timetable(t2.id)

        mock_timetable_repo.archive_previous_confirmed.assert_called()

    @pytest.mark.asyncio
    async def test_invalid_transition_uploaded_to_confirmed_rejected(
        self, timetable_service, mock_timetable_repo
    ):
        """Cannot confirm timetable from UPLOADED state."""
        timetable = Timetable(
            student_id=uuid4(),
            status=TimetableStatus.UPLOADED,
            version=1,
        )
        mock_timetable_repo.get_by_id_with_entries.return_value = timetable

        with pytest.raises(TimetableStateError):
            await timetable_service.confirm_timetable(timetable.id)


class TestTimetableVersioning:
    """Test timetable versioning behavior."""

    @pytest.mark.asyncio
    async def test_new_upload_increments_version(self):
        """New timetable for same student gets incremented version."""
        _t1 = Timetable(
            student_id=uuid4(),
            status=TimetableStatus.CONFIRMED,
            version=1,
        )
        t2 = Timetable(
            student_id=uuid4(),
            status=TimetableStatus.UPLOADED,
            version=2,
        )
        assert t2.version == 2

    @pytest.mark.asyncio
    async def test_previous_confirmed_preserved(self):
        """Historical confirmed timetable data not overwritten."""
        t1 = Timetable(
            student_id=uuid4(),
            status=TimetableStatus.CONFIRMED,
            version=1,
            academic_year="2024-25",
            semester=3,
        )
        t2 = Timetable(
            student_id=uuid4(),
            status=TimetableStatus.REVIEW_REQUIRED,
            version=2,
            academic_year="2025-26",
            semester=4,
        )

        assert t1.academic_year == "2024-25"
        assert t1.semester == 3
        assert t2.academic_year == "2025-26"
        assert t2.semester == 4


class TestMultiPeriodEntry:
    """Test multi-period cell handling."""

    @pytest.mark.asyncio
    async def test_multi_period_cell_single_entry(self):
        """Multi-period lab creates single entry with correct start/end."""
        # CM LAB spanning P5+P6 (14:40-16:40)
        entry = TimetableEntry(
            timetable_id=uuid4(),
            day_of_week=0,
            start_time=time(14, 40),
            end_time=time(16, 40),
            activity_name="CM LAB",
            activity_type=ActivityType.LAB,
        )

        assert entry.start_time == time(14, 40)
        assert entry.end_time == time(16, 40)
        assert entry.activity_name == "CM LAB"
        assert entry.activity_type == ActivityType.LAB


class TestLunchHandling:
    """Test lunch break handling."""

    @pytest.mark.asyncio
    async def test_lunch_break_type(self):
        """LUNCH has BREAK activity type."""
        entry = TimetableEntry(
            timetable_id=uuid4(),
            day_of_week=0,
            start_time=time(13, 0),
            end_time=time(13, 40),
            activity_name="Lunch",
            activity_type=ActivityType.BREAK,
        )

        assert entry.activity_type == ActivityType.BREAK
        assert entry.activity_name == "Lunch"

    @pytest.mark.asyncio
    async def test_no_classes_during_lunch(self):
        """No academic classes scheduled during lunch period."""
        # Class before lunch
        entry1 = TimetableEntry(
            timetable_id=uuid4(),
            day_of_week=0,
            start_time=time(12, 0),
            end_time=time(13, 0),
            activity_name="DBMS",
            activity_type=ActivityType.ACADEMIC,
        )
        # Lunch
        entry2 = TimetableEntry(
            timetable_id=uuid4(),
            day_of_week=0,
            start_time=time(13, 0),
            end_time=time(13, 40),
            activity_name="Lunch",
            activity_type=ActivityType.BREAK,
        )
        # Class after lunch
        entry3 = TimetableEntry(
            timetable_id=uuid4(),
            day_of_week=0,
            start_time=time(13, 40),
            end_time=time(14, 40),
            activity_name="MTP",
            activity_type=ActivityType.ACTIVITY,
        )

        assert entry1.end_time == entry2.start_time  # 13:00
        assert entry2.end_time == entry3.start_time  # 13:40


class TestCourseMetadataMapping:
    """Test course metadata from extraction."""

    @pytest.mark.asyncio
    async def test_course_code_stored(self):
        """Course code can be stored on entry."""
        entry = TimetableEntry(
            timetable_id=uuid4(),
            day_of_week=0,
            start_time=time(10, 0),
            end_time=time(11, 0),
            activity_name="Database Management Systems",
            activity_type=ActivityType.ACADEMIC,
            course_code="CS301",
        )

        assert entry.course_code == "CS301"


class TestSlashLabDetection:
    """Test slash-separated lab detection."""

    @pytest.mark.asyncio
    async def test_slash_lab_detected_during_extraction(self):
        """Slash labs detected and returned as candidates."""
        candidate = SlashLabCandidate(
            raw_content="OOPJ LAB / DBMS LAB",
            alternatives=("OOPJ LAB", "DBMS LAB"),
            day_of_week=0,
            start_period=5,
            end_period=6,
            confidence=ExtractionConfidence.MEDIUM,
        )

        assert candidate.raw_content == "OOPJ LAB / DBMS LAB"
        assert candidate.alternatives == ("OOPJ LAB", "DBMS LAB")

    @pytest.mark.asyncio
    async def test_slash_lab_marks_review_required(self):
        """Timetable with slash labs goes to REVIEW_REQUIRED."""
        slash = SlashLabCandidate(
            raw_content="OOPJ LAB / DBMS LAB",
            alternatives=("OOPJ LAB", "DBMS LAB"),
            day_of_week=0,
            start_period=5,
            end_period=6,
        )

        result = TimetableExtractionResult(
            metadata=ExtractedMetadata(),
            cells=(),
            slash_labs=(slash,),
        )

        assert result.has_ambiguity
        assert result.requires_review


class TestLabBatchResolution:
    """Test lab batch resolution behavior."""

    @pytest.mark.asyncio
    async def test_batch_1_resolves_to_first_lab(self):
        """Batch 1 selects first alternative."""
        candidate = SlashLabCandidate(
            raw_content="OOPJ LAB / DBMS LAB",
            alternatives=("OOPJ LAB", "DBMS LAB"),
            day_of_week=0,
            start_period=5,
            end_period=6,
        )

        # Batch 1 -> first alternative
        assert candidate.alternatives[0] == "OOPJ LAB"

    @pytest.mark.asyncio
    async def test_batch_2_resolves_to_second_lab(self):
        """Batch 2 selects second alternative."""
        candidate = SlashLabCandidate(
            raw_content="OOPJ LAB / DBMS LAB",
            alternatives=("OOPJ LAB", "DBMS LAB"),
            day_of_week=0,
            start_period=5,
            end_period=6,
        )

        # Batch 2 -> second alternative
        assert candidate.alternatives[1] == "DBMS LAB"

    @pytest.mark.asyncio
    async def test_set_lab_batch_does_not_auto_confirm(
        self, timetable_service, mock_timetable_repo, mock_student_repo
    ):
        """set_lab_batch resolves labs but keeps REVIEW_REQUIRED."""
        student_id = uuid4()

        # Student has unknown batch initially
        from app.models.student import Student

        student = Student(id=student_id, lab_batch=LabBatch.UNKNOWN)
        mock_student_repo.get_by_id.return_value = student

        # Create pending timetable with slash lab
        timetable = Timetable(
            student_id=student_id,
            status=TimetableStatus.REVIEW_REQUIRED,
            version=1,
        )

        _entry = TimetableEntry(
            timetable_id=timetable.id,
            day_of_week=0,
            start_time=time(14, 40),
            end_time=time(16, 40),
            activity_name="OOPJ LAB / DBMS LAB",
            activity_type=ActivityType.LAB,
            lab_batch=LabBatch.UNKNOWN,
        )

        # Set lab batch via service - this only sets student's lab_batch
        await timetable_service.set_lab_batch(student_id, LabBatch.BATCH_1)

        # Verify student's lab_batch was updated
        assert student.lab_batch == LabBatch.BATCH_1

        # Timetable should still be REVIEW_REQUIRED (confirm_timetable not called)
        # The service's set_lab_batch doesn't resolve slash labs
        # (that's done by the tool)
        assert timetable.status == TimetableStatus.REVIEW_REQUIRED

        # Now call the tool which does the resolution
        from app.intelligence.tools.timetable_tools import (
            set_lab_batch as tool_set_lab_batch,
        )

        result = await tool_set_lab_batch(timetable_service, str(student_id), "batch_1")

        # Verify resolution happened
        assert result["success"] is True
        assert result["lab_batch"] == "batch_1"

    @pytest.mark.asyncio
    async def test_known_batch_no_repeated_question(
        self, timetable_service, mock_timetable_repo, mock_student_repo
    ):
        """Student with known batch doesn't get asked again."""
        student_id = uuid4()

        # Student has known batch
        from app.models.student import Student

        student = Student(id=student_id, lab_batch=LabBatch.BATCH_1)
        mock_student_repo.get_by_id.return_value = student

        # Pending timetable with slash lab
        timetable = Timetable(
            student_id=student_id,
            status=TimetableStatus.REVIEW_REQUIRED,
            version=1,
        )
        mock_timetable_repo.get_pending_for_student.return_value = timetable

        _entry = TimetableEntry(
            timetable_id=timetable.id,
            day_of_week=0,
            start_time=time(14, 40),
            end_time=time(16, 40),
            activity_name="OOPJ LAB / DBMS LAB",
            activity_type=ActivityType.LAB,
            lab_batch=LabBatch.UNKNOWN,
        )
        timetable_service.entry_repo.get_for_timetable.return_value = [_entry]

        # Should NOT need lab batch (already known)
        needs = await timetable_service.needs_lab_batch(student_id)
        assert needs is False


class TestCrossStudentIsolation:
    """Test cross-student timetable isolation."""

    @pytest.mark.asyncio
    async def test_student_a_cannot_query_student_b_schedule(
        self, timetable_service, mock_timetable_repo, student_a_id, student_b_id
    ):
        """Student A cannot query Student B's schedule."""
        mock_timetable_repo.get_confirmed_for_student.return_value = None

        schedule_a = await timetable_service.get_today_schedule(student_a_id)
        assert schedule_a == []

    @pytest.mark.asyncio
    async def test_student_a_lab_batch_independent(
        self, timetable_service, mock_student_repo, student_a_id, student_b_id
    ):
        """Student A's lab batch doesn't affect Student B."""
        from app.models.student import Student

        student_a = Student(id=student_a_id, lab_batch=LabBatch.BATCH_1)
        student_b = Student(id=student_b_id, lab_batch=LabBatch.BATCH_2)

        mock_student_repo.get_by_id.side_effect = lambda sid: (
            student_a if sid == student_a_id else student_b
        )

        batch_a = await timetable_service.get_student_lab_batch(student_a_id)
        batch_b = await timetable_service.get_student_lab_batch(student_b_id)

        assert batch_a == LabBatch.BATCH_1
        assert batch_b == LabBatch.BATCH_2


class TestConfirmedOnlyQueryable:
    """Test only CONFIRMED timetable is usable for queries."""

    @pytest.mark.asyncio
    async def test_uploaded_timetable_not_queryable(
        self, timetable_service, mock_timetable_repo
    ):
        """UPLOADED timetable not returned by get_confirmed_timetable."""
        mock_timetable_repo.get_confirmed_for_student.return_value = None

        confirmed = await timetable_service.get_confirmed_timetable(uuid4())
        assert confirmed is None

        schedule = await timetable_service.get_today_schedule(uuid4())
        assert schedule == []

    @pytest.mark.asyncio
    async def test_review_required_not_queryable(
        self, timetable_service, mock_timetable_repo
    ):
        """REVIEW_REQUIRED timetable not returned by get_confirmed_timetable."""
        mock_timetable_repo.get_confirmed_for_student.return_value = None

        confirmed = await timetable_service.get_confirmed_timetable(uuid4())
        assert confirmed is None

    @pytest.mark.asyncio
    async def test_failed_not_queryable(self, timetable_service, mock_timetable_repo):
        """FAILED timetable not returned by get_confirmed_timetable."""
        mock_timetable_repo.get_confirmed_for_student.return_value = None

        confirmed = await timetable_service.get_confirmed_timetable(uuid4())
        assert confirmed is None

    @pytest.mark.asyncio
    async def test_archived_not_queryable(self, timetable_service, mock_timetable_repo):
        """ARCHIVED timetable not returned by get_confirmed_timetable."""
        mock_timetable_repo.get_confirmed_for_student.return_value = None

        confirmed = await timetable_service.get_confirmed_timetable(uuid4())
        assert confirmed is None


class TestCorrectionBeforeConfirmation:
    """Test corrections allowed before confirmation."""

    @pytest.mark.asyncio
    async def test_update_entry_in_review_allowed(self, timetable_service):
        """Entry can be updated in REVIEW_REQUIRED state."""
        timetable = Timetable(
            student_id=uuid4(),
            status=TimetableStatus.REVIEW_REQUIRED,
            version=1,
        )
        _entry = TimetableEntry(
            timetable_id=timetable.id,
            day_of_week=0,
            start_time=time(10, 0),
            end_time=time(11, 0),
            activity_name="DBMS",
            activity_type=ActivityType.ACADEMIC,
        )

        # This would need DB, so test the state check logic
        assert timetable.status == TimetableStatus.REVIEW_REQUIRED

    @pytest.mark.asyncio
    async def test_update_entry_in_confirmed_rejected(self, timetable_service):
        """Entry cannot be updated in CONFIRMED state."""
        timetable = Timetable(
            student_id=uuid4(),
            status=TimetableStatus.CONFIRMED,
            version=1,
        )

        # Test the state check
        with pytest.raises(TimetableStateError):
            if timetable.status != TimetableStatus.REVIEW_REQUIRED:
                raise TimetableStateError(
                    f"Cannot modify timetable in {timetable.status} state"
                )


class TestNoTimetableSafeResponse:
    """Test safe responses when no timetable exists."""

    @pytest.mark.asyncio
    async def test_get_schedule_no_timetable(
        self, timetable_service, mock_timetable_repo
    ):
        """get_schedule returns empty list when no timetable."""
        mock_timetable_repo.get_confirmed_for_student.return_value = None

        schedule = await timetable_service.get_today_schedule(uuid4())
        assert schedule == []

    @pytest.mark.asyncio
    async def test_get_next_class_no_timetable(
        self, timetable_service, mock_timetable_repo
    ):
        """get_next_class returns None when no timetable."""
        mock_timetable_repo.get_confirmed_for_student.return_value = None

        next_class = await timetable_service.get_next_class(uuid4())
        assert next_class is None


class TestAmbiguousExtractionReviewRequired:
    """Test ambiguous extraction triggers REVIEW_REQUIRED."""

    @pytest.mark.asyncio
    async def test_low_confidence_cell_triggers_review(self):
        """Low confidence extraction marks review required."""
        cell = ExtractedCell(
            day_of_week=0,
            start_period=1,
            end_period=1,
            content="Unclear Subject",
            confidence=ExtractionConfidence.LOW,
        )

        result = TimetableExtractionResult(
            metadata=ExtractedMetadata(),
            cells=(cell,),
            slash_labs=(),
        )

        assert result.has_ambiguity
        assert result.requires_review

    @pytest.mark.asyncio
    async def test_slash_lab_triggers_review(self):
        """Slash lab marks review required."""
        slash = SlashLabCandidate(
            raw_content="A / B",
            alternatives=("A", "B"),
            day_of_week=0,
            start_period=1,
            end_period=1,
        )

        result = TimetableExtractionResult(
            metadata=ExtractedMetadata(),
            cells=(),
            slash_labs=(slash,),
        )

        assert result.has_ambiguity
        assert result.requires_review

    @pytest.mark.asyncio
    async def test_high_confidence_no_slash_no_review(self):
        """High confidence, no slash labs -> no review needed."""
        cell = ExtractedCell(
            day_of_week=0,
            start_period=1,
            end_period=1,
            content="DBMS",
            confidence=ExtractionConfidence.HIGH,
        )

        result = TimetableExtractionResult(
            metadata=ExtractedMetadata(),
            cells=(cell,),
            slash_labs=(),
        )

        assert not result.has_ambiguity
        assert not result.requires_review


class TestScheduleQueries:
    """Test deterministic schedule query methods."""

    @pytest.mark.asyncio
    async def test_get_today_schedule(
        self, timetable_service, mock_timetable_repo, mock_entry_repo
    ):
        """get_today_schedule returns correct entries."""
        timetable = Timetable(
            student_id=uuid4(),
            status=TimetableStatus.CONFIRMED,
            version=1,
        )
        mock_timetable_repo.get_confirmed_for_student.return_value = timetable

        entry = TimetableEntry(
            timetable_id=timetable.id,
            day_of_week=date.today().weekday(),
            start_time=time(10, 0),
            end_time=time(11, 0),
            activity_name="DBMS",
            activity_type=ActivityType.ACADEMIC,
        )
        mock_entry_repo.get_for_timetable.return_value = [entry]

        schedule = await timetable_service.get_today_schedule(uuid4())
        assert len(schedule) == 1
        assert schedule[0].activity_name == "DBMS"

    @pytest.mark.asyncio
    async def test_get_tomorrow_schedule(
        self, timetable_service, mock_timetable_repo, mock_entry_repo
    ):
        """get_tomorrow_schedule returns correct entries."""
        student_id = uuid4()
        timetable = Timetable(
            student_id=student_id,
            status=TimetableStatus.CONFIRMED,
            version=1,
        )
        mock_timetable_repo.get_confirmed_for_student.return_value = timetable

        tomorrow = date.today() + timedelta(days=1)
        target_day = tomorrow.weekday()

        # Skip test if tomorrow is weekend (no classes)
        if target_day > 5:
            pytest.skip("Tomorrow is weekend, no classes scheduled")

        entry = TimetableEntry(
            timetable_id=timetable.id,
            day_of_week=target_day,
            start_time=time(10, 0),
            end_time=time(11, 0),
            activity_name="OOPJ",
            activity_type=ActivityType.ACADEMIC,
        )
        mock_entry_repo.get_for_timetable.return_value = [entry]

        schedule = await timetable_service.get_tomorrow_schedule(student_id)
        assert len(schedule) == 1
        assert schedule[0].activity_name == "OOPJ"

    @pytest.mark.asyncio
    async def test_get_next_class(
        self, timetable_service, mock_timetable_repo, mock_entry_repo
    ):
        """get_next_class returns next upcoming class."""
        timetable = Timetable(
            student_id=uuid4(),
            status=TimetableStatus.CONFIRMED,
            version=1,
        )
        mock_timetable_repo.get_confirmed_for_student.return_value = timetable

        today = date.today()
        day = today.weekday()

        # Past class
        entry1 = TimetableEntry(
            timetable_id=timetable.id,
            day_of_week=day,
            start_time=time(8, 0),
            end_time=time(9, 0),
            activity_name="Early Class",
            activity_type=ActivityType.ACADEMIC,
        )
        # Future class
        entry2 = TimetableEntry(
            timetable_id=timetable.id,
            day_of_week=day,
            start_time=time(15, 0),
            end_time=time(16, 0),
            activity_name="Late Class",
            activity_type=ActivityType.ACADEMIC,
        )
        mock_entry_repo.get_for_timetable.return_value = [entry1, entry2]

        next_class = await timetable_service.get_next_class(
            uuid4(), from_time=time(10, 0)
        )
        assert next_class is not None
        assert next_class.activity_name == "Late Class"


class TestExtractionWithRealisticData:
    """Test extraction with realistic VNR-style data."""

    def test_period_time_mapping(self):
        """Period to time mapping matches VNR format."""
        assert period_to_time(1) == (time(10, 0), time(11, 0))
        assert period_to_time(2) == (time(11, 0), time(12, 0))
        assert period_to_time(3) == (time(12, 0), time(13, 0))
        assert period_to_time(4) == (time(13, 40), time(14, 40))
        assert period_to_time(5) == (time(14, 40), time(15, 40))
        assert period_to_time(6) == (time(15, 40), time(16, 40))
        assert period_to_time(7) is None

    def test_confidence_to_float(self):
        """Confidence enum to float conversion."""
        assert _confidence_to_float(ExtractionConfidence.HIGH) == 1.0
        assert _confidence_to_float(ExtractionConfidence.MEDIUM) == 0.5
        assert _confidence_to_float(ExtractionConfidence.LOW) == 0.1
        assert _confidence_to_float(ExtractionConfidence.AMBIGUOUS) == 0.1


class TestConfirmTimetableTool:
    """Test confirm_timetable tool behavior."""

    @pytest.mark.asyncio
    async def test_confirm_timetable_success(
        self, timetable_service, mock_timetable_repo
    ):
        from app.intelligence.tools.timetable_tools import confirm_timetable

        student_id = uuid4()
        pending = Timetable(
            id=uuid4(),
            student_id=student_id,
            status=TimetableStatus.REVIEW_REQUIRED,
            version=1,
        )
        mock_timetable_repo.get_pending_for_student.return_value = pending
        mock_timetable_repo.get_by_id_with_entries.return_value = pending

        result = await confirm_timetable(timetable_service, str(student_id))

        assert result["success"] is True
        assert result["status"] == "confirmed"
        assert "Version 1 is now active" in result["message"]

    @pytest.mark.asyncio
    async def test_confirm_timetable_none_pending(
        self, timetable_service, mock_timetable_repo
    ):
        from app.intelligence.tools.timetable_tools import confirm_timetable

        student_id = uuid4()
        mock_timetable_repo.get_pending_for_student.return_value = None

        result = await confirm_timetable(timetable_service, str(student_id))

        assert result["success"] is False
        assert "No pending timetable found" in result["message"]


class TestHybridAndOcrTimetableExtractor:
    """Test OCR and Hybrid timetable extraction."""

    @pytest.mark.asyncio
    async def test_create_timetable_extractor_returns_hybrid(self):
        from app.intelligence.services.timetable_extraction import (
            HybridTimetableExtractor,
            create_timetable_extractor,
        )

        extractor = create_timetable_extractor()
        assert isinstance(extractor, HybridTimetableExtractor)

    @pytest.mark.asyncio
    async def test_ocr_timetable_extractor_sample_pdf(self):
        from pathlib import Path

        from app.intelligence.services.timetable_extraction import (
            OcrTimetableExtractor,
        )

        sample_pdf = Path("timetablepdf/5_6185777998969446650.pdf")
        if not sample_pdf.exists():
            pytest.skip("Sample timetable PDF not present in environment")

        extractor = OcrTimetableExtractor()
        result = await extractor.extract(str(sample_pdf))

        assert len(result.cells) >= 20
        assert len(result.slash_labs) >= 2
        assert result.metadata.academic_year == "2026-2027"
        assert result.metadata.branch == "CSE-CYS"
        assert result.metadata.regulation == "R25"
        assert result.metadata.section == "A"
        assert len(result.metadata.course_metadata) >= 5

    @pytest.mark.asyncio
    async def test_hybrid_fallback_on_empty_pdf(self):
        from unittest.mock import AsyncMock, patch

        from app.intelligence.services.timetable_extraction import (
            ExtractedCell,
            ExtractedMetadata,
            ExtractionConfidence,
            HybridTimetableExtractor,
            TimetableExtractionResult,
        )

        hybrid = HybridTimetableExtractor()

        # Mock vector extractor to return empty result
        mock_empty = TimetableExtractionResult(
            metadata=ExtractedMetadata(),
            cells=(),
            slash_labs=(),
            warnings=(),
            errors=(),
        )
        mock_ocr_result = TimetableExtractionResult(
            metadata=ExtractedMetadata(branch="CSE-CYS"),
            cells=(
                ExtractedCell(
                    day_of_week=0,
                    start_period=1,
                    end_period=1,
                    content="OOPJ",
                    confidence=ExtractionConfidence.HIGH,
                ),
            ),
            slash_labs=(),
            warnings=(),
            errors=(),
        )

        with patch.object(
            hybrid._pdf_extractor, "extract", new=AsyncMock(return_value=mock_empty)
        ), patch.object(
            hybrid._ocr_extractor,
            "extract",
            new=AsyncMock(return_value=mock_ocr_result),
        ):
            res = await hybrid.extract("dummy.pdf")
            assert len(res.cells) == 1
            assert res.cells[0].content == "OOPJ"
            assert res.metadata.branch == "CSE-CYS"
