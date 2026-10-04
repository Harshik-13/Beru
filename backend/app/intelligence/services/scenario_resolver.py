"""
Scenario resolver for attendance and bunk simulations.

Decouples natural language date/action interpretation from deterministic
attendance mathematics. Resolves explicit dates, relative instructional day
sequences, mixed actions, and subject references into a validated, canonical
ResolvedScenario DTO.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import enum
import logging
from typing import Any
from uuid import UUID
import zoneinfo

from app.models.timetable import ActivityType, LabBatch, Timetable, TimetableEntry

logger = logging.getLogger(__name__)


class SimulationAction(str, enum.Enum):
    """Action to simulate for a given date or period."""

    ATTEND = "ATTEND"
    SKIP = "SKIP"


class ScenarioResolutionError(Exception):
    """Base exception for scenario resolution errors."""

    pass


class ScenarioConflictError(ScenarioResolutionError):
    """Raised when the exact same canonical date has opposing actions (ATTEND and SKIP)."""

    def __init__(self, conflicting_date: date, message: str | None = None):
        self.conflicting_date = conflicting_date
        msg = (
            message
            or f"Conflicting actions requested for {conflicting_date.strftime('%A, %d %b %Y')}: "
            f"cannot both ATTEND and SKIP on the same date."
        )
        super().__init__(msg)


class LabBatchAmbiguityError(ScenarioResolutionError):
    """Raised when a scheduled session requires a specific lab batch, but student's batch is UNKNOWN."""

    def __init__(self, target_date: date, day_name: str, activity_name: str):
        self.target_date = target_date
        self.day_name = day_name
        self.activity_name = activity_name
        msg = (
            f"Your timetable has divided lab batches for '{activity_name}' on "
            f"{day_name} ({target_date.strftime('%d %b')}), but your profile lab batch is UNKNOWN. "
            f"Please set your lab batch (Batch 1 or Batch 2) first so I can simulate the exact classes."
        )
        super().__init__(msg)


class SubjectNotFoundError(ScenarioResolutionError):
    """Raised when a subject query cannot be mapped to confirmed timetable entries."""

    def __init__(self, subject_query: str):
        self.subject_query = subject_query
        super().__init__(
            f"No course or subject matching '{subject_query}' was found in your confirmed timetable."
        )


class NoConfirmedTimetableError(ScenarioResolutionError):
    """Raised when a student has no confirmed timetable."""

    def __init__(self):
        super().__init__(
            "No confirmed timetable found. Please upload and confirm your timetable "
            "before simulating attendance scenarios."
        )


@dataclass(frozen=True, slots=True)
class ResolvedDayAction:
    """Canonical day action pair."""

    date: date
    action: SimulationAction
    day_name: str


@dataclass(frozen=True, slots=True)
class ResolvedScenario:
    """Complete, validated simulation scenario ready for mathematical execution."""

    student_id: UUID
    actions: tuple[ResolvedDayAction, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def dates(self) -> tuple[date, ...]:
        return tuple(a.date for a in self.actions)


class ScenarioResolver:
    """
    Resolves natural language days, relative sequences, and subject queries
    into canonical, conflict-checked simulation structures.
    """

    WEEKDAY_MAP = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }

    def __init__(
        self,
        timetable_repo: Any,
        student_repo: Any,
    ):
        self.timetable_repo = timetable_repo
        self.student_repo = student_repo

    async def resolve_scenario(
        self,
        student_id: UUID | str,
        days_to_skip: list[str] | None = None,
        days_to_attend: list[str] | None = None,
        skip_next_n_days: int | None = None,
        attend_next_n_days: int | None = None,
        custom_today: date | None = None,
    ) -> ResolvedScenario:
        """
        Resolve natural language and relative inputs into a verified ResolvedScenario.

        Enforces:
        - Exact upcoming chronological weekday resolution in student's timezone.
        - Instructional day sequence scanning (counting any day with timetable classes, including Sundays/Saturdays).
        - Conflict validation: rejects same date with opposing actions.
        - Deduplication: redundant dates for the same action are unified.
        - Lab batch ambiguity defense: blocks simulation if an UNKNOWN student faces divided lab sessions.
        """
        uid = UUID(str(student_id))
        student = await self.student_repo.get_by_id(uid)
        tz_name = student.timezone if student and student.timezone else "Asia/Kolkata"
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            tz = zoneinfo.ZoneInfo("Asia/Kolkata")

        today_dt = custom_today or datetime.now(tz).date()
        student_batch = student.lab_batch if student else LabBatch.UNKNOWN

        # Fetch confirmed timetable
        confirmed_tt = await self._get_confirmed_timetable(uid)
        if not confirmed_tt:
            raise NoConfirmedTimetableError()

        entries = await self._get_timetable_entries(confirmed_tt)

        # Intermediate action map: {canonical_date: set of actions requested}
        date_action_requests: dict[date, set[SimulationAction]] = {}

        # 1. Resolve explicit days to skip
        if days_to_skip:
            for item in days_to_skip:
                d = self._parse_date_string(item, today_dt)
                if d:
                    date_action_requests.setdefault(d, set()).add(SimulationAction.SKIP)

        # 2. Resolve explicit days to attend
        if days_to_attend:
            for item in days_to_attend:
                d = self._parse_date_string(item, today_dt)
                if d:
                    date_action_requests.setdefault(d, set()).add(SimulationAction.ATTEND)

        # 3. Resolve relative instructional day counts (e.g. "skip next 3 days")
        if skip_next_n_days and skip_next_n_days > 0:
            instructional_dates = self._find_next_n_instructional_dates(
                today_dt=today_dt,
                entries=entries,
                student_batch=student_batch,
                count=skip_next_n_days,
            )
            for d in instructional_dates:
                date_action_requests.setdefault(d, set()).add(SimulationAction.SKIP)

        if attend_next_n_days and attend_next_n_days > 0:
            instructional_dates = self._find_next_n_instructional_dates(
                today_dt=today_dt,
                entries=entries,
                student_batch=student_batch,
                count=attend_next_n_days,
            )
            for d in instructional_dates:
                date_action_requests.setdefault(d, set()).add(SimulationAction.ATTEND)

        if not date_action_requests:
            return ResolvedScenario(student_id=uid, actions=())

        # 4. Conflict detection & deduplication
        resolved_actions_list: list[ResolvedDayAction] = []
        for d in sorted(date_action_requests.keys()):
            actions = date_action_requests[d]
            if len(actions) > 1:
                # Same canonical date has both ATTEND and SKIP
                raise ScenarioConflictError(d)

            action = next(iter(actions))

            # 5. Lab batch ambiguity verification for this date
            self._validate_lab_batch_ambiguity(
                target_date=d,
                entries=entries,
                student_batch=student_batch,
            )

            resolved_actions_list.append(
                ResolvedDayAction(
                    date=d,
                    action=action,
                    day_name=d.strftime("%A"),
                )
            )

        return ResolvedScenario(
            student_id=uid,
            actions=tuple(resolved_actions_list),
        )

    def _parse_date_string(self, text: str, today_dt: date) -> date | None:
        """Parse natural language weekday, relative word, or ISO date string."""
        clean = text.strip().casefold()
        if not clean:
            return None

        if clean == "today":
            return today_dt
        if clean == "tomorrow":
            return today_dt + timedelta(days=1)

        # Check weekday names (e.g. "monday", "tuesday")
        if clean in self.WEEKDAY_MAP:
            target_idx = self.WEEKDAY_MAP[clean]
            diff = (target_idx - today_dt.weekday()) % 7
            # If diff == 0, it means today is that weekday; resolve to upcoming next occurrence (7 days)
            return today_dt + timedelta(days=7 if diff == 0 else diff)

        # Attempt ISO YYYY-MM-DD
        try:
            return date.fromisoformat(clean)
        except ValueError:
            pass

        # Attempt common date formats like "06-10-2026", "2026/10/06"
        for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(clean, fmt).date()
            except ValueError:
                continue

        logger.warning("Unrecognized date format in simulation request: '%s'", text)
        return None

    def _find_next_n_instructional_dates(
        self,
        today_dt: date,
        entries: list[TimetableEntry],
        student_batch: LabBatch,
        count: int,
    ) -> list[date]:
        """
        Scan forward starting from tomorrow and gather the next N dates that have
        at least one instructional session scheduled in the confirmed timetable.
        Does not assume Sunday is non-working; if Sunday has classes scheduled, it counts.
        """
        instructional_dates: list[date] = []
        curr = today_dt + timedelta(days=1)
        max_scan_days = 90  # Avoid runaway loop if timetable is empty

        while len(instructional_dates) < count and (curr - today_dt).days <= max_scan_days:
            weekday = curr.weekday()
            # Find instructional entries for this weekday
            day_entries = [
                e
                for e in entries
                if e.day_of_week == weekday
                and e.activity_type != ActivityType.BREAK
            ]

            # If student has a known batch, filter out other batches
            if student_batch != LabBatch.UNKNOWN:
                day_entries = [
                    e
                    for e in day_entries
                    if e.lab_batch is None
                    or e.lab_batch == LabBatch.UNKNOWN
                    or e.lab_batch == student_batch
                ]

            if day_entries:
                instructional_dates.append(curr)

            curr += timedelta(days=1)

        return instructional_dates

    def _validate_lab_batch_ambiguity(
        self,
        target_date: date,
        entries: list[TimetableEntry],
        student_batch: LabBatch,
    ) -> None:
        """
        Check if any scheduled session on target_date requires a specific lab batch
        while the student's batch is UNKNOWN.
        """
        if student_batch != LabBatch.UNKNOWN:
            return

        weekday = target_date.weekday()
        for e in entries:
            if e.day_of_week != weekday:
                continue
            if e.activity_type == ActivityType.BREAK:
                continue
            # If an entry specifies batch_1 or batch_2, student's UNKNOWN batch is ambiguous
            if e.lab_batch in (LabBatch.BATCH_1, LabBatch.BATCH_2):
                raise LabBatchAmbiguityError(
                    target_date=target_date,
                    day_name=target_date.strftime("%A"),
                    activity_name=e.activity_name or (e.course_code or "Lab"),
                )

    async def resolve_subject_query(
        self,
        student_id: UUID | str,
        subject_query: str,
    ) -> tuple[str, str]:
        """
        Resolve a natural-language subject query (e.g. 'OS', 'Operating Systems', '25PC1CS204')
        against the student's confirmed timetable.

        Returns:
            (course_code, display_name)
        """
        uid = UUID(str(student_id))
        confirmed_tt = await self._get_confirmed_timetable(uid)
        if not confirmed_tt:
            raise NoConfirmedTimetableError()

        entries = await self._get_timetable_entries(confirmed_tt)

        clean_query = subject_query.strip().casefold()

        # Build map of unique courses from timetable entries
        courses: dict[str, str] = {}
        for e in entries:
            code = (e.course_code or "").strip()
            name = (e.activity_name or "").strip()
            if code and name:
                courses[code] = name
            elif code:
                courses[code] = code
            elif name:
                courses[name] = name

        # 1. Exact match on course_code or name
        for code, name in courses.items():
            if clean_query == code.casefold():
                return code, name
            if clean_query == name.casefold():
                return code, name

        # 2. Substring / acronym match (e.g. "OS" in "Operating Systems")
        for code, name in courses.items():
            words = name.split()
            acronym = "".join(w[0] for w in words if w).casefold()
            if clean_query == acronym:
                return code, name
            if clean_query in code.casefold() or clean_query in name.casefold():
                return code, name

        raise SubjectNotFoundError(subject_query)

    async def _get_confirmed_timetable(self, uid: UUID) -> Any:
        from app.models.timetable import TimetableStatus

        candidates = [
            ("get_confirmed_for_student", (uid,)),
            ("get_latest_confirmed_for_student", (uid,)),
            ("get_latest_for_student", (uid, TimetableStatus.CONFIRMED)),
            ("get_active", (uid,)),
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
