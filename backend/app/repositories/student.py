from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student import Student, StudentStatus


class StudentRepository:
    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, *, status: str = "active") -> Student:
        student = Student(status=status)
        self._session.add(student)
        await self._session.flush()
        return student

    async def get_by_id(self, student_id: UUID) -> Student | None:
        result = await self._session.execute(
            select(Student).where(Student.id == student_id)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, student_id: UUID) -> Student:
        student = await self.get_by_id(student_id)
        if student is None:
            student = Student(id=student_id)
            self._session.add(student)
            await self._session.flush()
        return student

    async def get_active_students(self) -> list[Student]:
        """Get all active students."""
        result = await self._session.execute(
            select(Student).where(Student.status == StudentStatus.ACTIVE)
        )
        return list(result.scalars().all())

    async def update_profile(
        self,
        student_id: UUID,
        *,
        name: str | None = None,
        attendance_target: float | None = None,
    ) -> Student | None:
        """Update student profile fields. Only updates provided fields."""
        student = await self.get_by_id(student_id)
        if student is None:
            return None

        if name is not None:
            student.name = name
        if attendance_target is not None:
            if not 0.0 <= attendance_target <= 100.0:
                raise ValueError("attendance_target must be between 0 and 100")
            student.attendance_target = attendance_target

        await self._session.flush()
        return student
