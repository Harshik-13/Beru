"""
Scenario resolver for attendance and bunk simulations.

Decouples natural language date/action interpretation from deterministic
attendance mathematics. Resolves explicit dates, relative instructional day
sequences, mixed actions, partial-day / ordinal period requests, and subject
references into a validated, canonical ResolvedScenario containing pure
ResolvedSessionAction records.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import enum
import inspect
import logging
from typing import Any
from uuid import UUID
import zoneinfo

from app.models.timetable import ActivityType, LabBatch, Timetable, TimetableEntry

logger = logging.getLogger(__name__)


class SimulationAction(str, enum.Enum):
    """Action to simulate for a given session, period, or date."""

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


class SessionConflictError(ScenarioResolutionError):
    """Raised when the exact same scheduled session has conflicting actions."""

    def __init__(self, message: str):
        super().__init__(message)


class InvalidSessionCountError(ScenarioResolutionError):
    """Raised when a partial-day simulation request exceeds available sessions or specifies invalid bounds."""

    def __init__(self, message: str):
        super().__init__(message)


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
class PartialDayRequest:
    """Canonical request for partial-day / ordinal period absence or attendance."""

    date: str  # "Monday", "tomorrow", "2026-10-05"
    skip_first_n_periods: int | None = None
    skip_last_n_periods: int | None = None
    periods_to_skip: tuple[int, ...] | None = None  # 1-indexed, e.g. (1, 2, 3)
    periods_to_attend: tuple[int, ...] | None = None  # 1-indexed
    attend_remaining: bool = True


@dataclass(frozen=True, slots=True)
class ResolvedSessionAction:
    """Canonical session action representing a single scheduled instructional period."""

    date: date
    period_index: int  # 1-indexed within the day
    course_code: str
    activity_name: str | None
    start_time: time
    end_time: time
    action: SimulationAction  # ATTEND or SKIP


@dataclass(frozen=True, slots=True)
class ResolvedDayAction:
    """Canonical day action pair (kept for backward compatibility)."""

    date: date
    action: SimulationAction
    day_name: str


@dataclass(frozen=True, slots=True)
class ResolvedScenario:
    """Complete, validated simulation scenario ready for mathematical execution."""

    student_id: UUID
    session_actions: tuple[ResolvedSessionAction, ...]
    actions: tuple[ResolvedDayAction, ...] = field(default_factory=tuple)
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def dates(self) -> tuple[date, ...]:
        return tuple(sorted({s.date for s in self.session_actions}))


class ScenarioResolver:
    """
    Resolves natural language days, relative sequences, partial-day periods,
    and subject queries into canonical, conflict-checked ResolvedSessionAction items.
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
        student_repo: Any = None,
        entry_repo: Any = None,
    ):
        self.timetable_repo = timetable_repo
        self.student_repo = student_repo
        self.entry_repo = entry_repo

    async def resolve_scenario(
        self,
        student_id: UUID | str,
        days_to_skip: list[str] | None = None,
        days_to_attend: list[str] | None = None,
        skip_next_n_days: int | None = None,
        attend_next_n_days: int | None = None,
        partial_day_scenarios: list[dict | PartialDayRequest] | None = None,
        custom_today: date | None = None,
    ) -> ResolvedScenario:
        """
        Resolve natural language, relative, and partial-day inputs into a verified ResolvedScenario.

        Enforces:
        - Exact upcoming chronological weekday resolution in student's timezone.
        - Instructional day sequence scanning (counting any day with timetable classes).
        - Conflict validation: rejects same date or same session with opposing actions.
        - Deduplication: redundant dates for the same action are unified.
        - Lab batch ambiguity defense: blocks simulation if an UNKNOWN student faces divided lab sessions.
        - Partial-day validation: verifies requested period counts against actual scheduled periods.
        - Pure session-action output: returns canonical ResolvedSessionAction records.
        """
        uid = UUID(str(student_id))
        student = None
        if self.student_repo is not None:
            raw_student = self.student_repo.get_by_id(uid)
            student = await raw_student if inspect.isawaitable(raw_student) else raw_student
        tz_name = student.timezone if student and getattr(student, "timezone", None) else "Asia/Kolkata"
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            tz = zoneinfo.ZoneInfo("Asia/Kolkata")

        today_dt = custom_today or datetime.now(tz).date()
        student_batch = student.lab_batch if student else LabBatch.UNKNOWN

        # Fetch confirmed timetable and entries
        confirmed_tt = await self._get_confirmed_timetable(uid)
        if not confirmed_tt:
            raise NoConfirmedTimetableError()

        entries = await self._get_timetable_entries(confirmed_tt)

        # 1. Resolve whole-day requests: {canonical_date: set of actions requested}
        date_action_requests: dict[date, set[SimulationAction]] = {}

        if days_to_skip:
            for item in days_to_skip:
                d = self._parse_date_string(item, today_dt)
                if d:
                    date_action_requests.setdefault(d, set()).add(SimulationAction.SKIP)

        if days_to_attend:
            for item in days_to_attend:
                d = self._parse_date_string(item, today_dt)
                if d:
                    date_action_requests.setdefault(d, set()).add(SimulationAction.ATTEND)

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

        # Whole-day conflict detection
        for d, actions in date_action_requests.items():
            if len(actions) > 1:
                raise ScenarioConflictError(d)

        # 2. Parse and validate partial-day requests
        parsed_partial_reqs: list[PartialDayRequest] = []
        if partial_day_scenarios:
            for p in partial_day_scenarios:
                if isinstance(p, PartialDayRequest):
                    parsed_partial_reqs.append(p)
                elif isinstance(p, dict):
                    parsed_partial_reqs.append(
                        PartialDayRequest(
                            date=str(p.get("date", "")),
                            skip_first_n_periods=p.get("skip_first_n_periods"),
                            skip_last_n_periods=p.get("skip_last_n_periods"),
                            periods_to_skip=tuple(p["periods_to_skip"]) if p.get("periods_to_skip") else None,
                            periods_to_attend=tuple(p["periods_to_attend"]) if p.get("periods_to_attend") else None,
                            attend_remaining=p.get("attend_remaining", True),
                        )
                    )

        # Ensure no date is requested as both whole-day and partial-day
        for p in parsed_partial_reqs:
            p_date = self._parse_date_string(p.date, today_dt)
            if p_date and p_date in date_action_requests:
                raise ScenarioConflictError(
                    p_date,
                    f"Conflicting actions requested for {p_date.strftime('%A, %d %b %Y')}: "
                    f"cannot specify both whole-day action and partial-day actions on the same date.",
                )

        if not date_action_requests and not parsed_partial_reqs:
            return ResolvedScenario(student_id=uid, session_actions=(), actions=())

        # 3. Build pure ResolvedSessionAction collection
        session_actions_list: list[ResolvedSessionAction] = []
        day_actions_list: list[ResolvedDayAction] = []
        notes_list: list[str] = []

        # Process whole-day actions
        for d in sorted(date_action_requests.keys()):
            act = next(iter(date_action_requests[d]))
            self._validate_lab_batch_ambiguity(
                target_date=d,
                entries=entries,
                student_batch=student_batch,
            )
            day_sessions = self._get_sessions_for_date(d, entries, student_batch)
            for idx, s in enumerate(day_sessions, 1):
                session_actions_list.append(
                    ResolvedSessionAction(
                        date=d,
                        period_index=idx,
                        course_code=(s.course_code or s.activity_name or "Course").strip(),
                        activity_name=s.activity_name,
                        start_time=s.start_time,
                        end_time=s.end_time,
                        action=act,
                    )
                )
            day_actions_list.append(
                ResolvedDayAction(
                    date=d,
                    action=act,
                    day_name=d.strftime("%A"),
                )
            )

        # Process partial-day actions
        for req in parsed_partial_reqs:
            d = self._parse_date_string(req.date, today_dt)
            if not d:
                continue
            self._validate_lab_batch_ambiguity(
                target_date=d,
                entries=entries,
                student_batch=student_batch,
            )
            partial_sessions, note = self._resolve_partial_day_sessions(d, req, entries, student_batch)
            session_actions_list.extend(partial_sessions)
            if note:
                notes_list.append(note)

        # 4. Strict session conflict check: Ensure no session is both ATTEND and SKIP
        seen_sessions: dict[tuple[date, int], SimulationAction] = {}
        for sa in session_actions_list:
            key = (sa.date, sa.period_index)
            if key in seen_sessions:
                if seen_sessions[key] != sa.action:
                    raise SessionConflictError(
                        f"Conflicting actions requested for period {sa.period_index} on {sa.date.strftime('%A, %d %b %Y')}: "
                        f"cannot both ATTEND and SKIP."
                    )
            else:
                seen_sessions[key] = sa.action

        return ResolvedScenario(
            student_id=uid,
            session_actions=tuple(session_actions_list),
            actions=tuple(day_actions_list),
            notes=tuple(notes_list),
        )

    def _get_sessions_for_date(
        self,
        target_date: date,
        entries: list[TimetableEntry],
        student_batch: LabBatch,
    ) -> list[TimetableEntry]:
        """Get scheduled instructional sessions for date, sorted by start time."""
        weekday = target_date.weekday()
        day_entries = [
            e for e in entries
            if e.day_of_week == weekday and e.activity_type != ActivityType.BREAK
        ]
        if student_batch != LabBatch.UNKNOWN:
            day_entries = [
                e for e in day_entries
                if e.lab_batch is None
                or e.lab_batch == LabBatch.UNKNOWN
                or e.lab_batch == student_batch
            ]
        return sorted(day_entries, key=lambda e: e.start_time)

    def _resolve_partial_day_sessions(
        self,
        target_date: date,
        req: PartialDayRequest,
        entries: list[TimetableEntry],
        student_batch: LabBatch,
    ) -> tuple[list[ResolvedSessionAction], str | None]:
        """
        Validate and resolve partial-day requests into ResolvedSessionAction items.

        Enforces Directive 4:
        - If Monday has 2 classes and user asks to skip first 3: raises InvalidSessionCountError.
        - Validates N > 0.
        - Validates requested period indices exist.
        - Detects same-session conflicts.
        """
        day_sessions = self._get_sessions_for_date(target_date, entries, student_batch)
        total_sessions = len(day_sessions)
        day_label = target_date.strftime("%A")

        if total_sessions == 0:
            raise InvalidSessionCountError(
                f"{day_label} ({target_date.strftime('%d %b')}) has no scheduled classes to simulate."
            )

        skip_indices: set[int] = set()
        attend_indices: set[int] = set()

        # 1. Validate skip_first_n_periods
        if req.skip_first_n_periods is not None:
            if req.skip_first_n_periods <= 0:
                raise InvalidSessionCountError("Number of periods to skip must be greater than zero.")
            if req.skip_first_n_periods > total_sessions:
                raise InvalidSessionCountError(
                    f"{day_label} has only {total_sessions} scheduled classes, so I cannot skip the first "
                    f"{req.skip_first_n_periods} as requested."
                )
            skip_indices.update(range(1, req.skip_first_n_periods + 1))

        # 2. Validate skip_last_n_periods
        if req.skip_last_n_periods is not None:
            if req.skip_last_n_periods <= 0:
                raise InvalidSessionCountError("Number of periods to skip must be greater than zero.")
            if req.skip_last_n_periods > total_sessions:
                raise InvalidSessionCountError(
                    f"{day_label} has only {total_sessions} scheduled classes, so I cannot skip the last "
                    f"{req.skip_last_n_periods} as requested."
                )
            skip_indices.update(range(total_sessions - req.skip_last_n_periods + 1, total_sessions + 1))

        # 3. Validate explicit periods_to_skip
        if req.periods_to_skip:
            for p in req.periods_to_skip:
                if p <= 0 or p > total_sessions:
                    raise InvalidSessionCountError(
                        f"{day_label} has only {total_sessions} scheduled classes, but period {p} was requested."
                    )
                skip_indices.add(p)

        # 4. Validate explicit periods_to_attend
        if req.periods_to_attend:
            for p in req.periods_to_attend:
                if p in skip_indices:
                    raise SessionConflictError(
                        f"Conflicting actions requested for period {p} on {target_date.strftime('%A, %d %b %Y')}: "
                        f"cannot both ATTEND and SKIP."
                    )
                if p <= 0 or p > total_sessions:
                    raise InvalidSessionCountError(
                        f"{day_label} has only {total_sessions} scheduled classes, but period {p} was requested."
                    )
                attend_indices.add(p)

        # 5. Build session actions
        resolved: list[ResolvedSessionAction] = []
        for idx, s in enumerate(day_sessions, 1):
            if idx in skip_indices:
                act = SimulationAction.SKIP
            elif idx in attend_indices or req.attend_remaining:
                act = SimulationAction.ATTEND
            else:
                act = SimulationAction.ATTEND

            resolved.append(
                ResolvedSessionAction(
                    date=target_date,
                    period_index=idx,
                    course_code=(s.course_code or s.activity_name or "Course").strip(),
                    activity_name=s.activity_name,
                    start_time=s.start_time,
                    end_time=s.end_time,
                    action=act,
                )
            )

        note = (
            f"{day_label}: Skipping {len(skip_indices)} class{'es' if len(skip_indices) != 1 else ''}, "
            f"attending {total_sessions - len(skip_indices)} class{'es' if (total_sessions - len(skip_indices)) != 1 else ''}"
        )
        return resolved, note

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
        """
        instructional_dates: list[date] = []
        curr = today_dt + timedelta(days=1)
        max_scan_days = 90

        while len(instructional_dates) < count and (curr - today_dt).days <= max_scan_days:
            weekday = curr.weekday()
            day_entries = [
                e for e in entries
                if e.day_of_week == weekday and e.activity_type != ActivityType.BREAK
            ]
            if student_batch != LabBatch.UNKNOWN:
                day_entries = [
                    e for e in day_entries
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
        Resolve a natural-language subject query against the student's confirmed timetable.
        """
        uid = UUID(str(student_id))
        confirmed_tt = await self._get_confirmed_timetable(uid)
        if not confirmed_tt:
            raise NoConfirmedTimetableError()

        entries = await self._get_timetable_entries(confirmed_tt)
        clean_query = subject_query.strip().casefold()

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

        # 1. Exact match
        for code, name in courses.items():
            if clean_query == code.casefold():
                return code, name
            if clean_query == name.casefold():
                return code, name

        # 2. Acronym / substring match
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
            ("get_latest_confirmed_for_student", (uid,)),
            ("get_confirmed_for_student", (uid,)),
            ("get_latest_for_student", (uid, TimetableStatus.CONFIRMED)),
            ("get_active", (uid,)),
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
        # Check entry_repo explicitly first
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
