from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.student import Student


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
