"""
Timetable service - core business logic for timetable pipeline.

Handles:
- Timetable state machine (UPLOADED -> EXTRACTING -> REVIEW_REQUIRED ->
  CONFIRMED -> ARCHIVED)
- Extraction coordination
- Lab batch resolution
- Confirmation flow
- Schedule queries (deterministic)
"""

from contextlib import suppress
from datetime import date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.intelligence.services.timetable_extraction import (
    ExtractedCell,
    cell_to_entry,
    create_timetable_extractor,
)
from app.models.timetable import (
    ActivityType,
    LabBatch,
    Timetable,
    TimetableEntry,
    TimetableStatus,
)
from app.repositories.student import StudentRepository
from app.repositories.timetable import TimetableEntryRepository, TimetableRepository


class TimetableStateError(Exception):
    """Raised when an invalid state transition is attempted."""

    pass


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]


def format_week_schedule(
    entries: list["TimetableEntry"],
    metadata: "Timetable | None" = None,
) -> str:
    """Format timetable entries as a weekday grid for review display."""
    lines: list[str] = []

    if metadata:
        header_parts: list[str] = []
        if metadata.programme:
            header_parts.append(metadata.programme)
        if metadata.branch:
            header_parts.append(metadata.branch)
        if metadata.semester:
            header_parts.append(f"Semester {metadata.semester}")
        if metadata.section:
            header_parts.append(f"Section {metadata.section}")
        if metadata.academic_year:
            header_parts.append(metadata.academic_year)
        if header_parts:
            lines.append(" | ".join(header_parts))
        if metadata.default_classroom:
            lines.append(f"Default Classroom: {metadata.default_classroom}")
        lines.append("")

    for day_idx, day_name in enumerate(DAY_NAMES):
        day_entries = [e for e in entries if e.day_of_week == day_idx]
        if not day_entries:
            continue

        lines.append(f"<b>{day_name}</b>")
        for entry in sorted(day_entries, key=lambda e: e.start_time):
            time_str = f"{entry.start_time.strftime('%H:%M')}-{entry.end_time.strftime('%H:%M')}"
            type_label = ""
            if entry.activity_type == ActivityType.LAB:
                type_label = " [LAB]"
            elif entry.activity_type == ActivityType.BREAK:
                type_label = " [BREAK]"
            elif entry.activity_type == ActivityType.ACTIVITY:
                type_label = " [ACTIVITY]"

            room_str = f" @ {entry.room}" if entry.room else ""
            lines.append(f"  {time_str} {entry.activity_name}{type_label}{room_str}")
        lines.append("")

    return "\n".join(lines)


class TimetableService:
    """
    Service for managing timetable lifecycle.

    Enforces state machine, ownership, and confirmation flow.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.timetable_repo = TimetableRepository(session)
        self.entry_repo = TimetableEntryRepository(session)
        self.student_repo = StudentRepository(session)

    async def create_uploaded_timetable(
        self,
        student_id: UUID,
        file_path: str,
        original_filename: str,
    ) -> Timetable:
        """
        Create a new timetable in UPLOADED state and start extraction.
        """
        # Check latest version for student
        latest = await self.timetable_repo.get_latest_for_student(student_id)
        version = (latest.version + 1) if latest else 1

        # Create timetable record
        timetable = Timetable(
            student_id=student_id,
            status=TimetableStatus.UPLOADED,
            version=version,
        )
        await self.timetable_repo.create(timetable)

        # Start extraction
        return await self.extract_timetable(timetable.id, file_path)

    async def extract_timetable(self, timetable_id: UUID, file_path: str) -> Timetable:
        """
        Extract timetable data from file.

        Updates timetable to EXTRACTING, then REVIEW_REQUIRED or FAILED.
        """
        timetable = await self.timetable_repo.get_by_id(timetable_id)
        if not timetable:
            raise ValueError(f"Timetable not found: {timetable_id}")

        if timetable.status not in (
            TimetableStatus.UPLOADED,
            TimetableStatus.FAILED,
        ):
            raise TimetableStateError(
                f"Cannot extract timetable in status: {timetable.status}"
            )

        timetable.status = TimetableStatus.EXTRACTING
        await self.session.flush()

        extractor = create_timetable_extractor()
        result = await extractor.extract(file_path)

        if result.errors:
            timetable.status = TimetableStatus.FAILED
            await self.session.flush()
            return timetable

        # Populate metadata
        meta = result.metadata
        timetable.academic_year = meta.academic_year
        timetable.regulation = meta.regulation
        timetable.programme = meta.programme
        timetable.branch = meta.branch
        timetable.year = meta.year
        timetable.semester = meta.semester
        timetable.section = meta.section
        if meta.effective_from:
            with suppress(ValueError):
                timetable.effective_from = date.fromisoformat(meta.effective_from)
        timetable.default_classroom = meta.default_classroom

        # Clear any existing entries
        await self.entry_repo.delete_for_timetable(timetable_id)

        # Process cells into entries
        entries = []
        for cell in result.cells:
            entry = cell_to_entry(cell)
            entry.timetable_id = timetable_id
            # Map course_metadata onto entry if available
            content_key = cell.content.strip().split()[0] if cell.content.strip() else ""
            if content_key in meta.course_metadata:
                course_info = meta.course_metadata[content_key]
                entry.course_code = content_key
                if course_info.get("faculty"):
                    entry.faculty = course_info["faculty"]
            entries.append(entry)

        # Handle slash labs - store as ambiguous for now, will resolve on confirmation
        for slash_lab in result.slash_labs:
            entry = cell_to_entry(
                ExtractedCell(
                    day_of_week=slash_lab.day_of_week,
                    start_period=slash_lab.start_period,
                    end_period=slash_lab.end_period,
                    content=slash_lab.raw_content,
                    confidence=slash_lab.confidence,
                )
            )
            entry.timetable_id = timetable_id
            entries.append(entry)

        if entries:
            await self.entry_repo.create_batch(entries)

        timetable.status = TimetableStatus.REVIEW_REQUIRED
        await self.session.flush()
        return timetable

    async def get_pending_timetable(self, student_id: UUID) -> Timetable | None:
        """Get the timetable pending review for a student."""
        return await self.timetable_repo.get_pending_for_student(student_id)

    async def get_pending_timetable_with_entries(
        self, student_id: UUID
    ) -> tuple[Timetable | None, list[TimetableEntry]]:
        """Get the pending timetable with its entries for review display."""
        pending = await self.timetable_repo.get_pending_for_student(student_id)
        if not pending:
            return None, []
        entries = await self.entry_repo.get_for_timetable(pending.id)
        return pending, entries

    async def confirm_timetable(self, timetable_id: UUID) -> Timetable:
        """
        Confirm a timetable - makes it the active CONFIRMED timetable.

        Archives previous confirmed timetable for the student.
        """
        timetable = await self.timetable_repo.get_by_id_with_entries(timetable_id)
        if not timetable:
            raise ValueError(f"Timetable not found: {timetable_id}")

        if timetable.status != TimetableStatus.REVIEW_REQUIRED:
            raise TimetableStateError(
                "Can only confirm timetable in REVIEW_REQUIRED status, "
                f"got: {timetable.status}"
            )

        # Resolve slash labs based on student's lab_batch
        student = await self.student_repo.get_by_id(timetable.student_id)
        if not student:
            raise ValueError("Student not found")

        for entry in timetable.entries:
            if (
                entry.lab_batch is None or entry.lab_batch == LabBatch.UNKNOWN
            ) and "/" in entry.activity_name:
                parts = [p.strip() for p in entry.activity_name.split("/")]
                if len(parts) == 2:
                    if student.lab_batch == LabBatch.BATCH_1:
                        entry.activity_name = parts[0]
                    elif student.lab_batch == LabBatch.BATCH_2:
                        entry.activity_name = parts[1]
                    if "lab" in entry.activity_name.lower():
                        entry.activity_type = ActivityType.LAB
                    entry.lab_batch = student.lab_batch

        # Archive previous confirmed timetable
        await self.timetable_repo.archive_previous_confirmed(timetable.student_id)

        # Confirm this one
        timetable.status = TimetableStatus.CONFIRMED
        tz = timetable.confirmed_at.tzinfo if timetable.confirmed_at else None
        timetable.confirmed_at = datetime.now(tz)

        await self.session.flush()
        return timetable

    async def set_lab_batch(self, student_id: UUID, lab_batch: LabBatch) -> None:
        """Set the student's lab batch."""
        student = await self.student_repo.get_by_id(student_id)
        if not student:
            raise ValueError("Student not found")
        student.lab_batch = lab_batch
        await self.session.flush()

    async def get_student_lab_batch(self, student_id: UUID) -> LabBatch:
        """Get the student's lab batch."""
        student = await self.student_repo.get_by_id(student_id)
        if not student:
            raise ValueError("Student not found")
        return student.lab_batch

    async def needs_lab_batch(self, student_id: UUID) -> bool:
        """Check if student needs to provide lab batch (has slash labs pending)."""
        student = await self.student_repo.get_by_id(student_id)
        if not student:
            return False
        if student.lab_batch != LabBatch.UNKNOWN:
            return False

        # Check if there's a pending timetable with slash labs
        pending = await self.timetable_repo.get_pending_for_student(student_id)
        if not pending:
            return False

        entries = await self.entry_repo.get_for_timetable(pending.id)
        return any("/" in e.activity_name for e in entries)

    # ===== Schedule Query Methods (deterministic) =====

    async def get_confirmed_timetable(self, student_id: UUID) -> Timetable | None:
        """Get the confirmed timetable for a student."""
        return await self.timetable_repo.get_confirmed_for_student(student_id)

    async def get_schedule_for_date(
        self, student_id: UUID, target_date: date
    ) -> list[TimetableEntry]:
        """Get schedule for a specific date."""
        timetable = await self.get_confirmed_timetable(student_id)
        if not timetable:
            return []

        day_of_week = target_date.weekday()  # 0=Monday, 5=Saturday, 6=Sunday
        if day_of_week == 6:  # Sunday (no classes)
            return []

        entries = await self.entry_repo.get_for_timetable(timetable.id)
        return [e for e in entries if e.day_of_week == day_of_week]

    async def get_today_schedule(self, student_id: UUID) -> list[TimetableEntry]:
        """Get today's schedule."""
        return await self.get_schedule_for_date(student_id, date.today())

    async def get_tomorrow_schedule(self, student_id: UUID) -> list[TimetableEntry]:
        """Get tomorrow's schedule."""
        return await self.get_schedule_for_date(
            student_id, date.today() + timedelta(days=1)
        )

    async def get_next_class(
        self, student_id: UUID, from_time: time | None = None
    ) -> TimetableEntry | None:
        """Get the next class from a given time (defaults to now)."""
        today = date.today()
        day_of_week = today.weekday()
        if day_of_week == 6:  # Sunday
            return None

        timetable = await self.get_confirmed_timetable(student_id)
        if not timetable:
            return None

        entries = await self.entry_repo.get_for_timetable(timetable.id)
        day_entries = [e for e in entries if e.day_of_week == day_of_week]

        if not day_entries:
            return None

        current_time = from_time or datetime.now().time()

        # Find first class after current time
        future_entries = [e for e in day_entries if e.start_time > current_time]
        if future_entries:
            return min(future_entries, key=lambda e: e.start_time)

        # If no future class today, return first class tomorrow
        tomorrow_entries = await self.get_tomorrow_schedule(student_id)
        if tomorrow_entries:
            return min(tomorrow_entries, key=lambda e: e.start_time)

        return None

    async def get_first_class_of_day(
        self, student_id: UUID, target_date: date
    ) -> TimetableEntry | None:
        """Get the first class of a specific day."""
        schedule = await self.get_schedule_for_date(student_id, target_date)
        if not schedule:
            return None
        return min(schedule, key=lambda e: e.start_time)

    async def update_entry(
        self, timetable_id: UUID, entry_id: UUID, **updates
    ) -> TimetableEntry | None:
        """
        Update a timetable entry (for corrections before confirmation).

        Only allowed for timetables in REVIEW_REQUIRED state.
        """
        timetable = await self.timetable_repo.get_by_id_with_entries(timetable_id)
        if not timetable:
            raise ValueError("Timetable not found")

        if timetable.status != TimetableStatus.REVIEW_REQUIRED:
            raise TimetableStateError(
                f"Cannot modify timetable in {timetable.status} state"
            )

        # Find and update entry
        result = await self.session.execute(
            select(TimetableEntry).where(TimetableEntry.id == entry_id)
        )
        entry = result.scalar_one_or_none()
        if not entry or entry.timetable_id != timetable_id:
            return None

        for key, value in updates.items():
            if hasattr(entry, key):
                setattr(entry, key, value)

        await self.session.flush()
        return entry

    async def count_classes_for_subject_on_date(
        self, student_id: UUID, subject_code: str, target_date: date
    ) -> int:
        """
        Count the number of classes for a subject on a specific date.

        Only uses CONFIRMED timetable.
        """
        timetable = await self.get_confirmed_timetable(student_id)
        if not timetable:
            return 0

        day_of_week = target_date.weekday()  # 0=Monday, 5=Saturday, 6=Sunday
        if day_of_week == 6:  # Sunday (no classes)
            return 0

        entries = await self.entry_repo.get_for_timetable(timetable.id)
        day_entries = [e for e in entries if e.day_of_week == day_of_week]

        count = 0
        for entry in day_entries:
            if subject_code.lower() in entry.activity_name.lower():
                count += 1

        return count
