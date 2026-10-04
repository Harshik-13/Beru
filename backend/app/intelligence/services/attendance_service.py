"""
Attendance service - deterministic business logic for attendance calculations.

All arithmetic is deterministic and performed in the backend.
The LLM never performs attendance arithmetic.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import zoneinfo
from math import ceil
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)


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
    monthly_attended: int | None = None
    monthly_conducted: int | None = None
    monthly_percentage: float | None = None
    monthly_period: str | None = None
    target_percentage: float = 75.0
    target_difference: float = 0.0
    target_status: str = "at_target"
    target_gap_percentage: float = 0.0
    legacy_snapshot_reconciled: bool = False

    def to_dict(self):
        return {
            "attended": self.attended,
            "conducted": self.conducted,
            "percentage": self.percentage,
            "cumulative_attended": self.attended,
            "cumulative_conducted": self.conducted,
            "cumulative_percentage": self.percentage,
            "monthly_attended": self.monthly_attended,
            "monthly_conducted": self.monthly_conducted,
            "monthly_percentage": self.monthly_percentage,
            "monthly_period": self.monthly_period,
            "target_percentage": self.target_percentage,
            "target_difference": self.target_difference,
            "target_status": self.target_status,
            "target_gap_percentage": self.target_gap_percentage,
            "legacy_snapshot_reconciled": self.legacy_snapshot_reconciled,
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
    classes_needed: int | None = None

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
            "classes_needed": self.classes_needed,
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

    classes_needed: int | None
    projected_attended: int
    projected_conducted: int
    projected_percentage: float
    target_achieved: bool
    achievable: bool = True
    message: str | None = None


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
            achievable=True,
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
                achievable=True,
            )
        # Cannot reach 100% mathematically if any class was missed
        return RecoveryResult(
            classes_needed=None,
            projected_attended=current_attended,
            projected_conducted=current_conducted,
            projected_percentage=round_percentage(current_percentage),
            target_achieved=False,
            achievable=False,
            message="100% attendance cannot be achieved mathematically because classes have already been missed.",
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

    classes_needed = max(0, ceil(round(numerator / denominator, 9)))

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

    async def _get_student_target(self, student_id: str | UUID) -> float:
        """Get student attendance target from DB or default to 75.0."""
        from app.models.student import Student

        try:
            uid = UUID(str(student_id))
            if hasattr(self, "student_repo") and self.student_repo:
                student = await self.student_repo.get_by_id(uid)
                if student and student.attendance_target is not None:
                    return float(student.attendance_target)
                return 75.0
            stmt = select(Student.attendance_target).where(Student.id == uid)
            res = await self.session.execute(stmt)
            target = res.scalar_one_or_none()
            return float(target) if target is not None else 75.0
        except Exception:
            return 75.0

    async def _get_confirmed_timetable_mapping(
        self, student_id: str | UUID
    ) -> dict[str, dict[str, Any]]:
        """Get course code mapping from student's confirmed timetable."""
        from app.intelligence.services.timetable_service import TimetableService

        try:
            tt_svc = TimetableService(self.session)
            mapping_list = await tt_svc.get_course_mapping(UUID(str(student_id)))
            return {item["course_code"]: item for item in mapping_list}
        except Exception:
            return {}

    async def get_latest_snapshot(
        self,
        student_id: str,
        semester_id: str | None = None,
        auto_sync: bool = False,
    ):
        """Get the latest attendance snapshot for a student, optionally filtered by semester."""
        from app.models.attendance import AttendanceSnapshot

        if auto_sync and self.sync_service:
            try:
                snapshot, _prov, _notice = await self.sync_service.get_or_sync_attendance(
                    UUID(student_id),
                    semester_id=semester_id,
                )
                if snapshot:
                    return snapshot
            except Exception:
                pass

        stmt = select(AttendanceSnapshot).where(AttendanceSnapshot.student_id == student_id)
        if semester_id:
            stmt = stmt.where(AttendanceSnapshot.semester_id == semester_id)
        stmt = stmt.order_by(desc(AttendanceSnapshot.captured_at)).limit(1).options(
            selectinload(AttendanceSnapshot.subjects)
        )
        result = await self.session.execute(stmt)
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

    @staticmethod
    def _reconcile_snapshot_overall(
        snapshot: Any,
        target_percentage: float = 75.0,
    ) -> tuple[int, int, float, bool, float, str, float]:
        """
        Derive authoritative overall attendance and target metrics at read time.

        If a legacy snapshot has broken overall aggregates (e.g. conducted < sum(subjects.conducted)),
        this read-time fallback reconstructs overall numbers from valid subject cumulative records
        without mutating the database row.

        Returns:
            (attended, conducted, percentage, legacy_reconciled,
             target_difference, target_status, target_gap_percentage)
        """
        attended = snapshot.overall_attended
        conducted = snapshot.overall_conducted
        legacy_reconciled = False

        if snapshot.subjects:
            sum_att = sum(
                s.cumulative_attended
                for s in snapshot.subjects
                if s.cumulative_attended is not None
            )
            sum_cond = sum(
                s.cumulative_conducted
                for s in snapshot.subjects
                if s.cumulative_conducted is not None
            )
            # Reconcile only if subject sums are structurally valid and exceed truncated overall conducted
            if (
                sum_cond > 0
                and 0 <= sum_att <= sum_cond
                and snapshot.overall_conducted < sum_cond
            ):
                logger.warning(
                    "Read-time legacy snapshot reconciliation triggered for snapshot %s: "
                    "overall_conducted (%s) < subject sum conducted (%s). "
                    "Falling back to subject cumulative totals (%s/%s) on read.",
                    snapshot.id,
                    snapshot.overall_conducted,
                    sum_cond,
                    sum_att,
                    sum_cond,
                )
                attended = sum_att
                conducted = sum_cond
                legacy_reconciled = True

        pct = (
            round_percentage(calculate_percentage(attended, conducted))
            if conducted > 0
            else 0.0
        )

        diff = round(pct - target_percentage, 2)
        gap = round(abs(diff), 2)
        if diff < -0.05:
            status = "below"
        elif diff > 0.05:
            status = "above"
        else:
            status = "at_target"

        return (
            attended,
            conducted,
            pct,
            legacy_reconciled,
            diff,
            status,
            gap,
        )

    async def get_overall_attendance(
        self,
        student_id: str,
        semester_id: str | None = None,
        auto_sync: bool = True,
    ):
        """Get overall attendance for a student, auto-syncing if stale and portal connected."""
        snapshot = None
        provenance = "portal_snapshot_fresh"
        notice = None

        if auto_sync and self.sync_service:
            try:
                snapshot, prov_enum, notice = await self.sync_service.get_or_sync_attendance(
                    UUID(student_id),
                    semester_id=semester_id,
                )
                provenance = prov_enum.value
            except Exception:
                snapshot = await self.get_latest_snapshot(student_id, semester_id=semester_id)
        else:
            snapshot = await self.get_latest_snapshot(student_id, semester_id=semester_id)

        if not snapshot:
            return None

        target = await self._get_student_target(student_id)
        (
            attended,
            conducted,
            pct,
            legacy_reconciled,
            diff,
            status,
            gap,
        ) = self._reconcile_snapshot_overall(snapshot, target)

        # Aggregate monthly metrics from snapshot subjects if available
        has_monthly = any(s.monthly_conducted is not None for s in snapshot.subjects)
        monthly_att = (
            sum(s.monthly_attended for s in snapshot.subjects if s.monthly_attended is not None)
            if has_monthly
            else None
        )
        monthly_cond = (
            sum(s.monthly_conducted for s in snapshot.subjects if s.monthly_conducted is not None)
            if has_monthly
            else None
        )
        monthly_pct = (
            round_percentage((monthly_att / monthly_cond) * 100.0)
            if has_monthly and monthly_cond and monthly_cond > 0
            else None
        )
        monthly_period = next((s.monthly_period for s in snapshot.subjects if s.monthly_period), None)

        return OverallAttendanceResult(
            attended=attended,
            conducted=conducted,
            percentage=pct,
            captured_at=snapshot.captured_at,
            source=snapshot.source.value,
            semester_id=snapshot.semester_id,
            provenance=provenance,
            notice=notice,
            monthly_attended=monthly_att,
            monthly_conducted=monthly_cond,
            monthly_percentage=monthly_pct,
            monthly_period=monthly_period,
            target_percentage=target,
            target_difference=diff,
            target_status=status,
            target_gap_percentage=gap,
            legacy_snapshot_reconciled=legacy_reconciled,
        )

    async def get_subject_attendance(self, student_id: str, subject_code: str):
        """Get attendance for a specific subject, matching by code or friendly name."""
        snapshot = await self.get_latest_snapshot(student_id, auto_sync=True)
        if not snapshot:
            return None

        target = await self._get_student_target(student_id)
        tt_mapping = await self._get_confirmed_timetable_mapping(student_id)
        query_norm = subject_code.strip().casefold()

        for subject in snapshot.subjects:
            s_code = subject.subject_code.strip()
            mapped_info = tt_mapping.get(s_code.upper(), {})
            friendly_name = subject.subject_name or mapped_info.get("course_name")

            # Check normalized exact match on code or friendly name
            code_match = s_code.casefold() == query_norm
            name_match = friendly_name and friendly_name.strip().casefold() == query_norm

            if code_match or name_match:
                classes_needed = None
                if subject.cumulative_conducted > 0:
                    pct = subject.cumulative_percentage()
                    if pct < target:
                        rec = calculate_recovery(
                            subject.cumulative_attended,
                            subject.cumulative_conducted,
                            target,
                        )
                        classes_needed = rec.classes_needed
                    else:
                        classes_needed = 0

                return SubjectAttendanceResult(
                    subject_code=subject.subject_code,
                    subject_name=friendly_name,
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
                    classes_needed=classes_needed,
                )
        return None

    async def get_attendance_summary(
        self,
        student_id: str,
        semester_id: str | None = None,
        auto_sync: bool = True,
    ):
        """Get complete attendance summary for a student, auto-syncing if stale and portal connected."""
        snapshot = None
        provenance = "portal_snapshot_fresh"
        notice = None

        if auto_sync and self.sync_service:
            try:
                snapshot, prov_enum, notice = await self.sync_service.get_or_sync_attendance(
                    UUID(student_id),
                    semester_id=semester_id,
                )
                provenance = prov_enum.value
            except Exception:
                snapshot = await self.get_latest_snapshot(student_id, semester_id=semester_id)
        else:
            snapshot = await self.get_latest_snapshot(student_id, semester_id=semester_id)

        if not snapshot:
            return None

        target = await self._get_student_target(student_id)
        tt_mapping = await self._get_confirmed_timetable_mapping(student_id)

        subject_results = []
        for s in snapshot.subjects:
            s_code = s.subject_code.strip()
            mapped_info = tt_mapping.get(s_code.upper(), {})
            friendly_name = s.subject_name or mapped_info.get("course_name")

            classes_needed = None
            if s.cumulative_conducted > 0:
                pct = s.cumulative_percentage()
                if pct < target:
                    rec = calculate_recovery(
                        s.cumulative_attended,
                        s.cumulative_conducted,
                        target,
                    )
                    classes_needed = rec.classes_needed
                else:
                    classes_needed = 0

            subject_results.append(
                SubjectAttendanceResult(
                    subject_code=s.subject_code,
                    subject_name=friendly_name,
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
                    classes_needed=classes_needed,
                )
            )

        # Aggregate monthly metrics
        has_monthly = any(s.monthly_conducted is not None for s in snapshot.subjects)
        monthly_att = (
            sum(s.monthly_attended for s in snapshot.subjects if s.monthly_attended is not None)
            if has_monthly
            else None
        )
        monthly_cond = (
            sum(s.monthly_conducted for s in snapshot.subjects if s.monthly_conducted is not None)
            if has_monthly
            else None
        )
        monthly_pct = (
            round_percentage((monthly_att / monthly_cond) * 100.0)
            if has_monthly and monthly_cond and monthly_cond > 0
            else None
        )
        monthly_period = next((s.monthly_period for s in snapshot.subjects if s.monthly_period), None)

        (
            overall_att,
            overall_cond,
            overall_pct,
            legacy_reconciled,
            diff,
            status,
            gap,
        ) = self._reconcile_snapshot_overall(snapshot, target)

        overall = OverallAttendanceResult(
            attended=overall_att,
            conducted=overall_cond,
            percentage=overall_pct,
            captured_at=snapshot.captured_at,
            source=snapshot.source.value,
            semester_id=snapshot.semester_id,
            provenance=provenance,
            notice=notice,
            monthly_attended=monthly_att,
            monthly_conducted=monthly_cond,
            monthly_percentage=monthly_pct,
            monthly_period=monthly_period,
            target_percentage=target,
            target_difference=diff,
            target_status=status,
            target_gap_percentage=gap,
            legacy_snapshot_reconciled=legacy_reconciled,
        )

        return AttendanceSummaryResult(
            overall=overall,
            subjects=tuple(subject_results),
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
        subject_code: str | None = None,
        target_percentage: float | None = None,
    ):
        """
        Calculate classes needed to reach target percentage.

        If subject_code is None or empty, calculates recovery classes needed overall.
        If target_percentage is None, uses the student's configured target.
        """
        if target_percentage is None:
            target_percentage = await self._get_student_target(student_id)

        if target_percentage < 0 or target_percentage > 100:
            raise AttendanceCalculationError(
                "Target percentage must be between 0 and 100"
            )

        snapshot = await self.get_latest_snapshot(student_id)
        if not snapshot:
            raise AttendanceCalculationError("No attendance data available")

        # If subject_code specified, find subject
        if subject_code:
            target_code = subject_code.strip().casefold()
            subject = None
            for s in snapshot.subjects:
                if (
                    s.subject_code.strip().casefold() == target_code
                    or (s.subject_name and s.subject_name.strip().casefold() == target_code)
                ):
                    subject = s
                    break

            if not subject:
                raise AttendanceCalculationError(f"Subject {subject_code} not found")

            return calculate_recovery(
                current_attended=subject.cumulative_attended,
                current_conducted=subject.cumulative_conducted,
                target_percentage=target_percentage,
            )

        # Overall recovery
        (
            overall_att,
            overall_cond,
            _pct,
            _reconciled,
            _diff,
            _status,
            _gap,
        ) = self._reconcile_snapshot_overall(snapshot, target_percentage)

        return calculate_recovery(
            current_attended=overall_att,
            current_conducted=overall_cond,
            target_percentage=target_percentage,
        )

    async def set_attendance_target(
        self,
        student_id: str,
        target_percentage: float,
    ) -> dict[str, Any]:
        """
        Set and verify the student's target attendance percentage.

        Protocol:
        1. Validate 1.0 <= target_percentage <= 100.0.
        2. Verify student exists.
        3. Check idempotency.
        4. Mutate & commit to database.
        5. Re-read fresh from DB to verify committed value.
        6. Record audit event in audit_events table.
        7. Return verified post-mutation payload.
        """
        if target_percentage < 1.0 or target_percentage > 100.0:
            raise ValueError("Target percentage must be between 1.0 and 100.0")

        from app.models.student import Student
        from app.security.audit import AuditService

        uid = UUID(str(student_id))
        if hasattr(self, "student_repo") and self.student_repo:
            student = await self.student_repo.get_by_id(uid)
        else:
            stmt = select(Student).where(Student.id == uid)
            res = await self.session.execute(stmt)
            student = res.scalar_one_or_none()
        if not student:
            raise ValueError(f"Student not found: {student_id}")

        old_target = (
            float(student.attendance_target)
            if student.attendance_target is not None
            else 75.0
        )
        new_target = round(float(target_percentage), 2)
        is_idempotent = abs(old_target - new_target) < 1e-4

        if not is_idempotent:
            student.attendance_target = new_target
            await self.session.commit()

            # Re-read fresh from DB to verify committed value
            if hasattr(self, "student_repo") and self.student_repo:
                verified_student = await self.student_repo.get_by_id(uid)
                verified_target = (
                    float(verified_student.attendance_target)
                    if verified_student and verified_student.attendance_target is not None
                    else new_target
                )
            else:
                verify_stmt = select(Student.attendance_target).where(Student.id == uid)
                verify_res = await self.session.execute(verify_stmt)
                verified_target = float(verify_res.scalar_one())

            # Log audit event
            audit_svc = getattr(self, "audit_service", None) or AuditService(self.session)
            await audit_svc.log_student_updated(
                student_id=uid,
                event_metadata={
                    "action": "set_attendance_target",
                    "old_target": old_target,
                    "new_target": verified_target,
                    "idempotent": False,
                },
            )
            await self.session.commit()
        else:
            verified_target = old_target

        # Compute verified post-mutation metrics from attendance snapshot
        snapshot = await self.get_latest_snapshot(str(uid), auto_sync=False)
        if snapshot:
            (
                attended,
                conducted,
                pct,
                legacy_reconciled,
                diff,
                status,
                gap,
            ) = self._reconcile_snapshot_overall(snapshot, verified_target)

            t_ratio = verified_target / 100.0
            if pct < verified_target:
                rec = calculate_recovery(attended, conducted, verified_target)
                recovery_classes = rec.classes_needed
                safe_bunks = 0
            else:
                recovery_classes = 0
                safe_bunks = (
                    max(0, int((attended - t_ratio * conducted) / t_ratio))
                    if t_ratio > 0
                    else 0
                )
        else:
            attended, conducted, pct = 0, 0, 0.0
            diff, gap = 0.0, 0.0
            status = "at_target"
            recovery_classes = 0
            safe_bunks = 0

        return {
            "success": True,
            "mutation": {
                "action": "set_attendance_target",
                "success": True,
                "old_target": old_target,
                "new_target": verified_target,
                "idempotent": is_idempotent,
            },
            "attendance": {
                "current_percentage": pct,
                "attended": attended,
                "conducted": conducted,
            },
            "target": {
                "percentage": verified_target,
                "difference": diff,
                "status": status,
                "gap_percentage": gap,
                "recovery_classes_needed": recovery_classes,
                "safe_bunks": safe_bunks,
            },
            "provenance": {
                "snapshot_id": str(snapshot.id) if snapshot else None,
                "captured_at": snapshot.captured_at.isoformat()
                if snapshot and hasattr(snapshot.captured_at, "isoformat")
                else (str(snapshot.captured_at) if snapshot else None),
            },
        }

    async def calculate_bunk_allowance(
        self,
        student_id: str,
        subject_code: str | None = None,
    ) -> dict[str, Any]:
        """
        Calculate maximum safe classes that can be missed without dropping below target.

        Formula: B_max = max(0, floor((A - t*C) / t)) where t = T / 100.
        """
        snapshot = await self.get_latest_snapshot(student_id, auto_sync=True)
        if not snapshot:
            return {
                "available": False,
                "message": (
                    "I couldn't verify your current attendance data, so I can't safely "
                    "calculate that right now."
                ),
            }

        target = await self._get_student_target(student_id)
        tt_mapping = await self._get_confirmed_timetable_mapping(student_id)
        t_ratio = target / 100.0

        # Case 1: Specific subject requested
        if subject_code:
            query_norm = subject_code.strip().casefold()
            matched_subject = None
            friendly_name = None

            for s in snapshot.subjects:
                s_code = s.subject_code.strip()
                mapped_info = tt_mapping.get(s_code.upper(), {})
                f_name = s.subject_name or mapped_info.get("course_name")

                if (
                    s_code.casefold() == query_norm
                    or (f_name and f_name.strip().casefold() == query_norm)
                ):
                    matched_subject = s
                    friendly_name = f_name or s_code
                    break

            if not matched_subject:
                return {
                    "available": False,
                    "message": f"Subject {subject_code} was not found in your verified attendance data.",
                }

            A = matched_subject.cumulative_attended
            C = matched_subject.cumulative_conducted

            if C == 0:
                return {
                    "available": True,
                    "subject_code": matched_subject.subject_code,
                    "subject_name": friendly_name,
                    "attended": A,
                    "conducted": C,
                    "current_percentage": 0.0,
                    "target_percentage": target,
                    "safe_bunks": 0,
                    "projected_percentage_after_bunk": 0.0,
                    "status": "no_classes_conducted",
                    "captured_at": snapshot.captured_at.isoformat()
                    if hasattr(snapshot.captured_at, "isoformat")
                    else str(snapshot.captured_at),
                }

            curr_pct = round_percentage((A / C) * 100.0)
            if curr_pct < target or t_ratio <= 0:
                safe_bunks = 0
                proj_pct = curr_pct
                status = "below_target"
            else:
                safe_bunks = max(0, int((A - t_ratio * C) / t_ratio))
                proj_pct = round_percentage((A / (C + safe_bunks)) * 100.0)
                status = "safe_to_bunk" if safe_bunks > 0 else "at_target"

            return {
                "available": True,
                "is_overall": False,
                "subject_code": matched_subject.subject_code,
                "subject_name": friendly_name,
                "attended": A,
                "conducted": C,
                "current_percentage": curr_pct,
                "target_percentage": target,
                "safe_bunks": safe_bunks,
                "projected_percentage_after_bunk": proj_pct,
                "status": status,
                "captured_at": snapshot.captured_at.isoformat()
                if hasattr(snapshot.captured_at, "isoformat")
                else str(snapshot.captured_at),
            }

        # Case 2: Overall and per-subject breakdown
        (
            overall_att,
            overall_cond,
            overall_pct,
            _legacy_reconciled,
            _diff,
            _target_status,
            _gap,
        ) = self._reconcile_snapshot_overall(snapshot, target)

        if overall_cond == 0 or t_ratio <= 0:
            overall_safe_bunks = 0
            overall_proj_pct = 0.0
            overall_status = "no_classes_conducted"
        elif overall_pct < target:
            overall_safe_bunks = 0
            overall_proj_pct = overall_pct
            overall_status = "below_target"
        else:
            overall_safe_bunks = max(0, int((overall_att - t_ratio * overall_cond) / t_ratio))
            overall_proj_pct = round_percentage(
                (overall_att / (overall_cond + overall_safe_bunks)) * 100.0
            )
            overall_status = "safe_to_bunk" if overall_safe_bunks > 0 else "at_target"

        subject_bunks = []
        for s in snapshot.subjects:
            s_code = s.subject_code.strip()
            mapped_info = tt_mapping.get(s_code.upper(), {})
            f_name = s.subject_name or mapped_info.get("course_name") or s_code

            s_a = s.cumulative_attended
            s_c = s.cumulative_conducted

            if s_c == 0:
                s_bunk = 0
                s_pct = 0.0
                s_proj = 0.0
                s_status = "no_classes_conducted"
            else:
                s_pct = round_percentage((s_a / s_c) * 100.0)
                if s_pct < target or t_ratio <= 0:
                    s_bunk = 0
                    s_proj = s_pct
                    s_status = "below_target"
                else:
                    s_bunk = max(0, int((s_a - t_ratio * s_c) / t_ratio))
                    s_proj = round_percentage((s_a / (s_c + s_bunk)) * 100.0)
                    s_status = "safe_to_bunk" if s_bunk > 0 else "at_target"

            subject_bunks.append({
                "subject_code": s_code,
                "subject_name": f_name,
                "attended": s_a,
                "conducted": s_c,
                "current_percentage": s_pct,
                "safe_bunks": s_bunk,
                "projected_percentage_after_bunk": s_proj,
                "status": s_status,
            })

        return {
            "available": True,
            "is_overall": True,
            "attended": overall_att,
            "conducted": overall_cond,
            "current_percentage": overall_pct,
            "target_percentage": target,
            "safe_bunks": overall_safe_bunks,
            "projected_percentage_after_bunk": overall_proj_pct,
            "status": overall_status,
            "subjects": subject_bunks,
            "captured_at": snapshot.captured_at.isoformat()
            if hasattr(snapshot.captured_at, "isoformat")
            else str(snapshot.captured_at),
        }

    async def simulate_day_absence(
        self,
        student_id: str,
        day: str = "tomorrow",
        timetable_service=None,
    ) -> dict[str, Any]:
        """
        Simulate absence for an entire day based on scheduled classes in CONFIRMED timetable.

        Aggregates multiple periods per subject, predicts impact on individual subjects
        and overall attendance, and reports a 3-tier safety hierarchy:
        (overall_safe, subjects_safe, is_safe).
        """
        from app.models.student import Student
        from app.models.timetable import ActivityType, LabBatch, TimetableStatus

        uid = UUID(str(student_id))

        if timetable_service is None:
            from app.intelligence.services.timetable_service import TimetableService
            timetable_service = TimetableService(self.session)

        # Check confirmed timetable
        confirmed_tt = await timetable_service.get_confirmed_timetable(uid)
        if not confirmed_tt:
            pending_tt = await timetable_service.get_pending_timetable(uid)
            if pending_tt:
                return {
                    "available": False,
                    "error_code": "TIMETABLE_REVIEW_PENDING",
                    "message": (
                        "Timetable review pending. Only confirmed timetables are queryable "
                        "for day-leave simulations. Please review and confirm your timetable first."
                    ),
                }
            return {
                "available": False,
                "error_code": "NO_TIMETABLE",
                "message": (
                    "No confirmed timetable found. Please upload and confirm your timetable "
                    "to simulate day-leave."
                ),
            }

        # Student context for timezone & lab batch
        if hasattr(self, "student_repo") and self.student_repo:
            student = await self.student_repo.get_by_id(uid)
        else:
            stmt = select(Student).where(Student.id == uid)
            res = await self.session.execute(stmt)
            student = res.scalar_one_or_none()

        tz_name = student.timezone if student and student.timezone else "Asia/Kolkata"
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            tz = zoneinfo.ZoneInfo("Asia/Kolkata")

        today_dt = datetime.now(tz).date()

        # Parse date from day identifier
        if isinstance(day, date):
            target_date = day
        else:
            day_clean = str(day).strip().casefold()
            if day_clean == "today":
                target_date = today_dt
            elif day_clean == "tomorrow":
                target_date = today_dt + timedelta(days=1)
            else:
                weekday_map = {
                    "monday": 0,
                    "tuesday": 1,
                    "wednesday": 2,
                    "thursday": 3,
                    "friday": 4,
                    "saturday": 5,
                    "sunday": 6,
                }
                if day_clean in weekday_map:
                    target_idx = weekday_map[day_clean]
                    diff = (target_idx - today_dt.weekday()) % 7
                    target_date = (
                        today_dt + timedelta(days=7)
                        if diff == 0
                        else today_dt + timedelta(days=diff)
                    )
                else:
                    try:
                        target_date = date.fromisoformat(str(day).strip())
                    except Exception:
                        target_date = today_dt + timedelta(days=1)

        day_name = target_date.strftime("%A")

        # Sunday check
        if target_date.weekday() == 6:
            return {
                "available": True,
                "date": target_date.isoformat(),
                "day_name": day_name,
                "scheduled_classes_count": 0,
                "is_weekend": True,
                "is_safe": True,
                "overall_safe": True,
                "subjects_safe": True,
                "message": "It's Sunday! No classes are scheduled.",
            }

        # Filter entries for target date & lab batch
        all_entries = await timetable_service.entry_repo.get_for_timetable(
            confirmed_tt.id
        )
        student_batch = student.lab_batch if student else LabBatch.UNKNOWN

        day_entries = []
        for e in all_entries:
            if e.day_of_week != target_date.weekday():
                continue
            if e.activity_type == ActivityType.BREAK:
                continue
            if (
                student_batch != LabBatch.UNKNOWN
                and e.lab_batch is not None
                and e.lab_batch != LabBatch.UNKNOWN
                and e.lab_batch != student_batch
            ):
                continue
            day_entries.append(e)

        if not day_entries:
            return {
                "available": True,
                "date": target_date.isoformat(),
                "day_name": day_name,
                "scheduled_classes_count": 0,
                "is_safe": True,
                "overall_safe": True,
                "subjects_safe": True,
                "message": f"No classes are scheduled on {day_name} ({target_date.strftime('%d %b')}).",
            }

        # Fetch attendance snapshot (simulation is 100% offline, never trigger live sync)
        snapshot = await self.get_latest_snapshot(str(uid), auto_sync=False)
        if not snapshot:
            return {
                "available": False,
                "message": (
                    "I couldn't verify your current attendance data, so I can't safely "
                    "simulate day-leave right now."
                ),
            }

        target = await self._get_student_target(uid)
        tt_mapping = await self._get_confirmed_timetable_mapping(uid)

        # Aggregate repeated periods by subject
        subject_counts: dict[str, int] = {}
        for e in day_entries:
            key = (
                e.course_code.strip()
                if e.course_code
                else e.activity_name.strip()
            )
            subject_counts[key] = subject_counts.get(key, 0) + 1

        total_scheduled_classes = sum(subject_counts.values())

        # Match scheduled items to snapshot subjects
        affected_subjects = []
        for raw_key, count in subject_counts.items():
            matched_sub = None
            f_name = raw_key
            for s in snapshot.subjects:
                s_code = s.subject_code.strip()
                mapped_info = tt_mapping.get(s_code.upper(), {})
                candidate_name = s.subject_name or mapped_info.get("course_name")
                if (
                    s_code.casefold() == raw_key.casefold()
                    or (candidate_name and candidate_name.strip().casefold() == raw_key.casefold())
                ):
                    matched_sub = s
                    f_name = candidate_name or s_code
                    break

            if matched_sub:
                curr_att = matched_sub.cumulative_attended
                curr_cond = matched_sub.cumulative_conducted
                curr_pct = round_percentage((curr_att / curr_cond) * 100.0) if curr_cond > 0 else 0.0

                proj_cond = curr_cond + count
                proj_att = curr_att  # absent
                proj_pct = round_percentage((proj_att / proj_cond) * 100.0) if proj_cond > 0 else 0.0
                is_sub_safe = proj_pct >= target

                affected_subjects.append({
                    "subject_code": matched_sub.subject_code,
                    "subject_name": f_name,
                    "scheduled_periods": count,
                    "current_percentage": curr_pct,
                    "projected_percentage": proj_pct,
                    "is_safe": is_sub_safe,
                })
            else:
                affected_subjects.append({
                    "subject_code": raw_key,
                    "subject_name": raw_key,
                    "scheduled_periods": count,
                    "current_percentage": None,
                    "projected_percentage": None,
                    "is_safe": True,
                })

        # Calculate overall impact
        (
            overall_att,
            overall_cond,
            overall_pct,
            _legacy_reconciled,
            _diff,
            _target_status,
            _gap,
        ) = self._reconcile_snapshot_overall(snapshot, target)

        proj_overall_cond = overall_cond + total_scheduled_classes
        proj_overall_att = overall_att
        proj_overall_pct = (
            round_percentage((proj_overall_att / proj_overall_cond) * 100.0)
            if proj_overall_cond > 0
            else 0.0
        )

        overall_safe = proj_overall_pct >= target
        subjects_safe = all(
            s["is_safe"] for s in affected_subjects if s["current_percentage"] is not None
        )
        is_safe = overall_safe and subjects_safe

        return {
            "available": True,
            "date": target_date.isoformat(),
            "day_name": day_name,
            "scheduled_classes_count": total_scheduled_classes,
            "current_overall_percentage": overall_pct,
            "projected_overall_percentage": proj_overall_pct,
            "target_percentage": target,
            "overall_safe": overall_safe,
            "subjects_safe": subjects_safe,
            "is_safe": is_safe,
            "affected_subjects": affected_subjects,
            "captured_at": snapshot.captured_at.isoformat()
            if hasattr(snapshot.captured_at, "isoformat")
            else str(snapshot.captured_at),
        }

    async def get_attendance_extremes(self, student_id: str) -> dict[str, Any]:
        """
        Get subjects with highest and lowest attendance with multi-course tie handling.
        """
        snapshot = await self.get_latest_snapshot(student_id, auto_sync=True)
        if not snapshot or not snapshot.subjects:
            return {
                "available": False,
                "message": "No verified attendance data available to compute extremes.",
            }

        target = await self._get_student_target(student_id)
        tt_mapping = await self._get_confirmed_timetable_mapping(student_id)

        sub_list = []
        for s in snapshot.subjects:
            code = s.subject_code.strip()
            mapped = tt_mapping.get(code.upper(), {})
            name = s.subject_name or mapped.get("course_name") or code
            pct = (
                round_percentage(s.cumulative_percentage())
                if s.cumulative_conducted > 0
                else 0.0
            )
            sub_list.append({
                "subject_code": code,
                "subject_name": name,
                "attended": s.cumulative_attended,
                "conducted": s.cumulative_conducted,
                "percentage": pct,
            })

        if not sub_list:
            return {
                "available": False,
                "message": "No subject attendance records found.",
            }

        min_pct = min(s["percentage"] for s in sub_list)
        max_pct = max(s["percentage"] for s in sub_list)

        lowest = [s for s in sub_list if abs(s["percentage"] - min_pct) < 1e-4]
        highest = [s for s in sub_list if abs(s["percentage"] - max_pct) < 1e-4]

        below_target = [s for s in sub_list if s["percentage"] < target]
        at_or_above_target = [s for s in sub_list if s["percentage"] >= target]

        (
            overall_att,
            overall_cond,
            overall_pct,
            _legacy_reconciled,
            _diff,
            _target_status,
            _gap,
        ) = self._reconcile_snapshot_overall(snapshot, target)

        return {
            "available": True,
            "overall_percentage": overall_pct,
            "target_percentage": target,
            "lowest": lowest,
            "highest": highest,
            "below_target": below_target,
            "at_or_above_target": at_or_above_target,
            "total_subjects": len(sub_list),
            "captured_at": snapshot.captured_at.isoformat()
            if hasattr(snapshot.captured_at, "isoformat")
            else str(snapshot.captured_at),
        }

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


# Module-level alias for authoritative snapshot reconciliation
reconcile_snapshot_overall = AttendanceService._reconcile_snapshot_overall

