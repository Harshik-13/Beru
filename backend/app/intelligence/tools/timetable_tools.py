"""
Timetable tools for LLM function calling.

These tools provide deterministic access to confirmed timetable data.
"""

from dataclasses import dataclass
from datetime import date, timedelta
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
            if entry.lab_batch == LabBatch.UNKNOWN and "/" in entry.activity_name:
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


# Tool definitions for registry
TIMETABLE_TOOL_DEFINITIONS = [
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
        "description": "Get today's class schedule.",
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
        "description": "Get tomorrow's class schedule.",
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
            "Get the current status of the student's timetable "
            "(confirmed, pending, none)."
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
]


# Tool implementations mapping
async def execute_timetable_tool(
    service: "TimetableService",
    tool_name: str,
    student_id: str,
    **kwargs,
) -> dict:
    """Execute a timetable tool by name."""
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
    raise ValueError(f"Unknown timetable tool: {tool_name}")
