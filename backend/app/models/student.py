import enum

from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class StudentStatus(str, enum.Enum):  # noqa: UP042
    ACTIVE = "active"
    INACTIVE = "inactive"


class Student(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "students"

    status: Mapped[StudentStatus] = mapped_column(
        SQLEnum(StudentStatus, name="student_status", native_enum=False),
        default=StudentStatus.ACTIVE,
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Student(id={self.id}, status={self.status})>"
