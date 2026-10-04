"""
Daily Morning Briefing Service — Personal Alpha.

Generates a concise, natural-language morning briefing for one student
from verified timetable and attendance data.

Design rules:
- Transport-agnostic: no Telegram/WhatsApp imports here.
- Only CONFIRMED timetables are used (timetable state machine rule).
- All attendance arithmetic comes from AttendanceService; this module
  only formats and narrates verified results.
- The LLM is never involved: facts and wording are deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
import inspect
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from uuid import UUID

    from app.intelligence.models.context import StudentContext, StudentProfile
    from app.intelligence.services.attendance_service import (
        AttendanceService,
        AttendanceSummaryResult,
    )
    from app.intelligence.services.timetable_service import TimetableService
    from app.models.timetable import TimetableEntry

STALE_AFTER_DAYS = 7


@dataclass(frozen=True, slots=True)
class BriefingClass:
    """One class slot for the day, in chronological order."""

    subject_name: str
    start_time: time
    end_time: time
    activity_type: str
    room: str | None
    faculty: str | None


@dataclass(frozen=True, slots=True)
class BriefingSubjectAttendance:
    """A subject that is below the configured attendance target."""

    subject_code: str
    subject_name: str | None
    cumulative_percentage: float
    target_percentage: float
    deficit: float


@dataclass(frozen=True, slots=True)
class BriefingAttendance:
    """Verified attendance facts for the briefing."""

    overall_percentage: float
    attended: int
    conducted: int
    captured_at: datetime
    source: str
    target_percentage: float | None
    below_target: tuple[BriefingSubjectAttendance, ...]


@dataclass(frozen=True, slots=True)
class DailyBriefing:
    """Complete structured facts for one morning briefing."""

    student_name: str
    date: date
    day_name: str
    classes: tuple[BriefingClass, ...]
    timetable_confirmed: bool
    timetable_confirmed_at: datetime | None
    attendance: BriefingAttendance | None
    attendance_stale: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BriefingResult:
    """Structured facts plus the rendered natural-language message."""

    facts: DailyBriefing
    message: str


class BriefingService:
    """
    Builds the daily morning briefing for an authenticated student.

    Callable from any future transport (scheduler, Telegram, WhatsApp)
    without modification — it depends only on the intelligence services.
    """

    def __init__(
        self,
        timetable_service: TimetableService,
        attendance_service: AttendanceService,
        *,
        now: Callable[[], datetime] | None = None,
        today: Callable[[], date] | None = None,
    ) -> None:
        self._timetable_service = timetable_service
        self._attendance_service = attendance_service
        self._now = now or (lambda: datetime.now(UTC))
        self._today = today or date.today

    async def generate_briefing(
        self, student_context: StudentContext
    ) -> BriefingResult:
        """
        Generate the briefing for one student.

        The student identity comes from the authenticated context only.
        Returns structured facts and the rendered message.
        """
        student_id = student_context.student_id
        profile = student_context.profile

        briefing_date = self._today()
        timetable = await self._timetable_service.get_confirmed_timetable(student_id)
        classes: tuple[BriefingClass, ...] = ()
        if timetable is not None:
            entries = []
            if hasattr(self._timetable_service, "get_schedule_for_date"):
                res = self._timetable_service.get_schedule_for_date(student_id, briefing_date)
                if inspect.isawaitable(res):
                    entries = await res
                else:
                    entries = await self._timetable_service.get_today_schedule(student_id)
            else:
                entries = await self._timetable_service.get_today_schedule(student_id)

            classes = tuple(
                self._to_class(entry)
                for entry in sorted(entries, key=lambda e: (e.start_time, e.end_time))
            )

        summary = await self._attendance_service.get_attendance_summary(str(student_id))
        attendance, stale = await self._build_attendance(student_id, profile, summary)

        warnings = self._build_warnings(
            timetable_confirmed=timetable is not None,
            attendance=attendance,
            stale=stale,
        )

        briefing_date = self._today()
        facts = DailyBriefing(
            student_name=profile.get_display_name(),
            date=briefing_date,
            day_name=briefing_date.strftime("%A"),
            classes=classes,
            timetable_confirmed=timetable is not None,
            timetable_confirmed_at=timetable.confirmed_at if timetable else None,
            attendance=attendance,
            attendance_stale=stale,
            warnings=warnings,
        )
        return BriefingResult(facts=facts, message=self.render(facts))

    async def _build_attendance(
        self,
        student_id: UUID,
        profile: StudentProfile,
        summary: AttendanceSummaryResult | None,
    ) -> tuple[BriefingAttendance | None, bool]:
        """Assemble attendance facts; all arithmetic is pre-computed."""
        if summary is None:
            return None, True

        target = profile.attendance_target
        valid_target = target if target is not None and 0.0 <= target <= 100.0 else None

        below: tuple[BriefingSubjectAttendance, ...] = ()
        if valid_target is not None:
            results = await self._attendance_service.get_subjects_below_target(
                student_id=str(student_id),
                target_percentage=valid_target,
            )
            below = tuple(
                BriefingSubjectAttendance(
                    subject_code=r.subject_code,
                    subject_name=r.subject_name,
                    cumulative_percentage=r.cumulative_percentage,
                    target_percentage=r.target_percentage,
                    deficit=r.deficit,
                )
                for r in results
            )

        captured_at = summary.captured_at
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=UTC)
        stale = self._now() - captured_at > timedelta(days=STALE_AFTER_DAYS)

        return (
            BriefingAttendance(
                overall_percentage=summary.overall.percentage,
                attended=summary.overall.attended,
                conducted=summary.overall.conducted,
                captured_at=summary.captured_at,
                source=summary.source,
                target_percentage=valid_target,
                below_target=below,
            ),
            stale,
        )

    def _build_warnings(
        self,
        *,
        timetable_confirmed: bool,
        attendance: BriefingAttendance | None,
        stale: bool,
    ) -> tuple[str, ...]:
        warnings: list[str] = []
        if not timetable_confirmed:
            warnings.append(
                "No confirmed timetable — class schedule may be incomplete."
            )
        if attendance is None:
            warnings.append("No attendance data yet — sync your college portal.")
        elif stale:
            warnings.append(
                f"Attendance last synced over {STALE_AFTER_DAYS} days ago "
                "— figures may be outdated."
            )
        return tuple(warnings)

    @staticmethod
    def _to_class(entry: TimetableEntry) -> BriefingClass:
        activity_type = entry.activity_type
        return BriefingClass(
            subject_name=entry.activity_name,
            start_time=entry.start_time,
            end_time=entry.end_time,
            activity_type=(
                activity_type.value
                if hasattr(activity_type, "value")
                else str(activity_type)
            ),
            room=entry.room,
            faculty=entry.faculty,
        )

    @staticmethod
    def render(briefing: DailyBriefing) -> str:
        """Render briefing facts as a natural-language message."""
        lines: list[str] = []

        lines.append(f"☀️ Good morning, {briefing.student_name}!")
        lines.append(f"📅 {briefing.day_name}, {briefing.date.strftime('%d %B %Y')}")
        lines.append("")

        if briefing.classes:
            lines.append(f"📚 Classes today ({len(briefing.classes)}):")
            for index, cls in enumerate(briefing.classes, start=1):
                lines.append(f"  {index}. {_format_class(cls)}")
        else:
            lines.append("📚 No classes today. 🎉")
        lines.append("")

        attendance = briefing.attendance
        if attendance is None:
            lines.append("📊 Attendance: no data yet.")
        else:
            lines.append(
                f"📊 Attendance: {attendance.overall_percentage:.1f}% "
                f"({attendance.attended}/{attendance.conducted}) "
                f"— synced {attendance.captured_at.strftime('%d %b %Y')} "
                f"via {attendance.source}"
            )
            if attendance.target_percentage is not None:
                if attendance.below_target:
                    lines.append(f"⚠️ Below {attendance.target_percentage:g}% target:")
                    for subject in attendance.below_target:
                        name = subject.subject_name or subject.subject_code
                        lines.append(
                            f"  • {name}: {subject.cumulative_percentage:.1f}% "
                            f"(short by {subject.deficit:.1f}%)"
                        )
                else:
                    lines.append(
                        f"✅ All subjects at or above the "
                        f"{attendance.target_percentage:g}% target."
                    )
        lines.append("")

        for warning in briefing.warnings:
            lines.append(f"⚠️ {warning}")

        return "\n".join(lines)


def _format_class(cls: BriefingClass) -> str:
    """Format one class line: name, time, room, faculty."""
    parts = [
        f"{cls.start_time.strftime('%H:%M')}"
        f"-{cls.end_time.strftime('%H:%M')} {cls.subject_name}"
    ]
    detail: list[str] = []
    if cls.room:
        detail.append(f"Room {cls.room}")
    if cls.faculty:
        detail.append(cls.faculty)
    if detail:
        parts.append(f"[{', '.join(detail)}]")
    return " ".join(parts)


def create_briefing_service(
    timetable_service: TimetableService,
    attendance_service: AttendanceService,
) -> BriefingService:
    """Factory for BriefingService."""
    return BriefingService(
        timetable_service=timetable_service,
        attendance_service=attendance_service,
    )
