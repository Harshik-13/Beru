"""
Deterministic attendance simulation service.

Provides high-precision projections for future attendance without modifying
any database records and without interacting with the Doctus portal sync pipeline.
All calculations are pure mathematical projections over verified local snapshots
and confirmed timetable records.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import inspect
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
    ResolvedSessionAction,
    SimulationAction,
)
from app.models.timetable import ActivityType, LabBatch, Timetable, TimetableEntry

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SubjectSimulationDelta:
    """Projected change for an individual course."""

    subject_code: str
    subject_name: str | None
    current_attended: int
    current_conducted: int
    current_percentage: float
    projected_attended: int
    projected_conducted: int
    projected_percentage: float
    periods_in_scenario: int
    periods_attended: int
    periods_missed: int
    target_percentage: float
    is_safe: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_code": self.subject_code,
            "subject_name": self.subject_name,
            "current_attended": self.current_attended,
            "current_conducted": self.current_conducted,
            "current_percentage": self.current_percentage,
            "projected_attended": self.projected_attended,
            "projected_conducted": self.projected_conducted,
            "projected_percentage": self.projected_percentage,
            "periods_in_scenario": self.periods_in_scenario,
            "periods_attended": self.periods_attended,
            "periods_missed": self.periods_missed,
            "target_percentage": self.target_percentage,
            "is_safe": self.is_safe,
        }


@dataclass(frozen=True, slots=True)
class ScheduleSimulationResult:
    """Result of simulating arbitrary dates, ranges, or mixed actions."""

    available: bool
    scenario_dates: list[str] = None  # type: ignore
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
    critical_breaches: list[str] = None  # type: ignore
    subject_breakdown: list[SubjectSimulationDelta] = None  # type: ignore
    snapshot_captured_at: str | None = None
    snapshot_age_hours: float | None = None
    message: str | None = None

    def __post_init__(self):
        if self.scenario_dates is None:
            object.__setattr__(self, "scenario_dates", [])
        if self.critical_breaches is None:
            object.__setattr__(self, "critical_breaches", [])
        if self.subject_breakdown is None:
            object.__setattr__(self, "subject_breakdown", [])

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
        student_repo: Any = None,
        entry_repo: Any = None,
    ):
        self.session = session
        self.snapshot_repo = snapshot_repo
        self.timetable_repo = timetable_repo
        self.student_repo = student_repo
        self.entry_repo = entry_repo

    async def simulate_schedule_scenario(
        self,
        scenario: ResolvedScenario,
    ) -> ScheduleSimulationResult:
        """
        Simulate attendance impact for a resolved scenario.

        Enforces Directive 3:
        After scenario resolution, the simulation engine operates solely over
        ResolvedSessionAction records (date, period, course_code, action=ATTEND|SKIP).
        """
        uid = scenario.student_id
        student = await self.student_repo.get_by_id(uid)
        target = student.attendance_target if student and student.attendance_target else 75.0

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

        # 3. Pure deterministic session-level delta calculation
        delta_att_by_code: dict[str, int] = {}
        delta_cond_by_code: dict[str, int] = {}
        periods_missed_by_code: dict[str, int] = {}
        periods_attended_by_code: dict[str, int] = {}

        total_scheduled_periods = len(scenario.session_actions)

        for session in scenario.session_actions:
            key = (session.course_code or session.activity_name or "Unknown").strip().upper()
            delta_cond_by_code[key] = delta_cond_by_code.get(key, 0) + 1
            if session.action == SimulationAction.ATTEND:
                delta_att_by_code[key] = delta_att_by_code.get(key, 0) + 1
                periods_attended_by_code[key] = periods_attended_by_code.get(key, 0) + 1
            else:
                periods_missed_by_code[key] = periods_missed_by_code.get(key, 0) + 1

        total_delta_att = sum(delta_att_by_code.values())
        total_delta_cond = sum(delta_cond_by_code.values())

        # 4. Overall projected calculations
        proj_att = curr_att + total_delta_att
        proj_cond = curr_cond + total_delta_cond
        proj_pct = round_percentage(calculate_percentage(proj_att, proj_cond))
        pct_change = round(proj_pct - curr_pct, 2)
        overall_safe = proj_pct >= target

        # 5. Calculate per-subject breakdown & critical breaches
        subject_breakdown: list[SubjectSimulationDelta] = []
        critical_breaches: list[str] = []

        # Build timetable mapping for display names
        confirmed_tt = await self._get_confirmed_timetable(uid)
        entries = await self._get_timetable_entries(confirmed_tt) if confirmed_tt else []
        tt_mapping: dict[str, str] = {}
        for e in entries:
            c = (e.course_code or "").strip().upper()
            n = (e.activity_name or "").strip()
            if c and n:
                tt_mapping[c] = n

        # Process subjects in snapshot
        matched_keys: set[str] = set()

        for s in snapshot.subjects:
            s_code = s.subject_code.strip().upper()
            s_curr_att = s.cumulative_attended
            s_curr_cond = s.cumulative_conducted
            s_curr_pct = round_percentage(s.cumulative_percentage())

            # Match delta by subject code or mapped name
            matched_delta_att = 0
            matched_delta_cond = 0
            matched_periods_att = 0
            matched_periods_miss = 0

            for k in delta_cond_by_code.keys():
                if k == s_code or (s.subject_name and k == s.subject_name.strip().upper()):
                    matched_delta_att += delta_att_by_code.get(k, 0)
                    matched_delta_cond += delta_cond_by_code.get(k, 0)
                    matched_periods_att += periods_attended_by_code.get(k, 0)
                    matched_periods_miss += periods_missed_by_code.get(k, 0)
                    matched_keys.add(k)

            s_proj_att = s_curr_att + matched_delta_att
            s_proj_cond = s_curr_cond + matched_delta_cond
            s_proj_pct = round_percentage(calculate_percentage(s_proj_att, s_proj_cond))
            s_is_safe = s_proj_pct >= target

            display_name = s.subject_name or tt_mapping.get(s_code) or s.subject_code

            if not s_is_safe and matched_delta_cond > 0:
                critical_breaches.append(
                    f"{display_name}: drops to {s_proj_pct:.1f}% ({s_proj_att}/{s_proj_cond}), below target of {target:.0f}%"
                )

            subject_breakdown.append(
                SubjectSimulationDelta(
                    subject_code=s.subject_code,
                    subject_name=display_name,
                    current_attended=s_curr_att,
                    current_conducted=s_curr_cond,
                    current_percentage=s_curr_pct,
                    projected_attended=s_proj_att,
                    projected_conducted=s_proj_cond,
                    projected_percentage=s_proj_pct,
                    periods_in_scenario=matched_delta_cond,
                    periods_attended=matched_periods_att,
                    periods_missed=matched_periods_miss,
                    target_percentage=target,
                    is_safe=s_is_safe,
                )
            )

        # Include any timetable subjects not yet present in snapshot
        for k, cond_count in delta_cond_by_code.items():
            if k not in matched_keys:
                att_count = delta_att_by_code.get(k, 0)
                miss_count = periods_missed_by_code.get(k, 0)
                proj_pct_new = round_percentage(calculate_percentage(att_count, cond_count))
                display_name = tt_mapping.get(k, k)
                is_safe_new = proj_pct_new >= target
                if not is_safe_new:
                    critical_breaches.append(
                        f"{display_name}: drops to {proj_pct_new:.1f}% ({att_count}/{cond_count}), below target of {target:.0f}%"
                    )
                subject_breakdown.append(
                    SubjectSimulationDelta(
                        subject_code=k,
                        subject_name=display_name,
                        current_attended=0,
                        current_conducted=0,
                        current_percentage=0.0,
                        projected_attended=att_count,
                        projected_conducted=cond_count,
                        projected_percentage=proj_pct_new,
                        periods_in_scenario=cond_count,
                        periods_attended=att_count,
                        periods_missed=miss_count,
                        target_percentage=target,
                        is_safe=is_safe_new,
                    )
                )

        subjects_safe = len(critical_breaches) == 0
        is_safe = overall_safe and subjects_safe

        scenario_dates_str = [d.strftime("%Y-%m-%d") for d in scenario.dates]
        notes_str = "; ".join(scenario.notes) if scenario.notes else None

        return ScheduleSimulationResult(
            available=True,
            scenario_dates=scenario_dates_str,
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
            message=notes_str,
        )

    async def simulate_subject_periods(
        self,
        student_id: UUID | str,
        subject_query: str | None = None,
        periods_to_miss: int = 0,
        periods_to_attend: int = 0,
        subject_code: str | None = None,
        display_name: str | None = None,
    ) -> SubjectPeriodsSimulationResult:
        """
        Simulate missing or attending arbitrary period counts for a specific subject.
        """
        uid = UUID(str(student_id))
        student = None
        if self.student_repo is not None:
            raw_student = self.student_repo.get_by_id(uid)
            student = await raw_student if inspect.isawaitable(raw_student) else raw_student
        target = student.attendance_target if student and getattr(student, "attendance_target", None) else 75.0

        query_key = subject_code or subject_query or ""
        resolved_display = display_name

        # 1. Fetch latest local snapshot (zero portal calls)
        snapshot = await self._get_latest_snapshot(uid)
        if not snapshot:
            return SubjectPeriodsSimulationResult(
                available=False,
                subject_code=query_key,
                subject_name=resolved_display,
                periods_missed=periods_to_miss,
                periods_attended=periods_to_attend,
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

        now_utc = datetime.now(UTC)
        cap_at = snapshot.captured_at
        if cap_at.tzinfo is None:
            cap_at = cap_at.replace(tzinfo=UTC)
        age_hours = round(max(0.0, (now_utc - cap_at).total_seconds() / 3600.0), 1)

        # 3. Subject matching
        clean_query = query_key.strip().casefold()
        matched_sub = None

        for s in snapshot.subjects:
            if s.subject_code.strip().casefold() == clean_query:
                matched_sub = s
                break
            if s.subject_name and s.subject_name.strip().casefold() == clean_query:
                matched_sub = s
                break

        confirmed_tt = await self._get_confirmed_timetable(uid)
        entries = await self._get_timetable_entries(confirmed_tt) if confirmed_tt else []

        if not matched_sub:
            for e in entries:
                c = (e.course_code or "").strip()
                n = (e.activity_name or "").strip()
                if c.casefold() == clean_query or n.casefold() == clean_query:
                    if not resolved_display:
                        resolved_display = n or c
                    for s in snapshot.subjects:
                        if s.subject_code.strip().upper() == c.upper():
                            matched_sub = s
                            break
                    break

        if not matched_sub:
            for s in snapshot.subjects:
                words = (s.subject_name or s.subject_code).split()
                acronym = "".join(w[0] for w in words if w).casefold()
                if clean_query == acronym or clean_query in (s.subject_name or "").casefold():
                    matched_sub = s
                    break

        if not matched_sub:
            return SubjectPeriodsSimulationResult(
                available=False,
                subject_code=subject_query,
                subject_name=None,
                periods_missed=periods_to_miss,
                periods_attended=periods_to_attend,
                message=f"Could not find course '{subject_query}' in your attendance snapshot.",
            )

        s_curr_att = matched_sub.cumulative_attended
        s_curr_cond = matched_sub.cumulative_conducted
        s_curr_pct = round_percentage(matched_sub.cumulative_percentage())

        s_proj_att = s_curr_att + periods_to_attend
        s_proj_cond = s_curr_cond + periods_to_attend + periods_to_miss
        s_proj_pct = round_percentage(calculate_percentage(s_proj_att, s_proj_cond))
        s_is_safe = s_proj_pct >= target

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
                try:
                    res = fn(student_id)
                    res = await res if inspect.isawaitable(res) else res
                    if res is not None and isinstance(getattr(res, "overall_attended", None), int):
                        return res
                except Exception:
                    continue
        return None

    async def _get_confirmed_timetable(self, student_id: UUID) -> Any:
        from app.models.timetable import TimetableStatus

        candidates = [
            ("get_latest_confirmed_for_student", (student_id,)),
            ("get_confirmed_for_student", (student_id,)),
            ("get_latest_for_student", (student_id, TimetableStatus.CONFIRMED)),
            ("get_active", (student_id,)),
        ]
        for meth, args in candidates:
            if hasattr(self.timetable_repo, meth):
                fn = getattr(self.timetable_repo, meth)
                try:
                    res = fn(*args)
                    res = await res if inspect.isawaitable(res) else res
                    if res is not None:
                        status = getattr(res, "status", None)
                        if status in (TimetableStatus.CONFIRMED, "CONFIRMED", "confirmed") or (hasattr(res, "id") and hasattr(res, "student_id")):
                            return res
                except Exception:
                    continue
        return None

    async def _get_timetable_entries(self, timetable: Any) -> list:
        if self.entry_repo is not None:
            fn = getattr(self.entry_repo, "get_for_timetable", None) or getattr(self.entry_repo, "get_entries_for_timetable", None)
            if fn is not None:
                try:
                    res = fn(timetable.id)
                    entries = await res if inspect.isawaitable(res) else res
                    if isinstance(entries, (list, tuple, set)):
                        return list(entries)
                except Exception:
                    pass

        if hasattr(timetable, "entries") and isinstance(timetable.entries, (list, tuple, set)):
            return list(timetable.entries)

        if hasattr(self.timetable_repo, "get_entries_for_timetable"):
            try:
                res = self.timetable_repo.get_entries_for_timetable(timetable.id)
                entries = await res if inspect.isawaitable(res) else res
                if isinstance(entries, (list, tuple, set)):
                    return list(entries)
            except Exception:
                pass

        return []
