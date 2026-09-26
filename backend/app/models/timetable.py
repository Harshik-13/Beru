import enum
import uuid
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
)
from sqlalchemy import (
    Enum as SQLEnum,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.student import Student


class TimetableStatus(str, enum.Enum):  # noqa: UP042
    UPLOADED = "uploaded"
    EXTRACTING = "extracting"
    REVIEW_REQUIRED = "review_required"
    CONFIRMED = "confirmed"
    ARCHIVED = "archived"
    FAILED = "failed"


class ActivityType(str, enum.Enum):  # noqa: UP042
    ACADEMIC = "academic"
    LAB = "lab"
    BREAK = "break"
    ACTIVITY = "activity"


class LabBatch(str, enum.Enum):  # noqa: UP042
    UNKNOWN = "unknown"
    BATCH_1 = "batch_1"
    BATCH_2 = "batch_2"


class Timetable(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "timetables"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )

    academic_year: Mapped[str | None] = mapped_column(String(20), nullable=True)
    regulation: Mapped[str | None] = mapped_column(String(50), nullable=True)
    programme: Mapped[str | None] = mapped_column(String(100), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(100), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String(10), nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    default_classroom: Mapped[str | None] = mapped_column(String(100), nullable=True)

    status: Mapped[TimetableStatus] = mapped_column(
        SQLEnum(TimetableStatus, name="timetable_status", native_enum=False),
        default=TimetableStatus.UPLOADED,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    student: Mapped["Student"] = relationship("Student", back_populates="timetables")
    entries: Mapped[list["TimetableEntry"]] = relationship(
        "TimetableEntry", back_populates="timetable", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_timetables_student_id", "student_id"),
        Index("ix_timetables_student_id_status", "student_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Timetable(id={self.id}, student_id={self.student_id}, "
            f"status={self.status}, version={self.version})>"
        )


class TimetableEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "timetable_entries"

    timetable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("timetables.id", ondelete="CASCADE"),
        nullable=False,
    )

    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Mon, 6=Sun
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    activity_name: Mapped[str] = mapped_column(String(200), nullable=False)
    activity_type: Mapped[ActivityType] = mapped_column(
        SQLEnum(ActivityType, name="activity_type", native_enum=False),
        nullable=False,
    )

    course_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    room: Mapped[str | None] = mapped_column(String(50), nullable=True)
    faculty: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # For slash-separated labs: which batch this entry belongs to
    lab_batch: Mapped[LabBatch | None] = mapped_column(
        SQLEnum(LabBatch, name="lab_batch", native_enum=False),
        nullable=True,
    )

    # Extraction metadata
    extraction_confidence: Mapped[float | None] = mapped_column(nullable=True)
    extraction_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    timetable: Mapped["Timetable"] = relationship("Timetable", back_populates="entries")

    __table_args__ = (
        Index("ix_timetable_entries_timetable_id", "timetable_id"),
        Index("ix_timetable_entries_timetable_id_day", "timetable_id", "day_of_week"),
    )

    def __repr__(self) -> str:
        return (
            f"<TimetableEntry(timetable_id={self.timetable_id}, "
            f"day={self.day_of_week}, {self.start_time}-{self.end_time}, "
            f"{self.activity_name})>"
        )
