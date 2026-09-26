"""
Attendance tools for LLM function calling.

These tools provide deterministic access to verified attendance data
and deterministic simulations.
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class OverallAttendanceResult:
    """Result for overall attendance query."""

    attended: int
    conducted: int
    percentage: float
    captured_at: str
    source: str
    semester_id: str | None

    def to_dict(self):
        return {
            "attended": self.attended,
            "conducted": self.conducted,
            "percentage": self.percentage,
            "captured_at": self.captured_at,
            "source": self.source,
            "semester_id": self.semester_id,
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
    """Complete attendance summary."""

    overall: dict
    subjects: tuple[dict, ...]
    captured_at: str
    source: str
    semester_id: str | None

    def to_dict(self):
        return {
            "overall": self.overall,
            "subjects": self.subjects,
            "captured_at": self.captured_at,
            "source": self.source,
            "semester_id": self.semester_id,
        }


@dataclass(frozen=True, slots=True)
class BelowTargetResult:
    """Subject below target percentage."""

    subject_code: str
    subject_name: str | None
    cumulative_percentage: float
    target_percentage: float
    deficit: float

    def to_dict(self):
        return {
            "subject_code": self.subject_code,
            "subject_name": self.subject_name,
            "cumulative_percentage": self.cumulative_percentage,
            "target_percentage": self.target_percentage,
            "deficit": self.deficit,
        }


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Result of absence simulation."""

    current_percentage: float
    projected_percentage: float
    projected_attended: int
    projected_conducted: int
    missed_classes: int
    future_classes: int

    def to_dict(self):
        return {
            "current_percentage": self.current_percentage,
            "projected_percentage": self.projected_percentage,
            "projected_attended": self.projected_attended,
            "projected_conducted": self.projected_conducted,
            "missed_classes": self.missed_classes,
            "future_classes": self.future_classes,
        }


@dataclass(frozen=True, slots=True)
class RecoveryResult:
    """Result of recovery calculation."""

    classes_needed: int
    projected_attended: int
    projected_conducted: int
    projected_percentage: float
    target_achieved: bool

    def to_dict(self):
        return {
            "classes_needed": self.classes_needed,
            "projected_attended": self.projected_attended,
            "projected_conducted": self.projected_conducted,
            "projected_percentage": self.projected_percentage,
            "target_achieved": self.target_achieved,
        }


async def get_overall_attendance(service, student_id: str):
    """Get overall attendance for the authenticated student."""
    result = await service.get_overall_attendance(student_id)
    if not result:
        return {
            "available": False,
            "message": (
                "No verified attendance data available. "
                "Upload and confirm a timetable first."
            ),
        }
    return {
        "available": True,
        "attended": result.attended,
        "conducted": result.conducted,
        "percentage": result.percentage,
        "captured_at": result.captured_at.isoformat(),
        "source": result.source,
        "semester_id": result.semester_id,
    }


async def get_subject_attendance(service, student_id: str, subject_code: str):
    """Get attendance for a specific subject."""
    result = await service.get_subject_attendance(student_id, subject_code)
    if not result:
        return {
            "available": False,
            "message": f"Subject {subject_code} not found in verified attendance data.",
        }
    return {
        "available": True,
        "subject_code": result.subject_code,
        "subject_name": result.subject_name,
        "monthly": {
            "attended": result.monthly_attended,
            "conducted": result.monthly_conducted,
            "percentage": result.monthly_percentage,
            "period": result.monthly_period,
        }
        if result.monthly_attended is not None
        else None,
        "cumulative": {
            "attended": result.cumulative_attended,
            "conducted": result.cumulative_conducted,
            "percentage": result.cumulative_percentage,
        },
    }


async def get_attendance_summary(service, student_id: str):
    """Get complete attendance summary."""
    result = await service.get_attendance_summary(student_id)
    if not result:
        return {
            "available": False,
            "message": "No verified attendance data available.",
        }

    return {
        "available": True,
        "overall": result.overall,
        "subjects": [s.to_dict() for s in result.subjects],
        "captured_at": result.captured_at.isoformat(),
        "source": result.source,
        "semester_id": result.semester_id,
    }


async def get_subjects_below_target(service, student_id: str, target_percentage: float):
    """Get subjects below a target percentage."""
    if target_percentage < 0 or target_percentage > 100:
        return {"error": "Target percentage must be between 0 and 100"}

    subjects = await service.get_subjects_below_target(student_id, target_percentage)
    return {
        "target_percentage": target_percentage,
        "subjects_below": [
            {
                "subject_code": s.subject_code,
                "subject_name": s.subject_name,
                "current_percentage": s.cumulative_percentage,
                "target_percentage": s.target_percentage,
                "deficit": s.deficit,
            }
            for s in subjects
        ],
    }


async def simulate_absence(
    attendance_service,
    timetable_service,
    student_id: str,
    subject_code: str,
    date_str: str | None = None,
    missed_classes: int = 1,
):
    """
    Simulate missing classes for a subject.

    If date is provided, uses confirmed timetable to determine future classes.
    Otherwise simulates missing 1 class.
    """
    try:
        if date_str:
            _ = date.fromisoformat(date_str)
            # We need the timetable service for date-based simulation
            return {
                "error": (
                    "Date-based simulation requires timetable service integration."
                ),
                "suggestion": (
                    "Use simulate_absence without date for simple "
                    "simulation, or ensure timetable is confirmed."
                ),
            }
        else:
            # Simple simulation - assumes 1 future class
            result = await attendance_service.simulate_absence(
                student_id=student_id,
                subject_code=subject_code,
                future_classes=1,
                missed_classes=min(missed_classes, 1),
            )
            return {
                "available": True,
                "subject_code": subject_code,
                "current_percentage": result.current_percentage,
                "projected_percentage": result.projected_percentage,
                "projected_attended": result.projected_attended,
                "projected_conducted": result.projected_conducted,
                "missed_classes": result.missed_classes,
                "future_classes": result.future_classes,
                "note": "Simulated missing 1 of 1 future class.",
            }
    except Exception as e:
        return {"error": str(e), "available": False}


async def simulate_absence_with_timetable(
    attendance_service,
    timetable_service,
    student_id: str,
    subject_code: str,
    date_str: str,
    missed_classes: int,
):
    """
    Simulate absence using confirmed timetable.

    Uses confirmed timetable to determine future classes on the
    specified date.
    """
    try:
        target_date = date.fromisoformat(date_str)
        result = await attendance_service.simulate_absence_with_timetable(
            student_id=student_id,
            subject_code=subject_code,
            target_date=target_date,
            missed_count=missed_classes,
            timetable_service=timetable_service,
        )

        if not result:
            return {
                "available": False,
                "message": (
                    "No future classes scheduled for this subject on "
                    "the specified date."
                ),
            }

        return {
            "available": True,
            "subject_code": subject_code,
            "date": date_str,
            "future_classes": result.future_classes,
            "missed_classes": result.missed_classes,
            "current_percentage": result.current_percentage,
            "projected_percentage": result.projected_percentage,
            "projected_attended": result.projected_attended,
            "projected_conducted": result.projected_conducted,
        }
    except ValueError:
        return {
            "error": f"Invalid date format: {date_str}. Use YYYY-MM-DD.",
            "available": False,
        }
    except Exception:
        return {
            "error": "Simulation failed",
            "available": False,
        }


async def calculate_classes_needed(
    service, student_id: str, subject_code: str, target_percentage: float
):
    """Calculate minimum classes needed to reach target percentage."""
    if target_percentage < 0 or target_percentage > 100:
        return {"error": "Target percentage must be between 0 and 100"}

    try:
        result = await service.calculate_classes_needed(
            student_id=student_id,
            subject_code=subject_code,
            target_percentage=target_percentage,
        )

        if result.target_achieved:
            return {
                "already_achieved": True,
                "classes_needed": 0,
                "current_percentage": result.projected_percentage,
                "target_percentage": target_percentage,
            }

        return {
            "already_achieved": False,
            "classes_needed": result.classes_needed,
            "projected_attended": result.projected_attended,
            "projected_conducted": result.projected_conducted,
            "projected_percentage": result.projected_percentage,
            "target_percentage": target_percentage,
        }
    except Exception:
        return {"error": "Calculation failed"}


async def get_attendance_snapshot_info(service, student_id: str):
    """Get metadata about the latest attendance snapshot."""
    info = await service.get_snapshot_info(student_id)
    if not info:
        return {
            "available": False,
            "message": "No verified attendance snapshot available.",
        }
    return {
        "available": True,
        "snapshot_id": info["snapshot_id"],
        "captured_at": info["captured_at"],
        "source": info["source"],
        "semester_id": info["semester_id"],
        "overall_percentage": info["overall_percentage"],
    }


async def get_subject_codes(service, student_id: str):
    """Get all subject codes from verified attendance data."""
    codes = await service.get_all_subject_codes(student_id)
    return {"subject_codes": list(codes)}


# Tool definitions for registry
ATTENDANCE_TOOL_DEFINITIONS = [
    {
        "name": "get_overall_attendance",
        "description": "Get the student's overall attendance percentage.",
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
                "available": {"type": "boolean"},
                "attended": {"type": ["integer", "null"]},
                "conducted": {"type": ["integer", "null"]},
                "percentage": {"type": ["number", "null"]},
                "captured_at": {"type": ["string", "null"]},
                "source": {"type": ["string", "null"]},
                "semester_id": {"type": ["string", "null"]},
                "message": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "get_subject_attendance",
        "description": "Get attendance for a specific subject.",
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "subject_code": {"type": "string"},
            },
            "required": ["student_id", "subject_code"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "available": {"type": "boolean"},
                "subject_code": {"type": "string"},
                "subject_name": {"type": ["string", "null"]},
                "monthly": {
                    "type": ["object", "null"],
                    "properties": {
                        "attended": {"type": ["integer", "null"]},
                        "conducted": {"type": ["integer", "null"]},
                        "percentage": {"type": ["number", "null"]},
                        "period": {"type": ["string", "null"]},
                    },
                },
                "cumulative": {
                    "type": "object",
                    "properties": {
                        "attended": {"type": "integer"},
                        "conducted": {"type": "integer"},
                        "percentage": {"type": "number"},
                    },
                },
                "message": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "get_attendance_summary",
        "description": "Get complete attendance summary including all subjects.",
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
                "available": {"type": "boolean"},
                "overall": {"type": ["object", "null"]},
                "subjects": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "subject_code": {"type": "string"},
                            "subject_name": {"type": ["string", "null"]},
                            "monthly_attended": {"type": ["integer", "null"]},
                            "monthly_conducted": {"type": ["integer", "null"]},
                            "monthly_percentage": {"type": ["number", "null"]},
                            "monthly_period": {"type": ["string", "null"]},
                            "cumulative_attended": {"type": "integer"},
                            "cumulative_conducted": {"type": "integer"},
                            "cumulative_percentage": {"type": "number"},
                        },
                    },
                },
                "captured_at": {"type": ["string", "null"]},
                "source": {"type": ["string", "null"]},
                "semester_id": {"type": ["string", "null"]},
                "message": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "get_subjects_below_target",
        "description": "Get subjects below a target attendance percentage.",
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "target_percentage": {"type": "number", "minimum": 0, "maximum": 100},
            },
            "required": ["student_id", "target_percentage"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "target_percentage": {"type": "number"},
                "subjects_below": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "subject_code": {"type": "string"},
                            "subject_name": {"type": ["string", "null"]},
                            "current_percentage": {"type": "number"},
                            "target_percentage": {"type": "number"},
                            "deficit": {"type": "number"},
                        },
                    },
                },
                "error": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "simulate_absence",
        "description": (
            "Simulate the impact of missing future classes. "
            "Uses confirmed timetable if date provided."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "subject_code": {"type": "string"},
                "date": {
                    "type": "string",
                    "format": "date",
                    "description": ("Optional: date for timetable-based simulation"),
                },
                "missed_classes": {"type": "integer", "minimum": 1, "default": 1},
            },
            "required": ["student_id", "subject_code"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "available": {"type": "boolean"},
                "subject_code": {"type": "string"},
                "current_percentage": {"type": "number"},
                "projected_percentage": {"type": "number"},
                "projected_attended": {"type": "integer"},
                "projected_conducted": {"type": "integer"},
                "missed_classes": {"type": "integer"},
                "future_classes": {"type": "integer"},
                "note": {"type": ["string", "null"]},
                "error": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "calculate_classes_needed",
        "description": (
            "Calculate minimum consecutive classes needed to reach "
            "a target attendance percentage."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "subject_code": {"type": "string"},
                "target_percentage": {"type": "number", "minimum": 0, "maximum": 100},
            },
            "required": ["student_id", "subject_code", "target_percentage"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "already_achieved": {"type": "boolean"},
                "classes_needed": {"type": "integer"},
                "projected_attended": {"type": ["integer", "null"]},
                "projected_conducted": {"type": ["integer", "null"]},
                "projected_percentage": {"type": ["number", "null"]},
                "target_percentage": {"type": "number"},
                "current_percentage": {"type": ["number", "null"]},
                "error": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "get_attendance_snapshot_info",
        "description": ("Get metadata about the latest verified attendance snapshot."),
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
                "available": {"type": "boolean"},
                "snapshot_id": {"type": ["string", "null"]},
                "captured_at": {"type": ["string", "null"]},
                "source": {"type": ["string", "null"]},
                "semester_id": {"type": ["string", "null"]},
                "overall_percentage": {"type": ["number", "null"]},
                "message": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "get_subject_codes",
        "description": "Get all subject codes from verified attendance data.",
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
                "subject_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
    },
]


# Tool implementations mapping
async def execute_attendance_tool(
    attendance_service, timetable_service, tool_name: str, student_id: str, **kwargs
):
    """Execute an attendance tool by name."""
    if tool_name == "get_overall_attendance":
        return await get_overall_attendance(attendance_service, student_id)
    elif tool_name == "get_subject_attendance":
        return await get_subject_attendance(
            attendance_service, student_id, kwargs["subject_code"]
        )
    elif tool_name == "get_attendance_summary":
        return await get_attendance_summary(attendance_service, student_id)
    elif tool_name == "get_subjects_below_target":
        return await get_subjects_below_target(
            attendance_service, student_id, kwargs["target_percentage"]
        )
    elif tool_name == "simulate_absence":
        # For simple simulation without date
        if not kwargs.get("date"):
            return await simulate_absence(
                attendance_service,
                None,
                student_id,
                kwargs["subject_code"],
                None,
                kwargs.get("missed_classes", 1),
            )
        # Date-based simulation requires timetable service
        return await simulate_absence_with_timetable(
            attendance_service,
            timetable_service,
            student_id,
            kwargs["subject_code"],
            kwargs["date"],
            kwargs.get("missed_classes", 1),
        )
    elif tool_name == "calculate_classes_needed":
        return await calculate_classes_needed(
            attendance_service,
            student_id,
            kwargs["subject_code"],
            kwargs["target_percentage"],
        )
    elif tool_name == "get_attendance_snapshot_info":
        return await get_attendance_snapshot_info(attendance_service, student_id)
    elif tool_name == "get_subject_codes":
        return await get_subject_codes(attendance_service, student_id)
    else:
        raise ValueError(f"Unknown attendance tool: {tool_name}")
