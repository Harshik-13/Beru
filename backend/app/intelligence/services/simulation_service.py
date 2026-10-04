"""
Structurally isolated Attendance Simulation Service.

Provides deterministic mathematical forward projections for multi-day,
mixed attend/skip scenarios, and subject-level period counts.

INVARIANT:
This service has ZERO dependency on PortalSyncService or external portal HTTP
clients. It operates strictly on locally committed PostgreSQL snapshots and
confirmed timetable entries.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.intelligence.services.attendance_service import (
    calculate_percentage,
    reconcile_snapshot_overall,
    round_percentage,
)
from app.intelligence.services.scenario_resolver import (
    ResolvedScenario,
    SimulationAction,
)
from app.models.timetable import ActivityType, LabBatch

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SubjectSimulationDelta:
    """Projected attendance delta for an individual subject."""

    subject_code: str
    subject_name: str | None
    current_attended: int
    current_conducted: int
    current_percentage: float
    delta_attended: int
    delta_conducted: int
    projected_attended: int
    projected_conducted: int
    projected_percentage: float
    target_percentage: float
    is_safe: bool
    breach_gap: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_code": self.subject_code,
            "subject_name": self.subject_name,
            "current_attended": self.current_attended,
            "current_conducted": self.current_conducted,
            "current_percentage": self.current_percentage,
            "delta_attended": self.delta_attended,
            "delta_conducted": self.delta_conducted,
            "projected_attended": self.projected_attended,
            "projected_conducted": self.projected_conducted,
            "projected_percentage": self.projected_percentage,
            "target_percentage": self.target_percentage,
            "is_safe": self.is_safe,
            "breach_gap": self.breach_gap,
        }


@dataclass(frozen=True, slots=True)
class ScheduleSimulationResult:
    """Result of a multi-day or mixed attendance simulation scenario."""

    available: bool
    scenario_dates: list[str] = field(default_factory=list)
    total_scheduled_periods: int = 0
    total_delta_attended: int = 0
    total_delta_conducted: int = 0
    current_attended: int = 0
    current_conducted: int = 0
    current_percentage: float = 0.0
    projected_attended: int = 0
    projected_conducted: int = 0
    projected_percentage: float = 0.0
    percentage_change: float = 0.0
    target_percentage: float = 75.0
    overall_safe: bool = True
    subjects_safe: bool = True
    is_safe: bool = True
    critical_breaches: list[str] = field(default_factory=list)
    subject_breakdown: list[SubjectSimulationDelta] = field(default_factory=list)
    snapshot_captured_at: str | None = None
    snapshot_age_hours: float | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "scenario_dates": self.scenario_dates,
            "total_scheduled_periods": self.total_scheduled_periods,
            "total_delta_attended": self.total_delta_attended,
            "total_delta_conducted": self.total_delta_conducted,
            "current_attended": self.current_attended,
            "current_conducted": self.current_conducted,
            "current_percentage": self.current_percentage,
            "projected_attended": self.projected_attended,
            "projected_conducted": self.projected_conducted,
            "projected_percentage": self.projected_percentage,
            "percentage_change": self.percentage_change,
            "target_percentage": self.target_percentage,
            "overall_safe": self.overall_safe,
            "subjects_safe": self.subjects_safe,
            "is_safe": self.is_safe,
            "critical_breaches": self.critical_breaches,
            "subject_breakdown": [s.to_dict() for s in self.subject_breakdown],
            "snapshot_captured_at": self.snapshot_captured_at,
            "snapshot_age_hours": self.snapshot_age_hours,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class SubjectPeriodsSimulationResult:
    """Result of simulating arbitrary period counts on a specific subject."""

    available: bool
    subject_code: str
    subject_name: str | None
    periods_missed: int
    periods_attended: int
    subject_current_attended: int = 0
    subject_current_conducted: int = 0
    subject_current_percentage: float = 0.0
    subject_projected_attended: int = 0
    subject_projected_conducted: int = 0
    subject_projected_percentage: float = 0.0
    subject_is_safe: bool = True
    overall_current_attended: int = 0
    overall_current_conducted: int = 0
    overall_current_percentage: float = 0.0
    overall_projected_attended: int = 0
    overall_projected_conducted: int = 0
    overall_projected_percentage: float = 0.0
    overall_percentage_change: float = 0.0
    overall_is_safe: bool = True
    target_percentage: float = 75.0
    snapshot_captured_at: str | None = None
    snapshot_age_hours: float | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "subject_code": self.subject_code,
            "subject_name": self.subject_name,
            "periods_missed": self.periods_missed,
            "periods_attended": self.periods_attended,
            "subject_current_attended": self.subject_current_attended,
            "subject_current_conducted": self.subject_current_conducted,
            "subject_current_percentage": self.subject_current_percentage,
            "subject_projected_attended": self.subject_projected_attended,
            "subject_projected_conducted": self.subject_projected_conducted,
            "subject_projected_percentage": self.subject_projected_percentage,
            "subject_is_safe": self.subject_is_safe,
            "overall_current_attended": self.overall_current_attended,
            "overall_current_conducted": self.overall_current_conducted,
            "overall_current_percentage": self.overall_current_percentage,
            "overall_projected_attended": self.overall_projected_attended,
            "overall_projected_conducted": self.overall_projected_conducted,
            "overall_projected_percentage": self.overall_projected_percentage,
            "overall_percentage_change": self.overall_percentage_change,
            "overall_is_safe": self.overall_is_safe,
            "target_percentage": self.target_percentage,
            "snapshot_captured_at": self.snapshot_captured_at,
            "snapshot_age_hours": self.snapshot_age_hours,
            "message": self.message,
        }


class AttendanceSimulationService:
    """
    Dedicated simulation service operating strictly on local database state.
    Structurally isolated from any portal sync machinery.
    """

    def __init__(
        self,
        session: AsyncSession,
        snapshot_repo: Any,
        timetable_repo: Any,
        student_repo: Any,
    ):
        self.session = session
        self.snapshot_repo = snapshot_repo
        self.timetable_repo = timetable_repo
        self.student_repo = student_repo

    async def simulate_schedule_scenario(
        self,
        scenario: ResolvedScenario,
    ) -> ScheduleSimulationResult:
        """
        Simulate attendance impact for a resolved scenario (explicit dates & actions).
        Reuses authoritative snapshot reconciliation to correct legacy truncated snapshots.
        """
        uid = scenario.student_id
        student = await self.student_repo.get_by_id(uid)
        target = student.attendance_target if student and student.attendance_target else 75.0
        student_batch = student.lab_batch if student else LabBatch.UNKNOWN

        # 1. Fetch latest local snapshot (zero portal calls)
        snapshot = await self._get_latest_snapshot(uid)
        if not snapshot:
            return ScheduleSimulationResult(
                available=False,
                message="I couldn't verify your current attendance data, so I cannot safely simulate this scenario.",
            )

        # 2. Authoritative baseline reconciliation
        (
            curr_att,
            curr_cond,
            curr_pct,
            legacy_reconciled,
            diff,
            status,
            gap,
        ) = reconcile_snapshot_overall(snapshot, target)

        # Snapshot freshness calculation
        now_utc = datetime.now(UTC)
        cap_at = snapshot.captured_at
        if cap_at.tzinfo is None:
            cap_at = cap_at.replace(tzinfo=UTC)
        age_hours = round(max(0.0, (now_utc - cap_at).total_seconds() / 3600.0), 1)

        # 3. Load confirmed timetable
        confirmed_tt = await self._get_confirmed_timetable(uid)
        if not confirmed_tt:
            return ScheduleSimulationResult(
                available=False,
                message="No confirmed timetable found to map scheduled periods.",
            )

        entries = await self._get_timetable_entries(confirmed_tt)

        # 4. Map scheduled periods across scenario actions
        delta_att_by_code: dict[str, int] = {}
        delta_cond_by_code: dict[str, int] = {}
        scenario_descriptions: list[str] = []

        total_scheduled_periods = 0

        for day_action in scenario.actions:
            d = day_action.date
            weekday = d.weekday()
            act = day_action.action

            # Filter entries for this weekday
            day_entries = [
                e
                for e in entries
                if e.day_of_week == weekday and e.activity_type != ActivityType.BREAK
            ]

            if student_batch != LabBatch.UNKNOWN:
                day_entries = [
                    e
                    for e in day_entries
                    if e.lab_batch is None
                    or e.lab_batch == LabBatch.UNKNOWN
                    or e.lab_batch == student_batch
                ]

            periods_count = len(day_entries)
            total_scheduled_periods += periods_count
            act_label = "ATTEND" if act == SimulationAction.ATTEND else "SKIP"
            scenario_descriptions.append(
                f"{d.strftime('%A, %d %b')}: {periods_count} periods ({act_label})"
            )

            for e in day_entries:
                key = (e.course_code or e.activity_name or "Unknown").strip().upper()
                if act == SimulationAction.ATTEND:
                    delta_att_by_code[key] = delta_att_by_code.get(key, 0) + 1
                    delta_cond_by_code[key] = delta_cond_by_code.get(key, 0) + 1
                else:  # SKIP
                    delta_cond_by_code[key] = delta_cond_by_code.get(key, 0) + 1

        total_delta_att = sum(delta_att_by_code.values())
        total_delta_cond = sum(delta_cond_by_code.values())

        # 5. Calculate overall projected numbers
        proj_att = curr_att + total_delta_att
        proj_cond = curr_cond + total_delta_cond
        proj_pct = round_percentage(calculate_percentage(proj_att, proj_cond))
        pct_change = round(proj_pct - curr_pct, 2)
        overall_safe = proj_pct >= target

        # 6. Calculate per-subject breakdown & critical breaches
        subject_breakdown: list[SubjectSimulationDelta] = []
        critical_breaches: list[str] = []

        # Build timetable mapping for display names
        tt_mapping: dict[str, str] = {}
        for e in entries:
            c = (e.course_code or "").strip().upper()
            n = (e.activity_name or "").strip()
            if c and n:
                tt_mapping[c] = n

        for s in snapshot.subjects:
            s_code = s.subject_code.strip().upper()
            # Match delta by subject code or mapped name
            matched_delta_att = 0
            matched_delta_cond = 0

            for k, val in delta_att_by_code.items():
                if k == s_code or (s.subject_name and k == s.subject_name.strip().upper()):
                    matched_delta_att += val

            for k, val in delta_cond_by_code.items():
                if k == s_code or (s.subject_name and k == s.subject_name.strip().upper()):
                    matched_delta_cond += val

            s_curr_att = s.cumulative_attended
            s_curr_cond = s.cumulative_conducted
            s_curr_pct = round_percentage(calculate_percentage(s_curr_att, s_curr_cond))

            s_proj_att = s_curr_att + matched_delta_att
            s_proj_cond = s_curr_cond + matched_delta_cond
            s_proj_pct = round_percentage(calculate_percentage(s_proj_att, s_proj_cond))

            is_sub_safe = s_proj_pct >= target
            gap_sub = round(abs(s_proj_pct - target), 2)

            # If subject was affected and breaches or worsens below target
            if matched_delta_cond > 0 and s_proj_pct < target:
                friendly = s.subject_name or tt_mapping.get(s_code, s_code)
                critical_breaches.append(f"{friendly} ({s_proj_pct:.1f}% vs {target:.0f}%)")

            if matched_delta_cond > 0:
                subject_breakdown.append(
                    SubjectSimulationDelta(
                        subject_code=s.subject_code,
                        subject_name=s.subject_name or tt_mapping.get(s_code),
                        current_attended=s_curr_att,
                        current_conducted=s_curr_cond,
                        current_percentage=s_curr_pct,
                        delta_attended=matched_delta_att,
                        delta_conducted=matched_delta_cond,
                        projected_attended=s_proj_att,
                        projected_conducted=s_proj_cond,
                        projected_percentage=s_proj_pct,
                        target_percentage=target,
                        is_safe=is_sub_safe,
                        breach_gap=gap_sub,
                    )
                )

        subjects_safe = len(critical_breaches) == 0
        is_safe = overall_safe and subjects_safe

        return ScheduleSimulationResult(
            available=True,
            scenario_dates=scenario_descriptions,
            total_scheduled_periods=total_scheduled_periods,
            total_delta_attended=total_delta_att,
            total_delta_conducted=total_delta_cond,
            current_attended=curr_att,
            current_conducted=curr_cond,
            current_percentage=curr_pct,
            projected_attended=proj_att,
            projected_conducted=proj_cond,
            projected_percentage=proj_pct,
            percentage_change=pct_change,
            target_percentage=target,
            overall_safe=overall_safe,
            subjects_safe=subjects_safe,
            is_safe=is_safe,
            critical_breaches=critical_breaches,
            subject_breakdown=subject_breakdown,
            snapshot_captured_at=cap_at.isoformat(),
            snapshot_age_hours=age_hours,
        )

    async def simulate_subject_periods(
        self,
        student_id: UUID | str,
        subject_code: str,
        periods_to_miss: int = 0,
        periods_to_attend: int = 0,
        display_name: str | None = None,
    ) -> SubjectPeriodsSimulationResult:
        """
        Simulate missing and/or attending specific period counts for a single subject.
        """
        uid = UUID(str(student_id))
        student = await self.student_repo.get_by_id(uid)
        target = student.attendance_target if student and student.attendance_target else 75.0

        snapshot = await self._get_latest_snapshot(uid)
        if not snapshot:
            return SubjectPeriodsSimulationResult(
                available=False,
                subject_code=subject_code,
                subject_name=display_name,
                periods_missed=periods_to_miss,
                periods_attended=periods_to_attend,
                message="No verified attendance snapshot available to simulate.",
            )

        # Reconcile overall baseline
        (
            curr_att,
            curr_cond,
            curr_pct,
            _rec,
            _d,
            _st,
            _g,
        ) = reconcile_snapshot_overall(snapshot, target)

        now_utc = datetime.now(UTC)
        cap_at = snapshot.captured_at
        if cap_at.tzinfo is None:
            cap_at = cap_at.replace(tzinfo=UTC)
        age_hours = round(max(0.0, (now_utc - cap_at).total_seconds() / 3600.0), 1)

        # Match subject in snapshot
        target_code_norm = subject_code.strip().casefold()
        matched_sub = None
        for s in snapshot.subjects:
            if (
                s.subject_code.strip().casefold() == target_code_norm
                or (s.subject_name and s.subject_name.strip().casefold() == target_code_norm)
            ):
                matched_sub = s
                break

        if not matched_sub:
            return SubjectPeriodsSimulationResult(
                available=False,
                subject_code=subject_code,
                subject_name=display_name,
                periods_missed=periods_to_miss,
                periods_attended=periods_to_attend,
                message=f"Subject '{subject_code}' not found in your latest attendance snapshot.",
            )

        # Subject calculations
        s_curr_att = matched_sub.cumulative_attended
        s_curr_cond = matched_sub.cumulative_conducted
        s_curr_pct = round_percentage(calculate_percentage(s_curr_att, s_curr_cond))

        s_proj_att = s_curr_att + periods_to_attend
        s_proj_cond = s_curr_cond + periods_to_attend + periods_to_miss
        s_proj_pct = round_percentage(calculate_percentage(s_proj_att, s_proj_cond))
        s_is_safe = s_proj_pct >= target

        # Overall calculations
        o_proj_att = curr_att + periods_to_attend
        o_proj_cond = curr_cond + periods_to_attend + periods_to_miss
        o_proj_pct = round_percentage(calculate_percentage(o_proj_att, o_proj_cond))
        o_pct_change = round(o_proj_pct - curr_pct, 2)
        o_is_safe = o_proj_pct >= target

        return SubjectPeriodsSimulationResult(
            available=True,
            subject_code=matched_sub.subject_code,
            subject_name=matched_sub.subject_name or display_name,
            periods_missed=periods_to_miss,
            periods_attended=periods_to_attend,
            subject_current_attended=s_curr_att,
            subject_current_conducted=s_curr_cond,
            subject_current_percentage=s_curr_pct,
            subject_projected_attended=s_proj_att,
            subject_projected_conducted=s_proj_cond,
            subject_projected_percentage=s_proj_pct,
            subject_is_safe=s_is_safe,
            overall_current_attended=curr_att,
            overall_current_conducted=curr_cond,
            overall_current_percentage=curr_pct,
            overall_projected_attended=o_proj_att,
            overall_projected_conducted=o_proj_cond,
            overall_projected_percentage=o_proj_pct,
            overall_percentage_change=o_pct_change,
            overall_is_safe=o_is_safe,
            target_percentage=target,
            snapshot_captured_at=cap_at.isoformat(),
            snapshot_age_hours=age_hours,
        )

    async def _get_latest_snapshot(self, student_id: UUID) -> Any:
        for meth in (
            "get_latest_for_student_with_subjects",
            "get_latest_for_student",
            "get_latest",
        ):
            if hasattr(self.snapshot_repo, meth):
                fn = getattr(self.snapshot_repo, meth)
                res = await fn(student_id)
                if res is not None and isinstance(getattr(res, "overall_attended", None), int):
                    return res
        return None

    async def _get_confirmed_timetable(self, student_id: UUID) -> Any:
        from app.models.timetable import TimetableStatus

        candidates = [
            ("get_confirmed_for_student", (student_id,)),
            ("get_latest_confirmed_for_student", (student_id,)),
            ("get_latest_for_student", (student_id, TimetableStatus.CONFIRMED)),
            ("get_active", (student_id,)),
        ]
        for meth, args in candidates:
            if hasattr(self.timetable_repo, meth):
                fn = getattr(self.timetable_repo, meth)
                res = await fn(*args)
                if res is not None and isinstance(getattr(res, "entries", None), (list, tuple, set)):
                    return res
        return None

    async def _get_timetable_entries(self, timetable: Any) -> list:
        if hasattr(timetable, "entries") and isinstance(timetable.entries, (list, tuple, set)):
            return list(timetable.entries)
        if hasattr(self.timetable_repo, "get_entries_for_timetable"):
            entries = await self.timetable_repo.get_entries_for_timetable(timetable.id)
            if entries and isinstance(entries, (list, tuple, set)):
                return list(entries)
        if hasattr(self.timetable_repo, "get_entries"):
            entries = await self.timetable_repo.get_entries(timetable.id)
            if entries and isinstance(entries, (list, tuple, set)):
                return list(entries)
        if hasattr(self.timetable_repo, "get_for_timetable"):
            entries = await self.timetable_repo.get_for_timetable(timetable.id)
            if entries and isinstance(entries, (list, tuple, set)):
                return list(entries)
        return []
