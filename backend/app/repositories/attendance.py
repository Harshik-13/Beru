from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.attendance import AttendanceSnapshot, SubjectAttendance


class AttendanceSnapshotRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, snapshot: AttendanceSnapshot) -> AttendanceSnapshot:
        self.session.add(snapshot)
        await self.session.flush()
        await self.session.refresh(snapshot)
        return snapshot

    async def get_by_id(self, snapshot_id: UUID) -> AttendanceSnapshot | None:
        result = await self.session.execute(
            select(AttendanceSnapshot).where(AttendanceSnapshot.id == snapshot_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_subjects(
        self, snapshot_id: UUID
    ) -> AttendanceSnapshot | None:
        result = await self.session.execute(
            select(AttendanceSnapshot)
            .where(AttendanceSnapshot.id == snapshot_id)
            .options(selectinload(AttendanceSnapshot.subjects))
        )
        return result.scalar_one_or_none()

    async def get_latest_for_student(
        self, student_id: UUID
    ) -> AttendanceSnapshot | None:
        result = await self.session.execute(
            select(AttendanceSnapshot)
            .where(AttendanceSnapshot.student_id == student_id)
            .order_by(desc(AttendanceSnapshot.captured_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_for_student_with_subjects(
        self, student_id: UUID
    ) -> AttendanceSnapshot | None:
        result = await self.session.execute(
            select(AttendanceSnapshot)
            .where(AttendanceSnapshot.student_id == student_id)
            .order_by(desc(AttendanceSnapshot.captured_at))
            .limit(1)
            .options(selectinload(AttendanceSnapshot.subjects))
        )
        return result.scalar_one_or_none()

    async def get_all_for_student(
        self, student_id: UUID, limit: int = 50
    ) -> list[AttendanceSnapshot]:
        result = await self.session.execute(
            select(AttendanceSnapshot)
            .where(AttendanceSnapshot.student_id == student_id)
            .order_by(desc(AttendanceSnapshot.captured_at))
            .limit(limit)
        )
        return list(result.scalars().all())


class SubjectAttendanceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, subject: SubjectAttendance) -> SubjectAttendance:
        self.session.add(subject)
        await self.session.flush()
        await self.session.refresh(subject)
        return subject

    async def create_batch(
        self, subjects: list[SubjectAttendance]
    ) -> list[SubjectAttendance]:
        self.session.add_all(subjects)
        await self.session.flush()
        for subject in subjects:
            await self.session.refresh(subject)
        return subjects

    async def get_for_snapshot(self, snapshot_id: UUID) -> list[SubjectAttendance]:
        result = await self.session.execute(
            select(SubjectAttendance)
            .where(SubjectAttendance.snapshot_id == snapshot_id)
            .order_by(SubjectAttendance.subject_code)
        )
        return list(result.scalars().all())
