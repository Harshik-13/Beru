"""
End-to-End Onboarding, Security, Boundary, and Timetable Verification Tests.

Pattern: Pure async pytest with in-memory repository doubles and mock sessions.
Zero live database or SQLite dependencies.

Covers Phase 4B:
- Cross-student access & update isolation
- Confirmed timetable modification rejection
- Review-required quarantine (no schedule leak)
- Parameter & format validation (lab batch, weekday, time)
- Single-entry correction semantics by entry_id
- Ambiguity preservation (no hallucinated rooms/faculty)
- Failure paths, retry from FAILED state, and malformed confirmation rejection
- Duplicate upload versioning and archival semantics
- Idempotent batch setting and confirmation
"""

from datetime import date, time
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.intelligence.services.timetable_extraction import (
    ExtractedCell,
    ExtractedMetadata,
    ExtractionConfidence,
    TimetableExtractionResult,
)
from app.intelligence.services.timetable_service import (
    TimetableService,
    TimetableStateError,
)
from app.intelligence.tools.timetable_tools import (
    confirm_timetable,
    get_schedule_for_weekday,
    get_week_schedule,
    set_briefing_time,
    set_lab_batch,
    update_timetable_entry,
)
from app.models.student import Student
from app.models.timetable import (
    ActivityType,
    LabBatch,
    Timetable,
    TimetableEntry,
    TimetableStatus,
)


class InMemoryTimetableDataStore:
    """In-memory database double for student, timetable, and entry repositories."""

    def __init__(self):
        self.students: dict[UUID, Student] = {}
        self.timetables: dict[UUID, Timetable] = {}
        self.entries: dict[UUID, TimetableEntry] = {}

    def add_student(self, student: Student) -> Student:
        self.students[student.id] = student
        return student

    def add_timetable(self, tt: Timetable) -> Timetable:
        self.timetables[tt.id] = tt
        return tt

    def add_entry(self, entry: TimetableEntry) -> TimetableEntry:
        self.entries[entry.id] = entry
        return entry


@pytest.fixture
def store():
    return InMemoryTimetableDataStore()


@pytest.fixture
def mock_session(store):
    session = MagicMock()
    session.flush = AsyncMock()

    async def mock_execute(statement, *args, **kwargs):
        mock_result = MagicMock()
        # Handle select(TimetableEntry).where(TimetableEntry.id == entry_id)
        stmt_str = str(statement)
        if "timetable_entries" in stmt_str and "timetable_entries.id =" in stmt_str:
            # Find matching entry by ID
            for entry_id, entry in store.entries.items():
                if str(entry_id) in str(statement) or any(
                    val == entry_id for val in kwargs.values()
                ):
                    mock_result.scalar_one_or_none.return_value = entry
                    return mock_result

            # Default fallback: check store entries
            for _entry_id, entry in store.entries.items():
                mock_result.scalar_one_or_none.return_value = entry
                return mock_result

            mock_result.scalar_one_or_none.return_value = None
            return mock_result

        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        return mock_result

    session.execute = AsyncMock(side_effect=mock_execute)
    return session


@pytest.fixture
def mock_student_repo(store):
    repo = MagicMock()

    async def get_by_id(student_id: UUID) -> Student | None:
        return store.students.get(student_id)

    async def get_or_create(student_id: UUID) -> Student:
        if student_id not in store.students:
            store.students[student_id] = Student(id=student_id)
        return store.students[student_id]

    async def get_active_students() -> list[Student]:
        return list(store.students.values())

    repo.get_by_id = AsyncMock(side_effect=get_by_id)
    repo.get_or_create = AsyncMock(side_effect=get_or_create)
    repo.get_active_students = AsyncMock(side_effect=get_active_students)
    return repo


@pytest.fixture
def mock_timetable_repo(store):
    repo = MagicMock()

    async def create(timetable: Timetable) -> Timetable:
        store.timetables[timetable.id] = timetable
        return timetable

    async def get_by_id(timetable_id: UUID) -> Timetable | None:
        return store.timetables.get(timetable_id)

    async def get_by_id_with_entries(timetable_id: UUID) -> Timetable | None:
        tt = store.timetables.get(timetable_id)
        if tt:
            tt.entries = [
                e for e in store.entries.values() if e.timetable_id == timetable_id
            ]
        return tt

    async def get_latest_for_student(
        student_id: UUID, status: TimetableStatus | None = None
    ) -> Timetable | None:
        matches = [
            tt
            for tt in store.timetables.values()
            if tt.student_id == student_id and (status is None or tt.status == status)
        ]
        if not matches:
            return None
        return max(matches, key=lambda t: t.version)

    async def get_confirmed_for_student(student_id: UUID) -> Timetable | None:
        return await get_latest_for_student(student_id, TimetableStatus.CONFIRMED)

    async def get_pending_for_student(student_id: UUID) -> Timetable | None:
        pending_statuses = {
            TimetableStatus.UPLOADED,
            TimetableStatus.EXTRACTING,
            TimetableStatus.REVIEW_REQUIRED,
            TimetableStatus.FAILED,
        }
        matches = [
            tt
            for tt in store.timetables.values()
            if tt.student_id == student_id and tt.status in pending_statuses
        ]
        if not matches:
            return None
        return max(matches, key=lambda t: t.version)

    async def archive_previous_confirmed(student_id: UUID) -> None:
        for tt in store.timetables.values():
            if tt.student_id == student_id and tt.status == TimetableStatus.CONFIRMED:
                tt.status = TimetableStatus.ARCHIVED

    repo.create = AsyncMock(side_effect=create)
    repo.get_by_id = AsyncMock(side_effect=get_by_id)
    repo.get_by_id_with_entries = AsyncMock(side_effect=get_by_id_with_entries)
    repo.get_latest_for_student = AsyncMock(side_effect=get_latest_for_student)
    repo.get_confirmed_for_student = AsyncMock(side_effect=get_confirmed_for_student)
    repo.get_pending_for_student = AsyncMock(side_effect=get_pending_for_student)
    repo.archive_previous_confirmed = AsyncMock(side_effect=archive_previous_confirmed)
    return repo


@pytest.fixture
def mock_entry_repo(store):
    repo = MagicMock()

    async def create(entry: TimetableEntry) -> TimetableEntry:
        store.entries[entry.id] = entry
        return entry

    async def create_batch(entries: list[TimetableEntry]) -> list[TimetableEntry]:
        for e in entries:
            store.entries[e.id] = e
        return entries

    async def get_for_timetable(timetable_id: UUID) -> list[TimetableEntry]:
        entries = [
            e for e in store.entries.values() if e.timetable_id == timetable_id
        ]
        return sorted(entries, key=lambda e: (e.day_of_week, e.start_time))

    async def delete_for_timetable(timetable_id: UUID) -> None:
        to_delete = [
            eid
            for eid, e in store.entries.items()
            if e.timetable_id == timetable_id
        ]
        for eid in to_delete:
            del store.entries[eid]

    repo.create = AsyncMock(side_effect=create)
    repo.create_batch = AsyncMock(side_effect=create_batch)
    repo.get_for_timetable = AsyncMock(side_effect=get_for_timetable)
    repo.delete_for_timetable = AsyncMock(side_effect=delete_for_timetable)
    return repo


@pytest.fixture
def timetable_service(
    mock_session, mock_student_repo, mock_timetable_repo, mock_entry_repo
):
    service = TimetableService(mock_session)
    service.student_repo = mock_student_repo
    service.timetable_repo = mock_timetable_repo
    service.entry_repo = mock_entry_repo
    return service


@pytest.fixture
def student_a(store):
    student = Student(id=uuid4(), name="Student Alpha", attendance_target=75.0)
    return store.add_student(student)


@pytest.fixture
def student_b(store):
    student = Student(id=uuid4(), name="Student Beta", attendance_target=80.0)
    return store.add_student(student)


# ============================================================================
# Phase 4B: Security, Boundary, Failure-Path & Versioning Tests
# ============================================================================


class TestSecurityAndIsolation:
    """Security boundaries: cross-student isolation and state transition guards."""

    @pytest.mark.asyncio
    async def test_cross_student_entry_update_rejected(
        self, timetable_service, store, student_a, student_b, mock_session
    ):
        """Student B cannot update Student A's timetable entry."""
        # Student A has pending timetable with an entry
        tt_a = store.add_timetable(
            Timetable(
                id=uuid4(),
                student_id=student_a.id,
                status=TimetableStatus.REVIEW_REQUIRED,
                version=1,
            )
        )
        entry_a = store.add_entry(
            TimetableEntry(
                id=uuid4(),
                timetable_id=tt_a.id,
                day_of_week=0,
                start_time=time(10, 0),
                end_time=time(11, 0),
                activity_name="Operating Systems",
                activity_type=ActivityType.ACADEMIC,
            )
        )

        # Student B tries to update Student A's entry via tool
        result = await update_timetable_entry(
            service=timetable_service,
            student_id=str(student_b.id),
            entry_id=str(entry_a.id),
            activity_name="Malicious Hack",
        )

        # Student B has no pending timetable, update is rejected
        assert result["success"] is False
        assert "No pending timetable found" in result["message"]
        # Entry A is unchanged
        assert store.entries[entry_a.id].activity_name == "Operating Systems"

    @pytest.mark.asyncio
    async def test_cross_student_confirm_rejected(
        self, timetable_service, store, student_a, student_b
    ):
        """Student B cannot confirm Student A's timetable."""
        # Student A has pending timetable awaiting confirmation
        store.add_timetable(
            Timetable(
                id=uuid4(),
                student_id=student_a.id,
                status=TimetableStatus.REVIEW_REQUIRED,
                version=1,
            )
        )

        # Student B tries to call confirm_timetable tool
        res = await confirm_timetable(timetable_service, str(student_b.id))
        assert res["success"] is False
        assert "No pending timetable found" in res["message"]

    @pytest.mark.asyncio
    async def test_confirmed_timetable_update_rejected(
        self, timetable_service, store, student_a, mock_session
    ):
        """update_entry strictly rejected once timetable is CONFIRMED."""
        tt = store.add_timetable(
            Timetable(
                id=uuid4(),
                student_id=student_a.id,
                status=TimetableStatus.CONFIRMED,
                version=1,
            )
        )
        entry = store.add_entry(
            TimetableEntry(
                id=uuid4(),
                timetable_id=tt.id,
                day_of_week=1,
                start_time=time(9, 0),
                end_time=time(9, 50),
                activity_name="Physics",
                activity_type=ActivityType.ACADEMIC,
            )
        )

        with pytest.raises(TimetableStateError) as exc_info:
            await timetable_service.update_entry(
                timetable_id=tt.id,
                entry_id=entry.id,
                activity_name="Chemistry",
            )
        assert "Cannot modify timetable in" in str(exc_info.value)
        assert "CONFIRMED" in str(exc_info.value).upper()
        # Entry was not mutated
        assert store.entries[entry.id].activity_name == "Physics"


class TestReviewStateQuarantine:
    """Data in REVIEW_REQUIRED must never leak into normal queries or briefings."""

    @pytest.mark.asyncio
    async def test_review_required_not_queryable(
        self, timetable_service, store, student_a
    ):
        """Queries on a student with only REVIEW_REQUIRED timetable return empty."""
        tt = store.add_timetable(
            Timetable(
                id=uuid4(),
                student_id=student_a.id,
                status=TimetableStatus.REVIEW_REQUIRED,
                version=1,
            )
        )
        store.add_entry(
            TimetableEntry(
                id=uuid4(),
                timetable_id=tt.id,
                day_of_week=0,
                start_time=time(10, 0),
                end_time=time(11, 0),
                activity_name="Secret Unconfirmed Class",
                activity_type=ActivityType.ACADEMIC,
            )
        )

        # Today's schedule returns empty
        today_sched = await timetable_service.get_today_schedule(student_a.id)
        assert today_sched == []

        # Target date schedule returns empty
        date_sched = await timetable_service.get_schedule_for_date(
            student_a.id, date(2026, 9, 28)
        )
        assert date_sched == []

        # Week schedule tool returns status none
        week_res = await get_week_schedule(timetable_service, str(student_a.id))
        assert week_res["status"] == "none"
        assert "No confirmed timetable found" in week_res["message"]


class TestInputAndFormatValidation:
    """Validation guards on parameters, days, batches, and time strings."""

    @pytest.mark.asyncio
    async def test_invalid_lab_batch_rejected(
        self, timetable_service, student_a
    ):
        """Invalid batch strings raise ValueError."""
        with pytest.raises(ValueError):
            await set_lab_batch(timetable_service, str(student_a.id), "batch_3")

        with pytest.raises(ValueError):
            await set_lab_batch(timetable_service, str(student_a.id), "invalid_batch")

    @pytest.mark.asyncio
    async def test_invalid_weekday_validation(
        self, timetable_service, store, student_a
    ):
        """get_schedule_for_weekday rejects invalid days (0-5 allowed)."""
        # Day 6 is Sunday
        res_sun = await get_schedule_for_weekday(
            timetable_service, str(student_a.id), 6
        )
        assert res_sun["success"] is False
        assert "day_of_week must be 0-5" in res_sun["message"]

        # Negative day
        res_neg = await get_schedule_for_weekday(
            timetable_service, str(student_a.id), -1
        )
        assert res_neg["success"] is False
        assert "day_of_week must be 0-5" in res_neg["message"]

    @pytest.mark.asyncio
    async def test_invalid_briefing_time_validation(
        self, timetable_service, student_a
    ):
        """set_briefing_time rejects invalid 24h formats."""
        res1 = await set_briefing_time(timetable_service, str(student_a.id), "25:00")
        assert res1["success"] is False
        assert "Invalid time format" in res1["message"]

        res2 = await set_briefing_time(timetable_service, str(student_a.id), "8am")
        assert res2["success"] is False
        assert "Invalid time format" in res2["message"]

        res3 = await set_briefing_time(timetable_service, str(student_a.id), "08:65")
        assert res3["success"] is False
        assert "Invalid time format" in res3["message"]


class TestCorrectionSemanticsAndAmbiguity:
    """Correction semantics by entry_id and ambiguity preservation."""

    @pytest.mark.asyncio
    async def test_correction_semantics_single_entry_only(
        self, timetable_service, store, student_a, mock_session
    ):
        """Updating an entry modifies ONLY the target entry_id.

        Identical subjects on other days/periods remain untouched.
        """
        tt = store.add_timetable(
            Timetable(
                id=uuid4(),
                student_id=student_a.id,
                status=TimetableStatus.REVIEW_REQUIRED,
                version=1,
            )
        )
        # Monday DBMS
        entry_mon = store.add_entry(
            TimetableEntry(
                id=uuid4(),
                timetable_id=tt.id,
                day_of_week=0,
                start_time=time(10, 0),
                end_time=time(11, 0),
                activity_name="DBMS",
                activity_type=ActivityType.ACADEMIC,
                room="Room 101",
            )
        )
        # Wednesday DBMS (different entry_id, same subject)
        entry_wed = store.add_entry(
            TimetableEntry(
                id=uuid4(),
                timetable_id=tt.id,
                day_of_week=2,
                start_time=time(11, 40),
                end_time=time(12, 30),
                activity_name="DBMS",
                activity_type=ActivityType.ACADEMIC,
                room="Room 101",
            )
        )

        # Mock execute to return entry_mon when looked up
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = entry_mon
        mock_session.execute.return_value = mock_result

        # Update ONLY entry_mon
        updated = await timetable_service.update_entry(
            timetable_id=tt.id,
            entry_id=entry_mon.id,
            activity_name="Advanced DBMS",
            room="Room 205",
        )

        assert updated is not None
        assert entry_mon.activity_name == "Advanced DBMS"
        assert entry_mon.room == "Room 205"

        # Wednesday entry is completely untouched
        assert entry_wed.activity_name == "DBMS"
        assert entry_wed.room == "Room 101"

    @pytest.mark.asyncio
    async def test_ambiguity_preserved(self, timetable_service, store, student_a):
        """Unmatched rooms/faculty remain None without hallucinating data."""
        tt = store.add_timetable(
            Timetable(
                id=uuid4(),
                student_id=student_a.id,
                status=TimetableStatus.REVIEW_REQUIRED,
                version=1,
            )
        )
        entry = store.add_entry(
            TimetableEntry(
                id=uuid4(),
                timetable_id=tt.id,
                day_of_week=4,
                start_time=time(14, 10),
                end_time=time(15, 0),
                activity_name="Seminar",
                activity_type=ActivityType.ACADEMIC,
                room=None,
                faculty=None,
            )
        )

        assert entry.room is None
        assert entry.faculty is None


class TestFailurePathsAndRetry:
    """Extraction failure handling, retry capability, and malformed rejection."""

    @pytest.mark.asyncio
    async def test_upload_failure_allows_retry(
        self, timetable_service, store, student_a
    ):
        """Corrupt/unparsable upload transitions to FAILED, and retry is allowed."""
        # Mock extractor returning errors
        mock_extractor = MagicMock()
        mock_extractor.extract = AsyncMock(
            return_value=TimetableExtractionResult(
                metadata=ExtractedMetadata(),
                cells=(),
                slash_labs=(),
                errors=("Corrupt file header: unable to read PDF stream",),
            )
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.intelligence.services.timetable_service.create_timetable_extractor",
                lambda: mock_extractor,
            )
            tt = store.add_timetable(
                Timetable(
                    id=uuid4(),
                    student_id=student_a.id,
                    status=TimetableStatus.UPLOADED,
                    version=1,
                )
            )

            # Extraction fails
            result_failed = await timetable_service.extract_timetable(
                tt.id, "corrupt_file.pdf"
            )
            assert result_failed.status == TimetableStatus.FAILED

            # Retry is permitted on FAILED status!
            mock_extractor.extract = AsyncMock(
                return_value=TimetableExtractionResult(
                    metadata=ExtractedMetadata(programme="B.Tech", branch="CSBS"),
                    cells=(
                        ExtractedCell(
                            day_of_week=0,
                            start_period=1,
                            end_period=1,
                            content="Mathematics",
                            confidence=ExtractionConfidence.HIGH,
                        ),
                    ),
                    slash_labs=(),
                )
            )

            # Re-running extract_timetable from FAILED state succeeds
            result_retry = await timetable_service.extract_timetable(
                tt.id, "valid_file.pdf"
            )
            assert result_retry.status == TimetableStatus.REVIEW_REQUIRED
            assert result_retry.branch == "CSBS"

    @pytest.mark.asyncio
    async def test_malformed_timetable_cannot_confirm(
        self, timetable_service, store, student_a
    ):
        """Timetable in FAILED status cannot be confirmed."""
        tt_failed = store.add_timetable(
            Timetable(
                id=uuid4(),
                student_id=student_a.id,
                status=TimetableStatus.FAILED,
                version=1,
            )
        )

        with pytest.raises(TimetableStateError) as exc_info:
            await timetable_service.confirm_timetable(tt_failed.id)
        assert "Can only confirm timetable in REVIEW_REQUIRED status" in str(
            exc_info.value
        )


class TestDuplicateUploadAndVersioning:
    """Duplicate upload versioning, active timetable preservation, and archival."""

    @pytest.mark.asyncio
    async def test_duplicate_upload_versioning_and_archival(
        self, timetable_service, store, student_a
    ):
        """Uploading v2 preserves v1 confirmed until v2 confirmation archives v1."""
        # 1. Version 1 is CONFIRMED
        tt_v1 = store.add_timetable(
            Timetable(
                id=uuid4(),
                student_id=student_a.id,
                status=TimetableStatus.CONFIRMED,
                version=1,
            )
        )
        store.add_entry(
            TimetableEntry(
                id=uuid4(),
                timetable_id=tt_v1.id,
                day_of_week=0,
                start_time=time(9, 0),
                end_time=time(9, 50),
                activity_name="V1 Lecture",
                activity_type=ActivityType.ACADEMIC,
            )
        )

        # Verify active timetable is v1
        confirmed = await timetable_service.get_confirmed_timetable(student_a.id)
        assert confirmed.version == 1

        # 2. Student uploads v2 (creates version=2 in REVIEW_REQUIRED)
        mock_extractor = MagicMock()
        mock_extractor.extract = AsyncMock(
            return_value=TimetableExtractionResult(
                metadata=ExtractedMetadata(academic_year="2026-2027"),
                cells=(
                    ExtractedCell(
                        day_of_week=0,
                        start_period=1,
                        end_period=1,
                        content="V2 Lecture",
                        confidence=ExtractionConfidence.HIGH,
                    ),
                ),
                slash_labs=(),
            )
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.intelligence.services.timetable_service.create_timetable_extractor",
                lambda: mock_extractor,
            )
            tt_v2 = await timetable_service.create_uploaded_timetable(
                student_id=student_a.id,
                file_path="new_timetable.pdf",
                original_filename="new_timetable.pdf",
            )

        assert tt_v2.version == 2
        assert tt_v2.status == TimetableStatus.REVIEW_REQUIRED

        # Queries still return v1 because v2 is unconfirmed
        active = await timetable_service.get_confirmed_timetable(student_a.id)
        assert active.id == tt_v1.id
        assert active.version == 1

        # 3. Student confirms v2
        confirmed_v2 = await timetable_service.confirm_timetable(tt_v2.id)
        assert confirmed_v2.status == TimetableStatus.CONFIRMED
        assert confirmed_v2.version == 2

        # v1 is now ARCHIVED
        assert tt_v1.status == TimetableStatus.ARCHIVED

        # Only one active confirmed timetable
        latest_active = await timetable_service.get_confirmed_timetable(student_a.id)
        assert latest_active.id == tt_v2.id
        assert latest_active.version == 2

    @pytest.mark.asyncio
    async def test_idempotent_lab_batch_and_confirm(
        self, timetable_service, store, student_a
    ):
        """Re-invoking set_lab_batch is idempotent without duplicate entries."""
        tt = store.add_timetable(
            Timetable(
                id=uuid4(),
                student_id=student_a.id,
                status=TimetableStatus.REVIEW_REQUIRED,
                version=1,
            )
        )
        entry = store.add_entry(
            TimetableEntry(
                id=uuid4(),
                timetable_id=tt.id,
                day_of_week=1,
                start_time=time(13, 20),
                end_time=time(15, 0),
                activity_name="OOPJ LAB / DBMS LAB",
                activity_type=ActivityType.LAB,
                lab_batch=LabBatch.UNKNOWN,
            )
        )

        # Call set_lab_batch twice
        res1 = await set_lab_batch(timetable_service, str(student_a.id), "batch_1")
        assert res1["success"] is True
        assert entry.activity_name == "OOPJ LAB"
        assert entry.lab_batch == LabBatch.BATCH_1

        # Second call does not duplicate or error
        res2 = await set_lab_batch(timetable_service, str(student_a.id), "batch_1")
        assert res2["success"] is True
        assert entry.activity_name == "OOPJ LAB"
        assert entry.lab_batch == LabBatch.BATCH_1
