import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.student import Student


class AttendanceSource(str, enum.Enum):  # noqa: UP042
    DOCTUS = "doctus"


class AttendanceSnapshot(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "attendance_snapshots"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )

    source: Mapped[AttendanceSource] = mapped_column(
        SQLEnum(AttendanceSource, name="attendance_source", native_enum=False),
        nullable=False,
    )

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    semester_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    overall_attended: Mapped[int] = mapped_column(Integer, nullable=False)
    overall_conducted: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    student: Mapped["Student"] = relationship(
        "Student", back_populates="attendance_snapshots"
    )
    subjects: Mapped[list["SubjectAttendance"]] = relationship(
        "SubjectAttendance",
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("overall_attended >= 0", name="ck_attendance_attended_nonneg"),
        CheckConstraint(
            "overall_conducted >= 0", name="ck_attendance_conducted_nonneg"
        ),
        CheckConstraint(
            "overall_attended <= overall_conducted",
            name="ck_attendance_attended_le_conducted",
        ),
        Index("ix_attendance_snapshots_student_id", "student_id"),
        Index(
            "ix_attendance_snapshots_student_id_captured_at",
            "student_id",
            "captured_at",
        ),
    )

    def overall_percentage(self) -> float:
        """Calculate overall attendance percentage from counts."""
        if self.overall_conducted == 0:
            return 0.0
        return (self.overall_attended / self.overall_conducted) * 100.0

    def __repr__(self) -> str:
        return (
            f"<AttendanceSnapshot(id={self.id}, student_id={self.student_id}, "
            f"overall={self.overall_attended}/{self.overall_conducted}, "
            f"captured_at={self.captured_at})>"
        )


class SubjectAttendance(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "subject_attendance"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_snapshots.id", ondelete="CASCADE"),
        nullable=False,
    )

    subject_code: Mapped[str] = mapped_column(String(20), nullable=False)

    # Optional - portal may not provide subject name
    subject_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Optional monthly data - portal may not provide
    monthly_period: Mapped[str | None] = mapped_column(String(20), nullable=True)
    monthly_attended: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_conducted: Mapped[int | None] = mapped_column(Integer, nullable=True)

    cumulative_attended: Mapped[int] = mapped_column(Integer, nullable=False)
    cumulative_conducted: Mapped[int] = mapped_column(Integer, nullable=False)

    # Relationships
    snapshot: Mapped["AttendanceSnapshot"] = relationship(
        "AttendanceSnapshot", back_populates="subjects"
    )

    __table_args__ = (
        CheckConstraint("cumulative_attended >= 0", name="ck_subj_cum_attended_nonneg"),
        CheckConstraint(
            "cumulative_conducted >= 0", name="ck_subj_cum_conducted_nonneg"
        ),
        CheckConstraint(
            "cumulative_attended <= cumulative_conducted",
            name="ck_subj_cum_attended_le_conducted",
        ),
        CheckConstraint(
            "monthly_attended IS NULL OR monthly_attended >= 0",
            name="ck_subj_monthly_attended_nonneg",
        ),
        CheckConstraint(
            "monthly_conducted IS NULL OR monthly_conducted >= 0",
            name="ck_subj_monthly_conducted_nonneg",
        ),
        CheckConstraint(
            "monthly_attended IS NULL OR monthly_conducted IS NULL OR "
            "monthly_attended <= monthly_conducted",
            name="ck_subj_monthly_attended_le_conducted",
        ),
        Index("ix_subject_attendance_snapshot_id", "snapshot_id"),
        Index(
            "ix_subject_attendance_snapshot_id_subject_code",
            "snapshot_id",
            "subject_code",
        ),
    )

    def cumulative_percentage(self) -> float:
        """Calculate cumulative attendance percentage from counts."""
        if self.cumulative_conducted == 0:
            return 0.0
        return (self.cumulative_attended / self.cumulative_conducted) * 100.0

    def monthly_percentage(self) -> float | None:
        """Calculate monthly attendance percentage from counts if available."""
        if self.monthly_conducted is None:
            return None
        if self.monthly_conducted == 0:
            return 0.0
        if self.monthly_attended is None:
            return None
        return (self.monthly_attended / self.monthly_conducted) * 100.0

    def __repr__(self) -> str:
        return (
            f"<SubjectAttendance(id={self.id}, snapshot_id={self.snapshot_id}, "
            f"subject_code={self.subject_code}, "
            f"cumulative={self.cumulative_attended}/{self.cumulative_conducted})>"
        )
