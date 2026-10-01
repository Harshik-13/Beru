"""
Attendance service - deterministic business logic for attendance calculations.

All arithmetic is deterministic and performed in the backend.
The LLM never performs attendance arithmetic.
"""

from dataclasses import dataclass
from datetime import date, datetime
from math import ceil

from sqlalchemy import desc, select
from sqlalchemy.orm import selectinload


@dataclass(frozen=True, slots=True)
class OverallAttendanceResult:
    """Result for overall attendance query."""

    attended: int
    conducted: int
    percentage: float
    captured_at: datetime
    source: str
    semester_id: str | None
    provenance: str = "portal_snapshot_fresh"
    notice: str | None = None

    def to_dict(self):
        return {
            "attended": self.attended,
            "conducted": self.conducted,
            "percentage": self.percentage,
            "cumulative_attended": self.attended,
            "cumulative_conducted": self.conducted,
            "cumulative_percentage": self.percentage,
            "captured_at": self.captured_at.isoformat()
            if hasattr(self.captured_at, "isoformat")
            else str(self.captured_at),
            "source": self.source,
            "semester_id": self.semester_id,
            "provenance": self.provenance,
            "notice": self.notice,
        }


@dataclass(frozen=True, slots=True)
class SubjectAttendanceResult:
    """Result for subject attendance query."""

    subject_code: str
    subject_name: str | None
    monthly_attended: int | None
    monthly_conducted: int | None
    monthly_percentage: float | None
    monthly_period: str | None
    cumulative_attended: int
    cumulative_conducted: int
    cumulative_percentage: float

    def to_dict(self):
        return {
            "subject_code": self.subject_code,
            "subject_name": self.subject_name,
            "monthly_attended": self.monthly_attended,
            "monthly_conducted": self.monthly_conducted,
            "monthly_percentage": self.monthly_percentage,
            "monthly_period": self.monthly_period,
            "cumulative_attended": self.cumulative_attended,
            "cumulative_conducted": self.cumulative_conducted,
            "cumulative_percentage": self.cumulative_percentage,
        }


@dataclass(frozen=True, slots=True)
class AttendanceSummaryResult:
    """Complete attendance summary for a student."""

    overall: OverallAttendanceResult
    subjects: tuple[SubjectAttendanceResult, ...]
    captured_at: datetime
    source: str
    semester_id: str | None
    provenance: str = "portal_snapshot_fresh"
    notice: str | None = None

    def to_dict(self):
        return {
            "overall": self.overall.to_dict()
            if hasattr(self.overall, "to_dict")
            else self.overall,
            "subjects": [
                s.to_dict() if hasattr(s, "to_dict") else s for s in self.subjects
            ],
            "captured_at": self.captured_at.isoformat()
            if hasattr(self.captured_at, "isoformat")
            else str(self.captured_at),
            "source": self.source,
            "semester_id": self.semester_id,
            "provenance": self.provenance,
            "notice": self.notice,
        }


@dataclass(frozen=True, slots=True)
class BelowTargetResult:
    """Subjects below a target percentage."""

    subject_code: str
    subject_name: str | None
    cumulative_percentage: float
    target_percentage: float
    deficit: float


@dataclass(frozen=True, slots=True)
class SimulationInput:
    """Input for absence simulation."""

    current_attended: int
    current_conducted: int
    future_classes: int
    missed_classes: int


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Result of absence simulation."""

    current_percentage: float
    projected_percentage: float
    projected_attended: int
    projected_conducted: int
    missed_classes: int
    future_classes: int


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """Result of recovery calculation."""

    classes_needed: int
    projected_attended: int
    projected_conducted: int
    projected_percentage: float
    target_achieved: bool


class AttendanceCalculationError(Exception):
    """Raised when attendance calculation fails validation."""

    pass


def calculate_percentage(attended: int, conducted: int) -> float:
    """
    Calculate attendance percentage.

    Returns 0.0 if conducted is 0.
    """
    if conducted == 0:
        return 0.0
    return (attended / conducted) * 100.0


def round_percentage(value: float, decimals: int = 2) -> float:
    """Round percentage to consistent decimal places."""
    return round(value, decimals)


def simulate_absence(
    current_attended: int,
    current_conducted: int,
    future_classes: int,
    missed_classes: int,
) -> SimulationResult:
    """
    Simulate absence impact on attendance.

    Formula: ((x + (N - m)) / (y + N)) * 100
    where:
        x = current_attended
        y = current_conducted
        N = future_classes
        m = missed_classes

    Assumes all non-missed future classes are attended.
    """
    # Validation
    if current_attended < 0 or current_conducted < 0:
        raise AttendanceCalculationError("Attended and conducted must be non-negative")
    if current_attended > current_conducted:
        raise AttendanceCalculationError("Attended cannot exceed conducted")
    if future_classes < 0:
        raise AttendanceCalculationError("Future classes must be non-negative")
    if missed_classes < 0 or missed_classes > future_classes:
        raise AttendanceCalculationError(
            "Missed classes must be between 0 and future classes"
        )

    current_percentage = calculate_percentage(current_attended, current_conducted)

    projected_attended = current_attended + (future_classes - missed_classes)
    projected_conducted = current_conducted + future_classes
    projected_percentage = calculate_percentage(projected_attended, projected_conducted)

    return SimulationResult(
        current_percentage=round_percentage(current_percentage),
        projected_percentage=round_percentage(projected_percentage),
        projected_attended=projected_attended,
        projected_conducted=projected_conducted,
        missed_classes=missed_classes,
        future_classes=future_classes,
    )


def calculate_recovery(
    current_attended: int,
    current_conducted: int,
    target_percentage: float,
) -> RecoveryResult:
    """
    Calculate minimum classes needed to reach target percentage.

    Formula: Find minimum n >= 0 such that (x + n) / (y + n) >= T
    where T = target_percentage / 100

    Solution: n >= (T*y - x) / (1 - T) when T < 1
    """
    if current_attended < 0 or current_conducted < 0:
        raise AttendanceCalculationError("Attended and conducted must be non-negative")
    if current_attended > current_conducted:
        raise AttendanceCalculationError("Attended cannot exceed conducted")
    if target_percentage < 0 or target_percentage > 100:
        raise AttendanceCalculationError("Target percentage must be between 0 and 100")

    target_ratio = target_percentage / 100.0
    current_percentage = calculate_percentage(current_attended, current_conducted)

    # Already achieved
    if current_percentage >= target_percentage:
        return RecoveryResult(
            classes_needed=0,
            projected_attended=current_attended,
            projected_conducted=current_conducted,
            projected_percentage=round_percentage(current_percentage),
            target_achieved=True,
        )

    # If target is 100%, need infinite classes unless already perfect
    if target_percentage >= 100.0:
        if current_attended == current_conducted:
            return RecoveryResult(
                classes_needed=0,
                projected_attended=current_attended,
                projected_conducted=current_conducted,
                projected_percentage=100.0,
                target_achieved=True,
            )
        # Cannot reach 100% if not already perfect
        raise AttendanceCalculationError(
            "Cannot reach 100% target unless already perfect"
        )

    # Direct mathematical solution:
    # (x + n) / (y + n) >= T
    # x + n >= T(y + n)
    # x + n >= Ty + Tn
    # n - Tn >= Ty - x
    # n(1 - T) >= Ty - x
    # n >= (Ty - x) / (1 - T)

    target_ratio = target_percentage / 100.0
    numerator = target_ratio * current_conducted - current_attended
    denominator = 1.0 - target_ratio

    if denominator <= 0:
        raise AttendanceCalculationError("Invalid target percentage")

    classes_needed = max(0, ceil(numerator / denominator))

    projected_attended = current_attended + classes_needed
    projected_conducted = current_conducted + classes_needed
    projected_percentage = calculate_percentage(projected_attended, projected_conducted)

    return RecoveryResult(
        classes_needed=classes_needed,
        projected_attended=projected_attended,
        projected_conducted=projected_conducted,
        projected_percentage=round_percentage(projected_percentage),
        target_achieved=projected_percentage >= target_percentage,
    )


class AttendanceService:
    """
    Service for attendance queries and simulations.

    Enforces ownership, validates inputs, performs deterministic calculations.
    """

    def __init__(self, session, sync_service=None):
        self.session = session
        self._sync_service = sync_service

    @property
    def sync_service(self):
        if self._sync_service is None and self.session:
            from app.integrations.portal.sync_service import PortalSyncService
            self._sync_service = PortalSyncService(self.session)
        return self._sync_service

    async def sync_attendance(self, student_id: str, semester_id: str | None = None):
        """Trigger explicit sync of attendance data from portal."""
        from uuid import UUID
        return await self.sync_service.sync_attendance(UUID(student_id), semester_id)

    async def get_latest_snapshot(self, student_id: str, auto_sync: bool = False):
        """Get the latest attendance snapshot for a student."""
        from uuid import UUID
        from app.models.attendance import AttendanceSnapshot

        if auto_sync and self.sync_service:
            try:
                snapshot, _prov, _notice = await self.sync_service.get_or_sync_attendance(
                    UUID(student_id)
                )
                if snapshot:
                    return snapshot
            except Exception:
                pass

        result = await self.session.execute(
            select(AttendanceSnapshot)
            .where(AttendanceSnapshot.student_id == student_id)
            .order_by(desc(AttendanceSnapshot.captured_at))
            .limit(1)
            .options(selectinload(AttendanceSnapshot.subjects))
        )
        return result.scalar_one_or_none()

    async def get_snapshot_by_id(self, snapshot_id: str):
        """Get a specific snapshot by ID."""
        from app.models.attendance import AttendanceSnapshot

        result = await self.session.execute(
            select(AttendanceSnapshot)
            .where(AttendanceSnapshot.id == snapshot_id)
            .options(selectinload(AttendanceSnapshot.subjects))
        )
        return result.scalar_one_or_none()

    async def get_overall_attendance(self, student_id: str, auto_sync: bool = True):
        """Get overall attendance for a student, auto-syncing if stale and portal connected."""
        from uuid import UUID
        snapshot = None
        provenance = "portal_snapshot_fresh"
        notice = None

        if auto_sync and self.sync_service:
            try:
                snapshot, prov_enum, notice = await self.sync_service.get_or_sync_attendance(
                    UUID(student_id)
                )
                provenance = prov_enum.value
            except Exception:
                snapshot = await self.get_latest_snapshot(student_id)
        else:
            snapshot = await self.get_latest_snapshot(student_id)

        if not snapshot:
            return None

        return OverallAttendanceResult(
            attended=snapshot.overall_attended,
            conducted=snapshot.overall_conducted,
            percentage=round_percentage(snapshot.overall_percentage()),
            captured_at=snapshot.captured_at,
            source=snapshot.source.value,
            semester_id=snapshot.semester_id,
            provenance=provenance,
            notice=notice,
        )

    async def get_subject_attendance(self, student_id: str, subject_code: str):
        """Get attendance for a specific subject."""
        snapshot = await self.get_latest_snapshot(student_id, auto_sync=True)
        if not snapshot:
            return None

        for subject in snapshot.subjects:
            if subject.subject_code == subject_code:
                return SubjectAttendanceResult(
                    subject_code=subject.subject_code,
                    subject_name=subject.subject_name,
                    monthly_attended=subject.monthly_attended,
                    monthly_conducted=subject.monthly_conducted,
                    monthly_percentage=(
                        round_percentage(subject.monthly_percentage())
                        if subject.monthly_percentage() is not None
                        else None
                    ),
                    monthly_period=subject.monthly_period,
                    cumulative_attended=subject.cumulative_attended,
                    cumulative_conducted=subject.cumulative_conducted,
                    cumulative_percentage=round_percentage(
                        subject.cumulative_percentage()
                    ),
                )
        return None

    async def get_attendance_summary(self, student_id: str, auto_sync: bool = True):
        """Get complete attendance summary for a student, auto-syncing if stale and portal connected."""
        from uuid import UUID
        snapshot = None
        provenance = "portal_snapshot_fresh"
        notice = None

        if auto_sync and self.sync_service:
            try:
                snapshot, prov_enum, notice = await self.sync_service.get_or_sync_attendance(
                    UUID(student_id)
                )
                provenance = prov_enum.value
            except Exception:
                snapshot = await self.get_latest_snapshot(student_id)
        else:
            snapshot = await self.get_latest_snapshot(student_id)

        if not snapshot:
            return None

        subjects = tuple(
            SubjectAttendanceResult(
                subject_code=s.subject_code,
                subject_name=s.subject_name,
                monthly_attended=s.monthly_attended,
                monthly_conducted=s.monthly_conducted,
                monthly_percentage=(
                    round_percentage(s.monthly_percentage())
                    if s.monthly_percentage() is not None
                    else None
                ),
                monthly_period=s.monthly_period,
                cumulative_attended=s.cumulative_attended,
                cumulative_conducted=s.cumulative_conducted,
                cumulative_percentage=round_percentage(s.cumulative_percentage()),
            )
            for s in snapshot.subjects
        )

        return AttendanceSummaryResult(
            overall=OverallAttendanceResult(
                attended=snapshot.overall_attended,
                conducted=snapshot.overall_conducted,
                percentage=round_percentage(snapshot.overall_percentage()),
                captured_at=snapshot.captured_at,
                source=snapshot.source.value,
                semester_id=snapshot.semester_id,
                provenance=provenance,
                notice=notice,
            ),
            subjects=subjects,
            captured_at=snapshot.captured_at,
            source=snapshot.source.value,
            semester_id=snapshot.semester_id,
            provenance=provenance,
            notice=notice,
        )

    async def get_subjects_below_target(
        self, student_id: str, target_percentage: float
    ):
        """Get subjects below a target percentage."""
        if target_percentage < 0 or target_percentage > 100:
            raise AttendanceCalculationError(
                "Target percentage must be between 0 and 100"
            )

        snapshot = await self.get_latest_snapshot(student_id)
        if not snapshot:
            return ()

        results = []
        for subject in snapshot.subjects:
            pct = subject.cumulative_percentage()
            if pct < target_percentage:
                results.append(
                    BelowTargetResult(
                        subject_code=subject.subject_code,
                        subject_name=subject.subject_name,
                        cumulative_percentage=round_percentage(pct),
                        target_percentage=target_percentage,
                        deficit=round_percentage(target_percentage - pct),
                    )
                )
        return tuple(results)

    async def simulate_absence(
        self,
        student_id: str,
        subject_code: str,
        future_classes: int,
        missed_classes: int,
    ):
        """
        Simulate absence for a subject.

        Uses confirmed timetable to determine future classes if future_classes
        not provided.
        """
        snapshot = await self.get_latest_snapshot(student_id)
        if not snapshot:
            raise AttendanceCalculationError("No attendance data available")

        # Find subject
        subject = None
        for s in snapshot.subjects:
            if s.subject_code == subject_code:
                subject = s
                break

        if not subject:
            raise AttendanceCalculationError(
                f"Subject {subject_code} not found in attendance data"
            )

        return simulate_absence(
            current_attended=subject.cumulative_attended,
            current_conducted=subject.cumulative_conducted,
            future_classes=future_classes,
            missed_classes=missed_classes,
        )

    async def simulate_absence_with_timetable(
        self,
        student_id: str,
        subject_code: str,
        target_date: date,
        missed_count: int,
        timetable_service,
    ):
        """
        Simulate absence using confirmed timetable to determine future classes.

        Only works with CONFIRMED timetable.
        """
        snapshot = await self.get_latest_snapshot(student_id)
        if not snapshot:
            raise AttendanceCalculationError("No attendance data available")

        subject = None
        for s in snapshot.subjects:
            if s.subject_code == subject_code:
                subject = s
                break

        if not subject:
            raise AttendanceCalculationError(f"Subject {subject_code} not found")

        # Get confirmed timetable
        timetable = await timetable_service.get_confirmed_timetable(student_id)
        if not timetable:
            raise AttendanceCalculationError(
                "No confirmed timetable available for simulation"
            )

        # Count future classes for this subject on target date
        future_classes = await timetable_service.count_classes_for_subject_on_date(
            student_id, subject_code, target_date
        )

        if future_classes == 0:
            return simulate_absence(
                current_attended=subject.cumulative_attended,
                current_conducted=subject.cumulative_conducted,
                future_classes=0,
                missed_classes=0,
            )

        return simulate_absence(
            current_attended=subject.cumulative_attended,
            current_conducted=subject.cumulative_conducted,
            future_classes=future_classes,
            missed_classes=min(missed_count, future_classes),
        )

    async def calculate_classes_needed(
        self,
        student_id: str,
        subject_code: str,
        target_percentage: float,
    ):
        """Calculate classes needed to reach target percentage."""
        if target_percentage < 0 or target_percentage > 100:
            raise AttendanceCalculationError(
                "Target percentage must be between 0 and 100"
            )

        snapshot = await self.get_latest_snapshot(student_id)
        if not snapshot:
            raise AttendanceCalculationError("No attendance data available")

        subject = None
        for s in snapshot.subjects:
            if s.subject_code == subject_code:
                subject = s
                break

        if not subject:
            raise AttendanceCalculationError(f"Subject {subject_code} not found")

        return calculate_recovery(
            current_attended=subject.cumulative_attended,
            current_conducted=subject.cumulative_conducted,
            target_percentage=target_percentage,
        )

    async def get_all_subject_codes(self, student_id: str):
        """Get all subject codes for a student."""
        snapshot = await self.get_latest_snapshot(student_id)
        if not snapshot:
            return ()
        return tuple(s.subject_code for s in snapshot.subjects)

    async def get_snapshot_info(self, student_id: str):
        """Get snapshot metadata without full data."""
        snapshot = await self.get_latest_snapshot(student_id)
        if not snapshot:
            return None
        return {
            "snapshot_id": str(snapshot.id),
            "captured_at": snapshot.captured_at.isoformat(),
            "source": snapshot.source.value,
            "semester_id": snapshot.semester_id,
            "overall_percentage": round_percentage(snapshot.overall_percentage()),
        }
