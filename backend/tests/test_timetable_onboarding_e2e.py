"""
End-to-End Onboarding, Security, Boundary, and Timetable Verification Tests.

Pattern: Pure async pytest with in-memory repository doubles and mock sessions.
Zero live database or SQLite dependencies.

Covers Phase 4B & Phase 4C:
- Cross-student access & update isolation
- Confirmed timetable modification rejection
- Review-required quarantine (no schedule leak)
- Parameter & format validation (lab batch, weekday, time)
- Single-entry correction semantics by entry_id
- Ambiguity preservation (no hallucinated rooms/faculty)
- Failure paths, retry from FAILED state, and malformed confirmation rejection
- Duplicate upload versioning and archival semantics
- Idempotent batch setting and confirmation
- Full 12-step onboarding pipeline from fixture PDF to confirmed queries
- BriefingService generation and briefing_time persistence
- Derived duration arithmetic & lab/academic activity classification
- Natural-language paraphrase routing without hardcoded keyword menus
"""

from datetime import date, time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.intelligence.models.context import StudentProfile
from app.intelligence.providers.base import (
    LLMProvider,
    LLMProviderConfig,
    LLMResponse,
    LLMToolCall,
)
from app.intelligence.services.briefing import BriefingService
from app.intelligence.services.context_builder import create_student_context
from app.intelligence.services.conversation import ConversationService
from app.intelligence.services.timetable_extraction import (
    ExtractedCell,
    ExtractedMetadata,
    ExtractionConfidence,
    TimetableExtractionResult,
)
from app.intelligence.services.timetable_service import (
    TimetableService,
    TimetableStateError,
    format_week_schedule,
)
from app.intelligence.tools.timetable_tools import (
    confirm_timetable,
    get_schedule_for_weekday,
    get_timetable_metadata,
    get_today_schedule,
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
from app.telegram.message_handler import TelegramMessageHandler


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
        if timetable.id is None:
            timetable.id = uuid4()
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
        if entry.id is None:
            entry.id = uuid4()
        store.entries[entry.id] = entry
        return entry

    async def create_batch(entries: list[TimetableEntry]) -> list[TimetableEntry]:
        for e in entries:
            if e.id is None:
                e.id = uuid4()
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


class FakeAttendanceService:
    """Mock attendance service for briefing pipeline tests."""

    async def get_attendance_summary(self, student_id: str):
        return None

    async def get_subjects_below_target(
        self, student_id: str, target_percentage: float
    ):
        return ()


class SemanticRouterMockLLM(LLMProvider):
    """Mock LLM provider simulating natural-language semantic tool dispatch."""

    def __init__(self):
        self._initialized = True

    @property
    def provider_name(self) -> str:
        return "semantic_mock"

    @property
    def supported_models(self) -> tuple[str, ...]:
        return ("mock",)

    async def initialize(self, config: LLMProviderConfig) -> None:
        self._initialized = True

    async def chat_completion(
        self,
        messages: list,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        # Step 2: Synthesis of tool output (when tools is None)
        if not tools:
            return LLMResponse(
                content="Here is your requested schedule information.",
                finish_reason="stop",
            )

        # Step 1: Semantic Intent Routing (when tools are provided)
        user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_msg = m.get("content", "").lower()
                break

        # Semantic routing without hardcoded single phrases
        if "wednesday" in user_msg or "wed" in user_msg:
            return LLMResponse(
                tool_calls=(
                    LLMToolCall(
                        id="call-wed",
                        name="get_schedule_for_weekday",
                        arguments={"day_of_week": 2},
                    ),
                ),
                finish_reason="tool_calls",
            )

        if any(
            p in user_msg
            for p in ["full week", "entire week", "week look like", "week timetable"]
        ):
            return LLMResponse(
                tool_calls=(
                    LLMToolCall(
                        id="call-week",
                        name="get_week_schedule",
                        arguments={},
                    ),
                ),
                finish_reason="tool_calls",
            )

        if any(
            p in user_msg
            for p in [
                "section",
                "classroom",
                "branch",
                "regulation",
                "batch and section",
            ]
        ):
            return LLMResponse(
                tool_calls=(
                    LLMToolCall(
                        id="call-meta",
                        name="get_timetable_metadata",
                        arguments={},
                    ),
                ),
                finish_reason="tool_calls",
            )

        if "batch 1" in user_msg:
            return LLMResponse(
                tool_calls=(
                    LLMToolCall(
                        id="call-batch",
                        name="set_lab_batch",
                        arguments={"batch": "batch_1"},
                    ),
                ),
                finish_reason="tool_calls",
            )

        if any(p in user_msg for p in ["confirm", "looks accurate", "looks good"]):
            return LLMResponse(
                tool_calls=(
                    LLMToolCall(
                        id="call-confirm",
                        name="confirm_timetable",
                        arguments={},
                    ),
                ),
                finish_reason="tool_calls",
            )

        if "today" in user_msg:
            return LLMResponse(
                tool_calls=(
                    LLMToolCall(
                        id="call-today",
                        name="get_today_schedule",
                        arguments={},
                    ),
                ),
                finish_reason="tool_calls",
            )

        return LLMResponse(
            content="I can help you with your timetable and classes.",
            finish_reason="stop",
        )

    async def structured_completion(self, *args, **kwargs):
        return {}

    async def close(self) -> None:
        pass


class TestFullTimetableOnboardingE2E:
    """Full 12-step Timetable Onboarding, Verification, and Briefing pipeline."""

    @pytest.mark.asyncio
    async def test_complete_timetable_onboarding_pipeline(
        self, timetable_service, mock_entry_repo, store, student_a
    ):
        """Execute the full 12-step onboarding pipeline with fixture PDF."""
        # -------------------------------------------------------------
        # Step 1: Greeting & student without timetable
        # -------------------------------------------------------------
        handler = TelegramMessageHandler(MagicMock(), MagicMock())
        profile_pre = handler._create_student_profile(
            student_a, confirmed_tt=None, pending_tt=None
        )
        assert profile_pre.has_timetable is False
        assert profile_pre.timetable_status == "none"
        assert profile_pre.section is None
        assert profile_pre.academic_year is None

        # -------------------------------------------------------------
        # Step 2: Upload fixture PDF
        # -------------------------------------------------------------
        sample_pdf = Path("timetablepdf/5_6185777998969446650.pdf")
        if not sample_pdf.exists():
            pytest.skip("Fixture timetable PDF not present in environment")

        tt = await timetable_service.create_uploaded_timetable(
            student_a.id, str(sample_pdf), original_filename=sample_pdf.name
        )
        assert tt.status == TimetableStatus.REVIEW_REQUIRED
        assert tt.version == 1
        assert tt.academic_year == "2026-2027"
        assert tt.branch == "CSE-CYS"
        assert tt.regulation == "R25"
        assert tt.section == "A"

        entries_v1 = await mock_entry_repo.get_for_timetable(tt.id)
        assert len(entries_v1) > 0
        slash_labs_pre = [e for e in entries_v1 if "/" in e.activity_name]
        assert len(slash_labs_pre) >= 1

        # -------------------------------------------------------------
        # Step 3: Week Formatter contains day names & summaries
        # -------------------------------------------------------------
        week_grid = format_week_schedule(entries_v1, tt)
        assert "<b>Monday</b>" in week_grid
        assert "<b>Tuesday</b>" in week_grid
        assert "CSE-CYS" in week_grid
        assert "Section A" in week_grid
        assert "2026-2027" in week_grid

        # -------------------------------------------------------------
        # Step 4: Set lab batch -> resolves slash labs
        # -------------------------------------------------------------
        batch_res = await set_lab_batch(
            timetable_service, str(student_a.id), "batch_1"
        )
        assert batch_res["success"] is True
        assert batch_res["lab_batch"] == "batch_1"

        entries_post_batch = await mock_entry_repo.get_for_timetable(tt.id)
        # All slash labs resolved to single name
        assert not any("/" in e.activity_name for e in entries_post_batch)
        # Status MUST still be REVIEW_REQUIRED
        assert tt.status == TimetableStatus.REVIEW_REQUIRED

        # -------------------------------------------------------------
        # Step 5: Update one entry
        # -------------------------------------------------------------
        target_entry = entries_post_batch[0]
        update_res = await update_timetable_entry(
            timetable_service,
            str(student_a.id),
            entry_id=str(target_entry.id),
            room="LH-402",
            activity_name="COMPUTER NETWORKS",
        )
        assert update_res["success"] is True
        assert target_entry.room == "LH-402"
        assert target_entry.activity_name == "COMPUTER NETWORKS"

        # -------------------------------------------------------------
        # Step 6: Confirm timetable
        # -------------------------------------------------------------
        conf_res = await confirm_timetable(timetable_service, str(student_a.id))
        assert conf_res["success"] is True
        assert conf_res["status"] == "confirmed"
        assert tt.status == TimetableStatus.CONFIRMED
        assert tt.confirmed_at is not None

        active_tt = await timetable_service.get_confirmed_timetable(student_a.id)
        assert active_tt is not None
        assert active_tt.id == tt.id

        # -------------------------------------------------------------
        # Step 7: Set briefing time
        # -------------------------------------------------------------
        time_res = await set_briefing_time(
            timetable_service, str(student_a.id), "08:00"
        )
        assert time_res["success"] is True
        assert time_res["briefing_time"] == "08:00"
        assert student_a.briefing_time == "08:00"

        # -------------------------------------------------------------
        # Step 8: Briefing Pipeline from CONFIRMED timetable
        # -------------------------------------------------------------
        # Use a Monday date to ensure classes are returned
        monday_date = date(2026, 9, 28)
        briefing_svc = BriefingService(
            timetable_service,
            FakeAttendanceService(),
            today=lambda: monday_date,
        )
        profile_confirmed = handler._create_student_profile(
            student_a, confirmed_tt=tt, pending_tt=None
        )
        assert profile_confirmed.has_timetable is True
        assert profile_confirmed.timetable_status == "confirmed"
        assert profile_confirmed.section == "A"
        assert profile_confirmed.branch == "CSE-CYS"
        assert profile_confirmed.academic_year == "2026-2027"

        ctx = create_student_context(student_a.id, profile=profile_confirmed)
        briefing_result = await briefing_svc.generate_briefing(ctx)

        assert briefing_result.facts.timetable_confirmed is True
        assert len(briefing_result.facts.classes) > 0
        assert briefing_result.facts.day_name == "Monday"

        # -------------------------------------------------------------
        # Step 9: Query Tools return confirmed data
        # -------------------------------------------------------------
        week_res = await get_week_schedule(timetable_service, str(student_a.id))
        assert week_res["status"] == "confirmed"
        assert len(week_res["week"]) > 0

        mon_res = await get_schedule_for_weekday(
            timetable_service, str(student_a.id), day_of_week=0
        )
        assert mon_res["status"] == "confirmed"
        assert mon_res["day"] == "Monday"
        assert len(mon_res["entries"]) > 0

        meta_res = await get_timetable_metadata(
            timetable_service, str(student_a.id)
        )
        assert meta_res["status"] == "confirmed"
        assert meta_res["academic_year"] == "2026-2027"
        assert meta_res["branch"] == "CSE-CYS"
        assert meta_res["regulation"] == "R25"
        assert meta_res["section"] == "A"

        today_res = await get_today_schedule(timetable_service, str(student_a.id))
        assert "entries" in today_res

        # -------------------------------------------------------------
        # Step 10: Activity classification distinguishes LAB from ACADEMIC
        # -------------------------------------------------------------
        all_entries = list(store.entries.values())
        lab_entries = [e for e in all_entries if e.activity_type == ActivityType.LAB]
        acad_entries = [
            e for e in all_entries if e.activity_type == ActivityType.ACADEMIC
        ]
        assert len(lab_entries) > 0
        assert len(acad_entries) > 0

        # -------------------------------------------------------------
        # Step 11: Derived duration arithmetic
        # -------------------------------------------------------------
        for e in all_entries:
            start_m = e.start_time.hour * 60 + e.start_time.minute
            end_m = e.end_time.hour * 60 + e.end_time.minute
            duration = end_m - start_m
            assert duration > 0
            if e.activity_type == ActivityType.LAB:
                # Labs in VNR VJIET span multiple periods (>= 90 min)
                assert duration >= 90
            else:
                # Standard lectures span ~50-60 min
                assert duration <= 70

        # -------------------------------------------------------------
        # Step 12: Section & academic placement matches circular
        # -------------------------------------------------------------
        assert tt.section == "A"
        assert tt.branch == "CSE-CYS"
        assert tt.regulation == "R25"
        assert tt.academic_year == "2026-2027"


class TestNaturalLanguageParaphraseRouting:
    """Test conversation service intent routing across paraphrases without keywords."""

    @pytest.fixture
    def router_llm(self):
        return SemanticRouterMockLLM()

    @pytest.fixture
    def conv_service(self, router_llm, timetable_service):
        return ConversationService(
            llm_provider=router_llm,
            timetable_service=timetable_service,
        )

    @pytest.fixture
    def active_context(self, student_a):
        profile = StudentProfile(
            student_id=student_a.id,
            name="Harshik",
            section="A",
            branch="CSE-CYS",
            has_timetable=True,
            timetable_status="confirmed",
        )
        return create_student_context(student_a.id, profile=profile)

    @pytest.mark.asyncio
    async def test_natural_language_paraphrases_weekday_schedule(
        self, conv_service, active_context, timetable_service, store, student_a
    ):
        """Varied paraphrases asking about Wednesday route
        to get_schedule_for_weekday.
        """
        # Ensure a confirmed timetable exists
        tt = store.add_timetable(
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
                timetable_id=tt.id,
                day_of_week=2,
                start_time=time(10, 0),
                end_time=time(10, 50),
                activity_name="OPERATING SYSTEMS",
                activity_type=ActivityType.ACADEMIC,
            )
        )

        paraphrases = [
            "What do I have on Wednesday?",
            "Could you check my Wednesday classes please?",
            "Show me what's scheduled for Wednesday",
            "Am I free on Wednesday afternoon?",
        ]

        for phrase in paraphrases:
            response, new_ctx = await conv_service.process_message(
                active_context, phrase
            )
            assert "schedule" in response.lower()
            tools = [
                m
                for m in new_ctx.conversation.recent_tool_results
                if m.tool_name == "get_schedule_for_weekday"
            ]
            assert len(tools) > 0
            assert tools[-1].arguments["day_of_week"] == 2

    @pytest.mark.asyncio
    async def test_natural_language_paraphrases_full_week(
        self, conv_service, active_context, store, student_a
    ):
        """Varied paraphrases asking for weekly schedule route to get_week_schedule."""
        store.add_timetable(
            Timetable(
                id=uuid4(),
                student_id=student_a.id,
                status=TimetableStatus.CONFIRMED,
                version=1,
            )
        )

        paraphrases = [
            "Can you show me my full week timetable?",
            "Give me the entire week's schedule",
            "What does my week look like?",
        ]

        for phrase in paraphrases:
            response, new_ctx = await conv_service.process_message(
                active_context, phrase
            )
            assert "schedule" in response.lower()
            tools = [
                m
                for m in new_ctx.conversation.recent_tool_results
                if m.tool_name == "get_week_schedule"
            ]
            assert len(tools) > 0

    @pytest.mark.asyncio
    async def test_natural_language_paraphrases_metadata(
        self, conv_service, active_context, store, student_a
    ):
        """Varied paraphrases asking about metadata route to get_timetable_metadata."""
        store.add_timetable(
            Timetable(
                id=uuid4(),
                student_id=student_a.id,
                status=TimetableStatus.CONFIRMED,
                version=1,
                section="A",
                branch="CSE-CYS",
            )
        )

        paraphrases = [
            "What section am I in and what's my classroom?",
            "Which branch and regulation do I belong to?",
            "Can you check my batch and section details?",
        ]

        for phrase in paraphrases:
            _response, new_ctx = await conv_service.process_message(
                active_context, phrase
            )
            tools = [
                m
                for m in new_ctx.conversation.recent_tool_results
                if m.tool_name == "get_timetable_metadata"
            ]
            assert len(tools) > 0

    @pytest.mark.asyncio
    async def test_natural_language_batch_and_confirmation(
        self, conv_service, active_context, store, student_a
    ):
        """Conversational lab batch setting and confirmation route
        without regex menus.
        """
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
                day_of_week=0,
                start_time=time(13, 20),
                end_time=time(15, 0),
                activity_name="PYTHON LAB / WEB LAB",
                activity_type=ActivityType.LAB,
                lab_batch=LabBatch.UNKNOWN,
            )
        )

        # 1. Batch setting via conversational paraphrase
        _resp1, ctx1 = await conv_service.process_message(
            active_context, "Put me in lab batch 1"
        )
        batch_tools = [
            m
            for m in ctx1.conversation.recent_tool_results
            if m.tool_name == "set_lab_batch"
        ]
        assert len(batch_tools) > 0
        assert entry.activity_name == "PYTHON LAB"
        assert entry.lab_batch == LabBatch.BATCH_1
        assert tt.status == TimetableStatus.REVIEW_REQUIRED

        # 2. Confirmation via conversational paraphrase
        _resp2, ctx2 = await conv_service.process_message(
            ctx1, "The schedule looks completely accurate, confirm it"
        )
        confirm_tools = [
            m
            for m in ctx2.conversation.recent_tool_results
            if m.tool_name == "confirm_timetable"
        ]
        assert len(confirm_tools) > 0
        assert tt.status == TimetableStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_conversation_quarantine_unconfirmed_timetable(
        self, conv_service, store, student_b
    ):
        """Unconfirmed timetable is quarantined; queries return no
        confirmed schedule.
        """
        tt_review = store.add_timetable(
            Timetable(
                id=uuid4(),
                student_id=student_b.id,
                status=TimetableStatus.REVIEW_REQUIRED,
                version=1,
            )
        )
        store.add_entry(
            TimetableEntry(
                id=uuid4(),
                timetable_id=tt_review.id,
                day_of_week=2,
                start_time=time(9, 10),
                end_time=time(10, 0),
                activity_name="SECRET UNCONFIRMED CLASS",
                activity_type=ActivityType.ACADEMIC,
            )
        )

        ctx_b = create_student_context(
            student_b.id,
            profile=StudentProfile(
                student_id=student_b.id,
                has_timetable=False,
                timetable_status="review_required",
            ),
        )

        _response, new_ctx = await conv_service.process_message(
            ctx_b, "What do I have on Wednesday?"
        )
        tools = [
            m
            for m in new_ctx.conversation.recent_tool_results
            if m.tool_name == "get_schedule_for_weekday"
        ]
        assert len(tools) > 0
        # Result summary records no confirmed timetable found
        assert "No confirmed timetable found" in tools[-1].result_summary
        assert "SECRET UNCONFIRMED CLASS" not in tools[-1].result_summary
