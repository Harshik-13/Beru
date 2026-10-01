"""
Timetable tools for LLM function calling.

These tools provide deterministic access to confirmed timetable data.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.intelligence.services.timetable_service import TimetableService
    from app.models.timetable import TimetableEntry


@dataclass(frozen=True, slots=True)
class ScheduleEntryResult:
    """Result for a single schedule entry."""

    day: str  # Monday, Tuesday, etc.
    start_time: str  # HH:MM
    end_time: str  # HH:MM
    activity_name: str
    activity_type: str  # academic, lab, break, activity
    room: str | None = None
    faculty: str | None = None

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "activity_name": self.activity_name,
            "activity_type": self.activity_type,
            "room": self.room,
            "faculty": self.faculty,
        }


@dataclass(frozen=True, slots=True)
class ScheduleResult:
    """Result for a schedule query."""

    date: str  # YYYY-MM-DD
    day: str
    entries: tuple[ScheduleEntryResult, ...]

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "day": self.day,
            "entries": [e.to_dict() for e in self.entries],
        }


@dataclass(frozen=True, slots=True)
class NextClassResult:
    """Result for next class query."""

    has_class: bool
    entry: ScheduleEntryResult | None = None
    message: str | None = None

    def to_dict(self) -> dict:
        result = {"has_class": self.has_class}
        if self.entry:
            result["entry"] = self.entry.to_dict()
        if self.message:
            result["message"] = self.message
        return result


DAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def _entry_to_result(
    entry: "TimetableEntry", day_name: str | None = None
) -> ScheduleEntryResult:
    """Convert TimetableEntry to ScheduleEntryResult."""
    if day_name is None:
        day_name = DAY_NAMES[entry.day_of_week] if entry.day_of_week < 7 else "Unknown"

    return ScheduleEntryResult(
        day=day_name,
        start_time=entry.start_time.strftime("%H:%M"),
        end_time=entry.end_time.strftime("%H:%M"),
        activity_name=entry.activity_name,
        activity_type=entry.activity_type.value,
        room=entry.room,
        faculty=entry.faculty,
    )


async def get_schedule(
    service: "TimetableService",
    student_id: str,
    target_date: str | None = None,
) -> dict:
    """
    Get schedule for a specific date.

    Args:
        student_id: Student UUID
        target_date: Date in YYYY-MM-DD format (defaults to today)

    Returns:
        ScheduleResult dict
    """
    from uuid import UUID

    student_uuid = UUID(student_id)
    query_date = date.fromisoformat(target_date) if target_date else date.today()

    entries = await service.get_schedule_for_date(student_uuid, query_date)
    entry_results = tuple(_entry_to_result(e) for e in entries)

    result = ScheduleResult(
        date=query_date.isoformat(),
        day=(
            DAY_NAMES[query_date.weekday()] if query_date.weekday() < 7 else "Unknown"
        ),
        entries=entry_results,
    )
    return result.to_dict()


async def get_today_schedule(
    service: "TimetableService",
    student_id: str,
) -> dict:
    """Get today's schedule."""
    return await get_schedule(service, student_id, date.today().isoformat())


async def get_tomorrow_schedule(
    service: "TimetableService",
    student_id: str,
) -> dict:
    """Get tomorrow's schedule."""
    tomorrow = date.today() + timedelta(days=1)
    return await get_schedule(service, student_id, tomorrow.isoformat())


async def get_next_class(
    service: "TimetableService",
    student_id: str,
) -> dict:
    """Get the next upcoming class."""
    from uuid import UUID

    student_uuid = UUID(student_id)
    next_entry = await service.get_next_class(student_uuid)

    if not next_entry:
        return NextClassResult(
            has_class=False,
            message="No more classes today or tomorrow.",
        ).to_dict()

    day_name = DAY_NAMES[next_entry.day_of_week]
    entry_result = _entry_to_result(next_entry, day_name)

    return NextClassResult(
        has_class=True,
        entry=entry_result,
    ).to_dict()


async def get_first_class_tomorrow(
    service: "TimetableService",
    student_id: str,
) -> dict:
    """Get the first class of tomorrow."""
    from uuid import UUID

    student_uuid = UUID(student_id)
    tomorrow = date.today() + timedelta(days=1)
    first_entry = await service.get_first_class_of_day(student_uuid, tomorrow)

    if not first_entry:
        return NextClassResult(
            has_class=False,
            message="No classes scheduled for tomorrow.",
        ).to_dict()

    day_name = DAY_NAMES[first_entry.day_of_week]
    entry_result = _entry_to_result(first_entry, day_name)

    return NextClassResult(
        has_class=True,
        entry=entry_result,
    ).to_dict()


async def get_timetable_status(
    service: "TimetableService",
    student_id: str,
) -> dict:
    """Get the status of the student's timetable."""
    from uuid import UUID

    student_uuid = UUID(student_id)
    confirmed = await service.get_confirmed_timetable(student_uuid)
    pending = await service.get_pending_timetable(student_uuid)

    if confirmed:
        return {
            "status": "confirmed",
            "timetable_id": str(confirmed.id),
            "version": confirmed.version,
            "academic_year": confirmed.academic_year,
            "semester": confirmed.semester,
            "section": confirmed.section,
            "confirmed_at": (
                confirmed.confirmed_at.isoformat() if confirmed.confirmed_at else None
            ),
        }
    elif pending:
        return {
            "status": pending.status.value,
            "timetable_id": str(pending.id),
            "version": pending.version,
        }
    else:
        return {
            "status": "none",
            "message": "No timetable uploaded yet.",
        }


async def needs_lab_batch(
    service: "TimetableService",
    student_id: str,
) -> dict:
    """Check if student needs to provide lab batch."""
    from uuid import UUID

    student_uuid = UUID(student_id)
    needs = await service.needs_lab_batch(student_uuid)
    current = await service.get_student_lab_batch(student_uuid)

    return {
        "needs_lab_batch": needs,
        "current_batch": current.value if current else "unknown",
    }


async def set_lab_batch(
    service: "TimetableService",
    student_id: str,
    batch: str,  # "batch_1" or "batch_2"
) -> dict:
    """Set the student's lab batch and resolve slash labs.

    Does NOT auto-confirm - timetable remains in REVIEW_REQUIRED
    for student confirmation.
    """
    from uuid import UUID

    from app.models.timetable import LabBatch

    student_uuid = UUID(student_id)
    lab_batch = LabBatch(batch)

    await service.set_lab_batch(student_uuid, lab_batch)

    # If there's a pending timetable with slash labs, resolve them
    pending = await service.get_pending_timetable(student_uuid)
    if pending:
        entries = await service.entry_repo.get_for_timetable(pending.id)
        resolved_count = 0
        for entry in entries:
            if (
                entry.lab_batch is None or entry.lab_batch == LabBatch.UNKNOWN
            ) and "/" in entry.activity_name:
                parts = [p.strip() for p in entry.activity_name.split("/")]
                if len(parts) == 2:
                    if lab_batch == LabBatch.BATCH_1:
                        entry.activity_name = parts[0]
                    elif lab_batch == LabBatch.BATCH_2:
                        entry.activity_name = parts[1]
                    if "lab" in entry.activity_name.lower():
                        from app.models.timetable import ActivityType

                        entry.activity_type = ActivityType.LAB
                    entry.lab_batch = lab_batch
                    resolved_count += 1

        await service.session.flush()

    return {
        "success": True,
        "lab_batch": lab_batch.value,
        "message": (
            f"Lab batch set to {lab_batch.value.replace('_', ' ').title()}. "
            f"Resolved {resolved_count} lab entries. "
            "Please review and confirm your timetable."
        ),
    }


async def confirm_timetable(
    service: "TimetableService",
    student_id: str,
) -> dict:
    """Confirm a pending timetable for the student."""
    from uuid import UUID

    student_uuid = UUID(student_id)
    pending = await service.get_pending_timetable(student_uuid)
    if not pending:
        return {
            "success": False,
            "message": "No pending timetable found awaiting review/confirmation.",
        }

    confirmed = await service.confirm_timetable(pending.id)
    return {
        "success": True,
        "timetable_id": str(confirmed.id),
        "status": "confirmed",
        "message": (
            f"Timetable confirmed successfully! Version {confirmed.version} "
            "is now active."
        ),
    }


async def get_extracted_timetable(
    service: "TimetableService",
    student_id: str,
) -> dict:
    """Get the pending extracted timetable for review (not a schedule query)."""
    from uuid import UUID

    from app.intelligence.services.timetable_service import format_week_schedule

    student_uuid = UUID(student_id)
    pending, entries = await service.get_pending_timetable_with_entries(student_uuid)

    if not pending:
        return {
            "status": "none",
            "message": "No pending timetable found for review.",
        }

    week_grid = format_week_schedule(entries, pending)

    return {
        "status": pending.status.value,
        "timetable_id": str(pending.id),
        "version": pending.version,
        "section": pending.section,
        "branch": pending.branch,
        "programme": pending.programme,
        "semester": pending.semester,
        "year": pending.year,
        "academic_year": pending.academic_year,
        "default_classroom": pending.default_classroom,
        "entry_count": len(entries),
        "week_schedule": week_grid,
        "entries": [
            {
                "entry_id": str(e.id),
                "day": DAY_NAMES[e.day_of_week] if e.day_of_week < 7 else "Unknown",
                "day_of_week": e.day_of_week,
                "start_time": e.start_time.strftime("%H:%M"),
                "end_time": e.end_time.strftime("%H:%M"),
                "activity_name": e.activity_name,
                "activity_type": e.activity_type.value,
                "room": e.room,
                "faculty": e.faculty,
                "course_code": e.course_code,
            }
            for e in entries
        ],
    }


async def update_timetable_entry(
    service: "TimetableService",
    student_id: str,
    entry_id: str,
    **kwargs,
) -> dict:
    """Update a timetable entry during review (REVIEW_REQUIRED only)."""
    from uuid import UUID

    student_uuid = UUID(student_id)
    pending = await service.get_pending_timetable(student_uuid)
    if not pending:
        return {"success": False, "message": "No pending timetable found for review."}

    entry_uuid = UUID(entry_id)
    updates = {}
    if "activity_name" in kwargs:
        updates["activity_name"] = kwargs["activity_name"]
    if "start_time" in kwargs:
        updates["start_time"] = kwargs["start_time"]
    if "end_time" in kwargs:
        updates["end_time"] = kwargs["end_time"]
    if "activity_type" in kwargs:
        updates["activity_type"] = kwargs["activity_type"]
    if "room" in kwargs:
        updates["room"] = kwargs["room"]
    if "day_of_week" in kwargs:
        updates["day_of_week"] = int(kwargs["day_of_week"])

    updated = await service.update_entry(pending.id, entry_uuid, **updates)
    if not updated:
        return {"success": False, "message": "Entry not found in pending timetable."}

    return {
        "success": True,
        "entry_id": str(updated.id),
        "message": f"Updated entry: {updated.activity_name}",
    }


async def add_timetable_entry(
    service: "TimetableService",
    student_id: str,
    **kwargs,
) -> dict:
    """Add a new timetable entry during review (REVIEW_REQUIRED only)."""
    from uuid import UUID

    from app.models.timetable import ActivityType, TimetableEntry

    student_uuid = UUID(student_id)
    pending = await service.get_pending_timetable(student_uuid)
    if not pending:
        return {"success": False, "message": "No pending timetable found for review."}

    day_of_week = int(kwargs.get("day_of_week", 0))
    if day_of_week < 0 or day_of_week > 5:
        return {"success": False, "message": "day_of_week must be 0-5 (Mon-Sat)."}

    start_time = kwargs.get("start_time", "10:00")
    end_time = kwargs.get("end_time", "11:00")

    entry = TimetableEntry(
        timetable_id=pending.id,
        day_of_week=day_of_week,
        start_time=datetime.strptime(start_time, "%H:%M").time(),
        end_time=datetime.strptime(end_time, "%H:%M").time(),
        activity_name=kwargs.get("activity_name", "New Entry"),
        activity_type=ActivityType(kwargs.get("activity_type", "academic")),
        room=kwargs.get("room"),
        course_code=kwargs.get("course_code"),
        faculty=kwargs.get("faculty"),
    )
    await service.entry_repo.create(entry)

    return {
        "success": True,
        "entry_id": str(entry.id),
        "message": f"Added entry: {entry.activity_name}",
    }


async def delete_timetable_entry(
    service: "TimetableService",
    student_id: str,
    entry_id: str,
) -> dict:
    """Delete a timetable entry during review (REVIEW_REQUIRED only)."""
    from uuid import UUID

    student_uuid = UUID(student_id)
    pending = await service.get_pending_timetable(student_uuid)
    if not pending:
        return {"success": False, "message": "No pending timetable found for review."}

    entry_uuid = UUID(entry_id)
    entries = await service.entry_repo.get_for_timetable(pending.id)
    target = next((e for e in entries if e.id == entry_uuid), None)
    if not target:
        return {"success": False, "message": "Entry not found in pending timetable."}

    await service.session.delete(target)
    await service.session.flush()

    return {
        "success": True,
        "message": f"Deleted entry: {target.activity_name}",
    }


async def set_briefing_time(
    service: "TimetableService",
    student_id: str,
    briefing_time: str,
) -> dict:
    """Set the student's daily briefing time (HH:MM format)."""
    import re
    from uuid import UUID

    if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", briefing_time):
        return {
            "success": False,
            "message": "Invalid time format. Use HH:MM (24-hour).",
        }

    student_uuid = UUID(student_id)
    student = await service.student_repo.get_by_id(student_uuid)
    if not student:
        return {"success": False, "message": "Student not found."}

    student.briefing_time = briefing_time
    await service.session.flush()

    return {
        "success": True,
        "briefing_time": briefing_time,
        "message": f"Briefing time set to {briefing_time}.",
    }


async def get_week_schedule(
    service: "TimetableService",
    student_id: str,
) -> dict:
    """Get the full week schedule (Mon-Sat) from confirmed timetable."""
    from uuid import UUID

    student_uuid = UUID(student_id)
    timetable = await service.get_confirmed_timetable(student_uuid)
    if not timetable:
        return {"status": "none", "message": "No confirmed timetable found."}

    entries = await service.entry_repo.get_for_timetable(timetable.id)

    week = {}
    for day_idx, day_name in enumerate(DAY_NAMES):
        day_entries = [e for e in entries if e.day_of_week == day_idx]
        week[day_name] = [
            {
                "start_time": e.start_time.strftime("%H:%M"),
                "end_time": e.end_time.strftime("%H:%M"),
                "activity_name": e.activity_name,
                "activity_type": e.activity_type.value,
                "room": e.room,
                "faculty": e.faculty,
                "lab_batch": e.lab_batch.value if e.lab_batch else None,
            }
            for e in sorted(day_entries, key=lambda x: x.start_time)
        ]

    return {
        "status": "confirmed",
        "week": week,
    }


async def get_schedule_for_weekday(
    service: "TimetableService",
    student_id: str,
    day_of_week: int,
) -> dict:
    """Get schedule for a specific weekday (0=Mon, 5=Sat) from confirmed timetable."""
    from uuid import UUID

    if day_of_week < 0 or day_of_week > 5:
        return {"success": False, "message": "day_of_week must be 0-5 (Mon-Sat)."}

    student_uuid = UUID(student_id)
    timetable = await service.get_confirmed_timetable(student_uuid)
    if not timetable:
        return {"status": "none", "message": "No confirmed timetable found."}

    entries = await service.entry_repo.get_for_timetable(timetable.id)
    day_entries = [e for e in entries if e.day_of_week == day_of_week]

    return {
        "status": "confirmed",
        "day": DAY_NAMES[day_of_week],
        "entries": [
            {
                "start_time": e.start_time.strftime("%H:%M"),
                "end_time": e.end_time.strftime("%H:%M"),
                "activity_name": e.activity_name,
                "activity_type": e.activity_type.value,
                "room": e.room,
                "faculty": e.faculty,
                "lab_batch": e.lab_batch.value if e.lab_batch else None,
            }
            for e in sorted(day_entries, key=lambda x: x.start_time)
        ],
    }


async def get_timetable_metadata(
    service: "TimetableService",
    student_id: str,
) -> dict:
    """Get timetable metadata (section, branch, programme, etc.)."""
    from uuid import UUID

    student_uuid = UUID(student_id)
    timetable = await service.get_confirmed_timetable(student_uuid)
    if not timetable:
        return {"status": "none", "message": "No confirmed timetable found."}

    return {
        "status": "confirmed",
        "section": timetable.section,
        "branch": timetable.branch,
        "programme": timetable.programme,
        "regulation": timetable.regulation,
        "academic_year": timetable.academic_year,
        "semester": timetable.semester,
        "year": timetable.year,
        "default_classroom": timetable.default_classroom,
        "effective_from": (
            timetable.effective_from.isoformat() if timetable.effective_from else None
        ),
    }


async def find_activity_details(
    service: "TimetableService",
    student_id: str,
    query: str,
    day: int | str | None = None,
) -> dict:
    """Find schedule, rooms, timings, and faculty for a specific course or lab."""
    from uuid import UUID
    from app.intelligence.rendering.schedule_renderer import (
        _normalize_batch_str,
        merge_contiguous_entries,
        resolve_batch_and_filter,
    )

    student_uuid = UUID(student_id)
    timetable = await service.get_confirmed_timetable(student_uuid)
    if not timetable:
        return {
            "status": "none",
            "message": "No confirmed timetable found.",
            "found": False,
            "matches": [],
        }

    student_batch = None
    if service.student_repo:
        student = await service.student_repo.get_by_id(student_uuid)
        if student and student.lab_batch:
            student_batch = _normalize_batch_str(
                getattr(student.lab_batch, "value", str(student.lab_batch))
            )

    entries = await service.entry_repo.get_for_timetable(timetable.id)
    q_clean = query.strip().lower()

    # Normalize optional day filter
    target_day: int | None = None
    if day is not None:
        if isinstance(day, int) and 0 <= day <= 6:
            target_day = day
        elif isinstance(day, str):
            day_str = day.strip().lower()
            for idx, d_name in enumerate(DAY_NAMES):
                if d_name.lower().startswith(day_str):
                    target_day = idx
                    break

    matching_raw = []
    for e in entries:
        if target_day is not None and e.day_of_week != target_day:
            continue
        act = e.activity_name.lower()
        code = (e.course_code or "").lower()
        if q_clean in act or q_clean in code:
            matching_raw.append(
                {
                    "day_of_week": e.day_of_week,
                    "day": (
                        DAY_NAMES[e.day_of_week]
                        if e.day_of_week < len(DAY_NAMES)
                        else "Unknown"
                    ),
                    "start_time": e.start_time.strftime("%H:%M"),
                    "end_time": e.end_time.strftime("%H:%M"),
                    "activity_name": e.activity_name,
                    "activity_type": e.activity_type.value,
                    "room": e.room or timetable.default_classroom,
                    "faculty": e.faculty,
                    "lab_batch": e.lab_batch.value if e.lab_batch else None,
                }
            )

    resolved, has_ambiguity = resolve_batch_and_filter(matching_raw, student_batch)
    merged = merge_contiguous_entries(resolved)

    return {
        "status": "confirmed",
        "query": query,
        "found": len(merged) > 0,
        "count": len(merged),
        "has_ambiguity": has_ambiguity,
        "matches": merged,
    }


async def find_faculty_details(
    service: "TimetableService",
    student_id: str,
    subject: str | None = None,
    faculty_name: str | None = None,
    list_all: bool = False,
) -> dict:
    """Find professors and faculty members teaching the student."""
    from uuid import UUID

    student_uuid = UUID(student_id)
    timetable = await service.get_confirmed_timetable(student_uuid)
    if not timetable:
        return {
            "status": "none",
            "message": "No confirmed timetable found.",
            "found": False,
        }

    entries = await service.entry_repo.get_for_timetable(timetable.id)

    # Mode A: list all faculty directory
    if list_all or (not subject and not faculty_name):
        directory: dict[str, str] = {}
        for e in entries:
            if e.faculty:
                act = e.activity_name
                directory[act] = e.faculty
        items = [{"subject": k, "faculty": v} for k, v in sorted(directory.items())]
        return {
            "status": "confirmed",
            "type": "directory",
            "found": len(items) > 0,
            "faculty_list": items,
        }

    # Mode B: find by subject
    if subject:
        s_clean = subject.strip().lower()
        sub_entries = [
            e
            for e in entries
            if s_clean in e.activity_name.lower()
            or s_clean in (e.course_code or "").lower()
        ]
        faculty_map: dict[str, bool] = {}
        sessions = []
        for e in sorted(sub_entries, key=lambda x: (x.day_of_week, x.start_time)):
            if e.faculty:
                faculty_map[e.faculty] = True
            sessions.append(
                {
                    "day": (
                        DAY_NAMES[e.day_of_week]
                        if e.day_of_week < len(DAY_NAMES)
                        else "Unknown"
                    ),
                    "start_time": e.start_time.strftime("%H:%M"),
                    "end_time": e.end_time.strftime("%H:%M"),
                    "room": e.room,
                    "faculty": e.faculty,
                }
            )
        return {
            "status": "confirmed",
            "type": "subject_faculty",
            "subject": subject,
            "found": len(sub_entries) > 0,
            "faculty_names": list(faculty_map.keys()),
            "sessions": sessions,
        }

    # Mode C: find by faculty name
    if faculty_name:
        f_clean = faculty_name.strip().lower()
        fac_entries = [e for e in entries if e.faculty and f_clean in e.faculty.lower()]
        subjects_taught = sorted(list({e.activity_name for e in fac_entries}))
        sessions = [
            {
                "subject": e.activity_name,
                "day": (
                    DAY_NAMES[e.day_of_week]
                    if e.day_of_week < len(DAY_NAMES)
                    else "Unknown"
                ),
                "start_time": e.start_time.strftime("%H:%M"),
                "end_time": e.end_time.strftime("%H:%M"),
                "room": e.room,
            }
            for e in sorted(fac_entries, key=lambda x: (x.day_of_week, x.start_time))
        ]
        return {
            "status": "confirmed",
            "type": "faculty_schedule",
            "faculty_name": faculty_name,
            "found": len(fac_entries) > 0,
            "subjects": subjects_taught,
            "sessions": sessions,
        }

    return {"status": "none", "found": False}


async def find_room_details(
    service: "TimetableService",
    student_id: str,
    room: str,
) -> dict:
    """Find schedule and activities for a specific classroom or lab room."""
    from uuid import UUID

    student_uuid = UUID(student_id)
    timetable = await service.get_confirmed_timetable(student_uuid)
    if not timetable:
        return {
            "status": "none",
            "message": "No confirmed timetable found.",
            "found": False,
        }

    r_clean = room.strip().lower()
    is_default = bool(
        timetable.default_classroom
        and r_clean in timetable.default_classroom.lower()
    )

    entries = await service.entry_repo.get_for_timetable(timetable.id)
    room_entries = [
        e
        for e in entries
        if (e.room and r_clean in e.room.lower())
        or (is_default and not e.room)
    ]

    sessions = [
        {
            "activity_name": e.activity_name,
            "day": (
                DAY_NAMES[e.day_of_week]
                if e.day_of_week < len(DAY_NAMES)
                else "Unknown"
            ),
            "start_time": e.start_time.strftime("%H:%M"),
            "end_time": e.end_time.strftime("%H:%M"),
            "activity_type": e.activity_type.value,
        }
        for e in sorted(room_entries, key=lambda x: (x.day_of_week, x.start_time))
    ]

    return {
        "status": "confirmed",
        "room": room,
        "is_default_classroom": is_default,
        "default_classroom": timetable.default_classroom,
        "found": len(sessions) > 0 or is_default,
        "sessions": sessions,
    }


async def query_schedule_analytics(
    service: "TimetableService",
    student_id: str,
    metric: str,
    subject: str | None = None,
    day: int | str | None = None,
    scope: str = "entire_week",
) -> dict:
    """Deterministic schedule analytics: classes vs labs, frequencies, workload, free slots."""
    from datetime import date
    from uuid import UUID
    from app.intelligence.rendering.schedule_renderer import (
        _normalize_batch_str,
        merge_contiguous_entries,
        resolve_batch_and_filter,
    )

    student_uuid = UUID(student_id)
    timetable = await service.get_confirmed_timetable(student_uuid)
    if not timetable:
        return {"status": "none", "message": "No confirmed timetable found."}

    student_batch = None
    if service.student_repo:
        student = await service.student_repo.get_by_id(student_uuid)
        if student and student.lab_batch:
            student_batch = _normalize_batch_str(
                getattr(student.lab_batch, "value", str(student.lab_batch))
            )

    entries = await service.entry_repo.get_for_timetable(timetable.id)
    raw_dicts = [
        {
            "day_of_week": e.day_of_week,
            "day": (
                DAY_NAMES[e.day_of_week]
                if e.day_of_week < len(DAY_NAMES)
                else "Unknown"
            ),
            "start_time": e.start_time.strftime("%H:%M"),
            "end_time": e.end_time.strftime("%H:%M"),
            "activity_name": e.activity_name,
            "activity_type": e.activity_type.value,
            "room": e.room,
            "faculty": e.faculty,
            "lab_batch": e.lab_batch.value if e.lab_batch else None,
        }
        for e in entries
    ]

    resolved, _ = resolve_batch_and_filter(raw_dicts, student_batch)
    merged = merge_contiguous_entries(resolved)

    def duration_hours(start_str: str, end_str: str) -> float:
        sh, sm = map(int, start_str.split(":"))
        eh, em = map(int, end_str.split(":"))
        return round(((eh * 60 + em) - (sh * 60 + sm)) / 60.0, 1)

    # 1. Classes vs Labs
    if metric in {"classes_vs_labs", "counts", "breakdown"}:
        lectures = [
            e
            for e in merged
            if "lab" not in e.get("activity_type", "").lower()
            and "lab" not in e.get("activity_name", "").lower()
        ]
        labs = [
            e
            for e in merged
            if "lab" in e.get("activity_type", "").lower()
            or "lab" in e.get("activity_name", "").lower()
        ]

        lec_hours = sum(duration_hours(e["start_time"], e["end_time"]) for e in lectures)
        lab_hours = sum(duration_hours(e["start_time"], e["end_time"]) for e in labs)

        return {
            "status": "confirmed",
            "metric": "classes_vs_labs",
            "theory_count": len(lectures),
            "theory_hours": lec_hours,
            "lab_count": len(labs),
            "lab_hours": lab_hours,
            "total_count": len(merged),
            "total_hours": round(lec_hours + lab_hours, 1),
        }

    # 2. Subject Count / Frequency (Entire Week or Remaining Days)
    if metric in {"subject_count", "frequency"} or subject:
        sub_name = subject or ""
        s_clean = sub_name.strip().lower()

        # Check scope
        today_idx = date.today().weekday()
        if scope in {"remaining_days", "remaining"}:
            scoped_entries = [e for e in merged if e.get("day_of_week", 0) >= today_idx]
        else:
            scoped_entries = merged

        matched_all = [e for e in merged if s_clean in e["activity_name"].lower()]
        matched_scoped = [e for e in scoped_entries if s_clean in e["activity_name"].lower()]

        return {
            "status": "confirmed",
            "metric": "subject_count",
            "subject": subject or "Target Course",
            "scope": scope,
            "total_in_week": len(matched_all),
            "count_in_scope": len(matched_scoped),
            "sessions": matched_scoped,
        }

    # 3. Daily Workload & Extremes
    if metric in {"daily_workload", "workload", "extremes"}:
        day_counts: dict[str, dict[str, Any]] = {}
        for d_idx, d_name in enumerate(DAY_NAMES[:6]):
            d_entries = [e for e in merged if e.get("day_of_week") == d_idx]
            d_hours = sum(duration_hours(e["start_time"], e["end_time"]) for e in d_entries)
            day_counts[d_name] = {"count": len(d_entries), "hours": d_hours}

        sorted_days = sorted(
            [(k, v["hours"], v["count"]) for k, v in day_counts.items() if v["count"] > 0],
            key=lambda x: x[1],
            reverse=True,
        )
        heaviest = sorted_days[0] if sorted_days else None
        lightest = sorted_days[-1] if sorted_days else None

        return {
            "status": "confirmed",
            "metric": "daily_workload",
            "days": day_counts,
            "heaviest": heaviest,
            "lightest": lightest,
        }

    # 4. Free slots / Breaks
    if metric in {"free_slots", "breaks"}:
        target_d = day if isinstance(day, int) else date.today().weekday()
        d_entries = sorted(
            [e for e in merged if e.get("day_of_week") == target_d],
            key=lambda x: x["start_time"],
        )
        gaps = []
        for i in range(len(d_entries) - 1):
            curr_end = d_entries[i]["end_time"]
            next_start = d_entries[i + 1]["start_time"]
            if curr_end < next_start:
                gaps.append({"start_time": curr_end, "end_time": next_start})

        return {
            "status": "confirmed",
            "metric": "free_slots",
            "day": DAY_NAMES[target_d] if target_d < len(DAY_NAMES) else "Requested Day",
            "free_slots": gaps,
        }

    return {"status": "none", "message": f"Unsupported metric: {metric}"}


# Tool definitions for registry
TIMETABLE_TOOL_DEFINITIONS = [
    {
        "name": "confirm_timetable",
        "description": (
            "Confirm the student's pending timetable, activating it for daily "
            "briefings and schedule queries."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
            },
            "required": ["student_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "timetable_id": {"type": "string"},
                "status": {"type": "string"},
                "message": {"type": "string"},
            },
        },
    },
    {
        "name": "get_schedule",
        "description": (
            "Get the student's class schedule for a specific date. Defaults to today."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "target_date": {
                    "type": "string",
                    "format": "date",
                    "description": "Date in YYYY-MM-DD format",
                },
            },
            "required": ["student_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "format": "date"},
                "day": {"type": "string"},
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "day": {"type": "string"},
                            "start_time": {"type": "string"},
                            "end_time": {"type": "string"},
                            "activity_name": {"type": "string"},
                            "activity_type": {"type": "string"},
                            "room": {"type": ["string", "null"]},
                            "faculty": {"type": ["string", "null"]},
                        },
                    },
                },
            },
        },
    },
    {
        "name": "get_today_schedule",
        "description": "Get the student's scheduled classes for today.",
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
            },
            "required": ["student_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "format": "date"},
                "day": {"type": "string"},
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "day": {"type": "string"},
                            "start_time": {"type": "string"},
                            "end_time": {"type": "string"},
                            "activity_name": {"type": "string"},
                            "activity_type": {"type": "string"},
                            "room": {"type": ["string", "null"]},
                            "faculty": {"type": ["string", "null"]},
                        },
                    },
                },
            },
        },
    },
    {
        "name": "get_tomorrow_schedule",
        "description": (
            "Get the student's scheduled classes for tomorrow. "
            "Use this whenever the student asks about classes or schedule tomorrow."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
            },
            "required": ["student_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "format": "date"},
                "day": {"type": "string"},
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "day": {"type": "string"},
                            "start_time": {"type": "string"},
                            "end_time": {"type": "string"},
                            "activity_name": {"type": "string"},
                            "activity_type": {"type": "string"},
                            "room": {"type": ["string", "null"]},
                            "faculty": {"type": ["string", "null"]},
                        },
                    },
                },
            },
        },
    },
    {
        "name": "get_next_class",
        "description": "Get the next upcoming class from now.",
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
            },
            "required": ["student_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "has_class": {"type": "boolean"},
                "entry": {
                    "type": ["object", "null"],
                    "properties": {
                        "day": {"type": "string"},
                        "start_time": {"type": "string"},
                        "end_time": {"type": "string"},
                        "activity_name": {"type": "string"},
                        "activity_type": {"type": "string"},
                        "room": {"type": ["string", "null"]},
                        "faculty": {"type": ["string", "null"]},
                    },
                },
                "message": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "get_first_class_tomorrow",
        "description": "Get the first class of tomorrow.",
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
            },
            "required": ["student_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "has_class": {"type": "boolean"},
                "entry": {
                    "type": ["object", "null"],
                    "properties": {
                        "day": {"type": "string"},
                        "start_time": {"type": "string"},
                        "end_time": {"type": "string"},
                        "activity_name": {"type": "string"},
                        "activity_type": {"type": "string"},
                        "room": {"type": ["string", "null"]},
                        "faculty": {"type": ["string", "null"]},
                    },
                },
                "message": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "get_timetable_status",
        "description": (
            "Check the document lifecycle and confirmation state of the student's timetable "
            "(whether confirmed, pending review, version number, section, or semester). "
            "Does not provide schedule details, timings, or class counts."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
            },
            "required": ["student_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "timetable_id": {"type": ["string", "null"]},
                "version": {"type": ["integer", "null"]},
                "academic_year": {"type": ["string", "null"]},
                "semester": {"type": ["integer", "null"]},
                "section": {"type": ["string", "null"]},
                "confirmed_at": {"type": ["string", "null"]},
                "message": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "needs_lab_batch",
        "description": (
            "Check if the student needs to provide their lab batch "
            "(Batch 1 or Batch 2)."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
            },
            "required": ["student_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "needs_lab_batch": {"type": "boolean"},
                "current_batch": {"type": "string"},
            },
        },
    },
    {
        "name": "set_lab_batch",
        "description": (
            "Set the student's lab batch (Batch 1 or Batch 2) and "
            "auto-confirm pending timetable if applicable."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "batch": {"type": "string", "enum": ["batch_1", "batch_2"]},
            },
            "required": ["student_id", "batch"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "lab_batch": {"type": "string"},
                "message": {"type": "string"},
            },
        },
    },
    {
        "name": "get_extracted_timetable",
        "description": (
            "Get the pending extracted timetable awaiting student review "
            "(REVIEW_REQUIRED status). Returns the weekday grid and all "
            "entries with entry IDs. Use when the student asks to review or "
            "see what was parsed from their uploaded document before confirming, "
            "or needs entry IDs to make corrections."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
            },
            "required": ["student_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "timetable_id": {"type": ["string", "null"]},
                "version": {"type": ["integer", "null"]},
                "section": {"type": ["string", "null"]},
                "branch": {"type": ["string", "null"]},
                "programme": {"type": ["string", "null"]},
                "semester": {"type": ["integer", "null"]},
                "year": {"type": ["integer", "null"]},
                "academic_year": {"type": ["string", "null"]},
                "default_classroom": {"type": ["string", "null"]},
                "entry_count": {"type": "integer"},
                "week_schedule": {"type": "string"},
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "entry_id": {"type": "string"},
                            "day": {"type": "string"},
                            "day_of_week": {"type": "integer"},
                            "start_time": {"type": "string"},
                            "end_time": {"type": "string"},
                            "activity_name": {"type": "string"},
                            "activity_type": {"type": "string"},
                            "room": {"type": ["string", "null"]},
                            "faculty": {"type": ["string", "null"]},
                            "course_code": {"type": ["string", "null"]},
                        },
                    },
                },
            },
        },
    },
    {
        "name": "update_timetable_entry",
        "description": (
            "Update a timetable entry during review (REVIEW_REQUIRED only). "
            "Change name, times, type, room, or day for one entry by its ID."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "entry_id": {"type": "string", "format": "uuid"},
                "activity_name": {"type": "string"},
                "start_time": {"type": "string", "description": "HH:MM format"},
                "end_time": {"type": "string", "description": "HH:MM format"},
                "activity_type": {
                    "type": "string",
                    "enum": ["academic", "lab", "break", "activity"],
                },
                "room": {"type": "string"},
                "day_of_week": {"type": "integer", "description": "0=Mon, 5=Sat"},
            },
            "required": ["student_id", "entry_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "entry_id": {"type": "string"},
                "message": {"type": "string"},
            },
        },
    },
    {
        "name": "add_timetable_entry",
        "description": (
            "Add a new timetable entry during review (REVIEW_REQUIRED only)."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "activity_name": {"type": "string"},
                "day_of_week": {"type": "integer", "description": "0=Mon, 5=Sat"},
                "start_time": {"type": "string", "description": "HH:MM format"},
                "end_time": {"type": "string", "description": "HH:MM format"},
                "activity_type": {
                    "type": "string",
                    "enum": ["academic", "lab", "break", "activity"],
                },
                "room": {"type": "string"},
                "course_code": {"type": "string"},
                "faculty": {"type": "string"},
            },
            "required": ["student_id", "activity_name"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "entry_id": {"type": "string"},
                "message": {"type": "string"},
            },
        },
    },
    {
        "name": "delete_timetable_entry",
        "description": (
            "Delete a timetable entry during review (REVIEW_REQUIRED only)."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "entry_id": {"type": "string", "format": "uuid"},
            },
            "required": ["student_id", "entry_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "message": {"type": "string"},
            },
        },
    },
    {
        "name": "set_briefing_time",
        "description": (
            "Set the student's daily briefing time (HH:MM, 24-hour format). "
            "Used after timetable confirmation to configure morning briefings."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "briefing_time": {
                    "type": "string",
                    "description": "Time in HH:MM format (e.g., 08:00)",
                },
            },
            "required": ["student_id", "briefing_time"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "briefing_time": {"type": "string"},
                "message": {"type": "string"},
            },
        },
    },
    {
        "name": "get_week_schedule",
        "description": (
            "Get the full weekly schedule (Monday to Saturday) from the "
            "confirmed timetable, including all classes, laboratory practical "
            "sessions, timings, rooms, and faculty. Use when the student asks "
            "for their entire week schedule, a list of labs or practicals, "
            "overview of subjects/courses, or who teaches which subject across "
            "the week."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
            },
            "required": ["student_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "week": {"type": "object"},
                "message": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "get_schedule_for_weekday",
        "description": (
            "Get schedule for a specific weekday from the confirmed timetable "
            "(day_of_week: 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, "
            "4=Friday, 5=Saturday). Use when the student asks what classes or "
            "labs they have on a particular day (e.g. 'What do I have on "
            "Wednesday?', 'Am I free on Friday afternoon?')."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "day_of_week": {
                    "type": "integer",
                    "description": "0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat",
                },
            },
            "required": ["student_id", "day_of_week"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "day": {"type": "string"},
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "start_time": {"type": "string"},
                            "end_time": {"type": "string"},
                            "activity_name": {"type": "string"},
                            "activity_type": {"type": "string"},
                            "room": {"type": ["string", "null"]},
                            "faculty": {"type": ["string", "null"]},
                        },
                    },
                },
            },
        },
    },
    {
        "name": "get_timetable_metadata",
        "description": (
            "Get academic and timetable metadata from the confirmed timetable, "
            "such as section, department/branch, programme, academic year, "
            "semester, regulation, and default classroom. Use when the student "
            "asks about their section, department, branch, or classroom location."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
            },
            "required": ["student_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "section": {"type": ["string", "null"]},
                "branch": {"type": ["string", "null"]},
                "programme": {"type": ["string", "null"]},
                "regulation": {"type": ["string", "null"]},
                "academic_year": {"type": ["string", "null"]},
                "semester": {"type": ["integer", "null"]},
                "year": {"type": ["integer", "null"]},
                "default_classroom": {"type": ["string", "null"]},
                "effective_from": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "find_activity_details",
        "description": (
            "Find the schedule, room location, timings, and faculty for a "
            "specific course, subject, or laboratory session (e.g. 'Where is "
            "DV lab?', 'When do I have OS?', 'Where is OOPJ?')."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "query": {
                    "type": "string",
                    "description": "Name or acronym of the course, subject, or lab",
                },
                "day": {
                    "type": ["integer", "string", "null"],
                    "description": "Optional weekday filter (0=Mon, 5=Sat or day name)",
                },
            },
            "required": ["student_id", "query"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "query": {"type": "string"},
                "found": {"type": "boolean"},
                "count": {"type": "integer"},
                "matches": {"type": "array"},
            },
        },
    },
    {
        "name": "find_faculty_details",
        "description": (
            "Find professor and faculty details for courses: look up who teaches "
            "a specific subject, find a professor's schedule, or list the entire "
            "faculty directory for the student's timetable."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "subject": {
                    "type": ["string", "null"],
                    "description": "Subject name to find assigned professor for",
                },
                "faculty_name": {
                    "type": ["string", "null"],
                    "description": "Professor name to find schedule and subjects for",
                },
                "list_all": {
                    "type": "boolean",
                    "description": "Set to true to list all professors across the timetable",
                },
            },
            "required": ["student_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "found": {"type": "boolean"},
            },
        },
    },
    {
        "name": "find_room_details",
        "description": (
            "Find schedule and activities held in a specific classroom or lab room "
            "(e.g. 'What classes are in room E-505?', 'What is my default classroom?')."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "room": {
                    "type": "string",
                    "description": "Room or lab code (e.g. 'E-505')",
                },
            },
            "required": ["student_id", "room"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "room": {"type": "string"},
                "is_default_classroom": {"type": "boolean"},
                "found": {"type": "boolean"},
                "sessions": {"type": "array"},
            },
        },
    },
    {
        "name": "query_schedule_analytics",
        "description": (
            "Calculate deterministic schedule statistics, counts, and frequencies from the "
            "confirmed timetable: 'subject_count' (count of sessions for a specific course or lab across "
            "the week or remaining days), 'classes_vs_labs' (total lectures vs practicals and hours), "
            "'daily_workload' (hours and session count distribution per day, heaviest/lightest day), "
            "or 'free_slots' (breaks and free intervals between scheduled classes)."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "metric": {
                    "type": "string",
                    "description": "Metric to calculate: 'classes_vs_labs', 'subject_count', 'daily_workload', 'free_slots'",
                    "enum": ["classes_vs_labs", "subject_count", "daily_workload", "free_slots"],
                },
                "subject": {
                    "type": ["string", "null"],
                    "description": "Target subject for subject_count (e.g. 'OS', 'PSA')",
                },
                "scope": {
                    "type": ["string", "null"],
                    "description": "'entire_week' or 'remaining_days' (from current day forward)",
                    "enum": ["entire_week", "remaining_days"],
                },
                "day": {
                    "type": ["integer", "string", "null"],
                    "description": "Target day (0=Mon, 5=Sat) for daily_workload or free_slots",
                },
            },
            "required": ["student_id", "metric"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "metric": {"type": "string"},
            },
        },
    },
]


# Tool implementations mapping
async def execute_timetable_tool(
    service: "TimetableService",
    tool_name: str,
    student_id: str,
    **kwargs,
) -> dict:
    """Execute a timetable tool by name."""
    if tool_name == "confirm_timetable":
        return await confirm_timetable(service, student_id)
    if tool_name == "get_schedule":
        return await get_schedule(service, student_id, kwargs.get("target_date"))
    if tool_name == "get_today_schedule":
        return await get_today_schedule(service, student_id)
    if tool_name == "get_tomorrow_schedule":
        return await get_tomorrow_schedule(service, student_id)
    if tool_name == "get_next_class":
        return await get_next_class(service, student_id)
    if tool_name == "get_first_class_tomorrow":
        return await get_first_class_tomorrow(service, student_id)
    if tool_name == "get_timetable_status":
        return await get_timetable_status(service, student_id)
    if tool_name == "needs_lab_batch":
        return await needs_lab_batch(service, student_id)
    if tool_name == "set_lab_batch":
        return await set_lab_batch(service, student_id, kwargs["batch"])
    if tool_name == "get_extracted_timetable":
        return await get_extracted_timetable(service, student_id)
    if tool_name == "update_timetable_entry":
        return await update_timetable_entry(service, student_id, **kwargs)
    if tool_name == "add_timetable_entry":
        return await add_timetable_entry(service, student_id, **kwargs)
    if tool_name == "delete_timetable_entry":
        return await delete_timetable_entry(service, student_id, **kwargs)
    if tool_name == "set_briefing_time":
        return await set_briefing_time(service, student_id, kwargs["briefing_time"])
    if tool_name == "get_week_schedule":
        return await get_week_schedule(service, student_id)
    if tool_name == "get_schedule_for_weekday":
        dow = kwargs.get("day_of_week")
        if dow is None:
            dow = kwargs.get("weekday") or kwargs.get("day")
        if isinstance(dow, str):
            dow_clean = dow.strip().lower()
            for idx, name in enumerate(DAY_NAMES):
                if name.lower().startswith(dow_clean) or dow_clean.startswith(
                    name.lower()[:3]
                ):
                    dow = idx
                    break
            else:
                try:
                    dow = int(dow_clean)
                except ValueError:
                    dow = 0
        elif dow is None:
            dow = 0
        return await get_schedule_for_weekday(
            service, student_id, dow
        )
    if tool_name == "get_timetable_metadata":
        return await get_timetable_metadata(service, student_id)
    if tool_name == "find_activity_details":
        return await find_activity_details(service, student_id, **kwargs)
    if tool_name == "find_faculty_details":
        return await find_faculty_details(service, student_id, **kwargs)
    if tool_name == "find_room_details":
        return await find_room_details(service, student_id, **kwargs)
    if tool_name == "query_schedule_analytics":
        return await query_schedule_analytics(service, student_id, **kwargs)
    raise ValueError(f"Unknown timetable tool: {tool_name}")
