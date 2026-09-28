import enum
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.timetable import LabBatch

if TYPE_CHECKING:
    from app.models.attendance import AttendanceSnapshot
    from app.models.timetable import Timetable


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

    lab_batch: Mapped[LabBatch] = mapped_column(
        SQLEnum(LabBatch, name="lab_batch", native_enum=False),
        default=LabBatch.UNKNOWN,
        nullable=False,
    )

    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attendance_target: Mapped[float | None] = mapped_column(Float, nullable=True)

    briefing_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(50), default="Asia/Kolkata", nullable=False
    )

    timetables: Mapped[list["Timetable"]] = relationship(
        "Timetable", back_populates="student", cascade="all, delete-orphan"
    )

    attendance_snapshots: Mapped[list["AttendanceSnapshot"]] = relationship(
        "AttendanceSnapshot", back_populates="student", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Student(id={self.id}, status={self.status}, lab_batch={self.lab_batch})>"
        )
