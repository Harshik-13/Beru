from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.timetable import Timetable, TimetableEntry, TimetableStatus


class TimetableRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, timetable: Timetable) -> Timetable:
        self.session.add(timetable)
        await self.session.flush()
        await self.session.refresh(timetable)
        return timetable

    async def get_by_id(self, timetable_id: UUID) -> Timetable | None:
        result = await self.session.execute(
            select(Timetable).where(Timetable.id == timetable_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_entries(self, timetable_id: UUID) -> Timetable | None:
        result = await self.session.execute(
            select(Timetable)
            .where(Timetable.id == timetable_id)
            .options(selectinload(Timetable.entries))
        )
        return result.scalar_one_or_none()

    async def get_latest_for_student(
        self, student_id: UUID, status: TimetableStatus | None = None
    ) -> Timetable | None:
        query = select(Timetable).where(Timetable.student_id == student_id)
        if status:
            query = query.where(Timetable.status == status)
        query = query.order_by(Timetable.version.desc()).limit(1)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_confirmed_for_student(self, student_id: UUID) -> Timetable | None:
        return await self.get_latest_for_student(student_id, TimetableStatus.CONFIRMED)

    async def get_pending_for_student(self, student_id: UUID) -> Timetable | None:
        """Get the latest non-confirmed timetable for a student (for review)."""
        query = (
            select(Timetable)
            .where(
                Timetable.student_id == student_id,
                Timetable.status.in_(
                    [
                        TimetableStatus.UPLOADED,
                        TimetableStatus.EXTRACTING,
                        TimetableStatus.REVIEW_REQUIRED,
                        TimetableStatus.FAILED,
                    ]
                ),
            )
            .order_by(Timetable.version.desc())
            .limit(1)
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def archive_previous_confirmed(self, student_id: UUID) -> None:
        """Archive the previously confirmed timetable for a student."""
        await self.session.execute(
            update(Timetable)
            .where(
                Timetable.student_id == student_id,
                Timetable.status == TimetableStatus.CONFIRMED,
            )
            .values(status=TimetableStatus.ARCHIVED)
        )


class TimetableEntryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, entry: TimetableEntry) -> TimetableEntry:
        self.session.add(entry)
        await self.session.flush()
        await self.session.refresh(entry)
        return entry

    async def create_batch(self, entries: list[TimetableEntry]) -> list[TimetableEntry]:
        self.session.add_all(entries)
        await self.session.flush()
        for entry in entries:
            await self.session.refresh(entry)
        return entries

    async def get_for_timetable(self, timetable_id: UUID) -> list[TimetableEntry]:
        result = await self.session.execute(
            select(TimetableEntry)
            .where(TimetableEntry.timetable_id == timetable_id)
            .order_by(TimetableEntry.day_of_week, TimetableEntry.start_time)
        )
        return list(result.scalars().all())

    async def delete_for_timetable(self, timetable_id: UUID) -> None:
        await self.session.execute(
            delete(TimetableEntry).where(TimetableEntry.timetable_id == timetable_id)
        )
