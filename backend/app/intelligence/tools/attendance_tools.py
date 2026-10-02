"""
Attendance tools for LLM function calling.

These tools provide deterministic access to verified attendance data
and deterministic simulations.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any

# Tool Taxonomy Sets
MUTATION_TOOLS: frozenset[str] = frozenset({
    "set_attendance_target",
    "sync_attendance",
    "start_portal_connection",
})

SIMULATION_TOOLS: frozenset[str] = frozenset({
    "calculate_bunk_allowance",
    "simulate_day_absence",
    "simulate_absence",
    "calculate_classes_needed",
})

READ_TOOLS: frozenset[str] = frozenset({
    "get_overall_attendance",
    "get_subject_attendance",
    "get_attendance_summary",
    "get_attendance_extremes",
    "get_subjects_below_target",
    "get_attendance_snapshot_info",
    "get_subject_codes",
})


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


async def get_overall_attendance(
    service, student_id: str, semester_id: str | None = None
):
    """Get overall attendance for the authenticated student."""
    result = await service.get_overall_attendance(student_id, semester_id=semester_id)
    if not result:
        return {
            "available": False,
            "message": (
                "No verified attendance data available. "
                "Upload and confirm a timetable or connect your college portal first."
            ),
        }
    return {
        "available": True,
        "attended": result.attended,
        "conducted": result.conducted,
        "percentage": result.percentage,
        "cumulative_attended": result.attended,
        "cumulative_conducted": result.conducted,
        "cumulative_percentage": result.percentage,
        "monthly_attended": result.monthly_attended,
        "monthly_conducted": result.monthly_conducted,
        "monthly_percentage": result.monthly_percentage,
        "monthly_period": result.monthly_period,
        "captured_at": result.captured_at.isoformat()
        if hasattr(result.captured_at, "isoformat")
        else str(result.captured_at),
        "source": result.source,
        "semester_id": result.semester_id,
        "provenance": getattr(result, "provenance", "portal_snapshot_fresh"),
        "notice": getattr(result, "notice", None),
        "target_percentage": getattr(result, "target_percentage", 75.0),
        "target_difference": getattr(result, "target_difference", 0.0),
        "target_status": getattr(result, "target_status", "at_target"),
        "target_gap_percentage": getattr(result, "target_gap_percentage", 0.0),
        "legacy_snapshot_reconciled": getattr(
            result, "legacy_snapshot_reconciled", False
        ),
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


async def get_attendance_summary(
    service, student_id: str, semester_id: str | None = None
):
    """Get complete attendance summary."""
    result = await service.get_attendance_summary(student_id, semester_id=semester_id)
    if not result:
        return {
            "available": False,
            "message": "No verified attendance data available.",
        }

    overall_dict = (
        result.overall.to_dict()
        if hasattr(result.overall, "to_dict")
        else {
            "attended": result.overall.get("attended", 0),
            "conducted": result.overall.get("conducted", 0),
            "percentage": result.overall.get("percentage", 0.0),
            "cumulative_attended": result.overall.get("attended", 0),
            "cumulative_conducted": result.overall.get("conducted", 0),
            "cumulative_percentage": result.overall.get("percentage", 0.0),
            "target_percentage": result.overall.get("target_percentage", 75.0),
            "target_difference": result.overall.get("target_difference", 0.0),
            "target_status": result.overall.get("target_status", "at_target"),
            "target_gap_percentage": result.overall.get("target_gap_percentage", 0.0),
            "legacy_snapshot_reconciled": result.overall.get(
                "legacy_snapshot_reconciled", False
            ),
        }
        if isinstance(result.overall, dict)
        else {
            "attended": getattr(result.overall, "attended", 0),
            "conducted": getattr(result.overall, "conducted", 0),
            "percentage": getattr(result.overall, "percentage", 0.0),
            "cumulative_attended": getattr(result.overall, "attended", 0),
            "cumulative_conducted": getattr(result.overall, "conducted", 0),
            "cumulative_percentage": getattr(result.overall, "percentage", 0.0),
            "target_percentage": getattr(result.overall, "target_percentage", 75.0),
            "target_difference": getattr(result.overall, "target_difference", 0.0),
            "target_status": getattr(result.overall, "target_status", "at_target"),
            "target_gap_percentage": getattr(
                result.overall, "target_gap_percentage", 0.0
            ),
            "legacy_snapshot_reconciled": getattr(
                result.overall, "legacy_snapshot_reconciled", False
            ),
        }
    )

    return {
        "available": True,
        "overall": overall_dict,
        "subjects": [
            s.to_dict() if hasattr(s, "to_dict") else s for s in result.subjects
        ],
        "captured_at": result.captured_at.isoformat()
        if hasattr(result.captured_at, "isoformat")
        else str(result.captured_at),
        "source": result.source,
        "semester_id": result.semester_id,
        "provenance": getattr(result, "provenance", "portal_snapshot_fresh"),
        "notice": getattr(result, "notice", None),
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


async def sync_attendance(service, student_id: str, semester_id: str | None = None):
    """Sync attendance from the portal and store as verified snapshot."""
    try:
        result = await service.sync_attendance(
            student_id=student_id,
            semester_id=semester_id,
        )
        return {
            "success": result.success,
            "snapshot_id": result.snapshot_id,
            "captured_at": result.captured_at,
            "overall_percentage": result.overall_percentage,
            "subject_count": result.subject_count,
            "message": result.message,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def set_attendance_target(
    service, student_id: str, target_percentage: float
):
    """Set and verify student's target attendance percentage."""
    try:
        return await service.set_attendance_target(
            student_id=student_id, target_percentage=target_percentage
        )
    except Exception as e:
        return {"success": False, "error": str(e)}


async def calculate_bunk_allowance(
    service, student_id: str, subject_code: str | None = None
):
    """Calculate maximum safe classes that can be missed."""
    try:
        return await service.calculate_bunk_allowance(
            student_id=student_id, subject_code=subject_code
        )
    except Exception as e:
        return {"available": False, "error": str(e)}


async def simulate_day_absence(
    attendance_service, timetable_service, student_id: str, day: str = "tomorrow"
):
    """Simulate missing classes for an entire day based on confirmed timetable."""
    try:
        return await attendance_service.simulate_day_absence(
            student_id=student_id,
            day=day,
            timetable_service=timetable_service,
        )
    except Exception as e:
        return {"available": False, "error": str(e)}


async def get_attendance_extremes(service, student_id: str):
    """Get subjects with lowest and highest attendance."""
    try:
        return await service.get_attendance_extremes(student_id=student_id)
    except Exception as e:
        return {"available": False, "error": str(e)}


async def calculate_classes_needed(
    service,
    student_id: str,
    subject_code: str | None = None,
    target_percentage: float | None = None,
):
    """Calculate minimum classes needed to reach target percentage."""
    if target_percentage is not None and (
        target_percentage < 0 or target_percentage > 100
    ):
        return {"error": "Target percentage must be between 0 and 100"}

    try:
        result = await service.calculate_classes_needed(
            student_id=student_id,
            subject_code=subject_code,
            target_percentage=target_percentage,
        )

        if not getattr(result, "achievable", True):
            return {
                "already_achieved": False,
                "achievable": False,
                "classes_needed": None,
                "current_percentage": result.projected_percentage,
                "target_percentage": target_percentage,
                "message": getattr(
                    result,
                    "message",
                    "Target attendance cannot be achieved mathematically because classes have already been missed.",
                ),
            }

        if result.target_achieved:
            return {
                "already_achieved": True,
                "achievable": True,
                "classes_needed": 0,
                "current_percentage": result.projected_percentage,
                "target_percentage": target_percentage,
            }

        return {
            "already_achieved": False,
            "achievable": True,
            "classes_needed": result.classes_needed,
            "projected_attended": result.projected_attended,
            "projected_conducted": result.projected_conducted,
            "projected_percentage": result.projected_percentage,
            "target_percentage": target_percentage,
        }
    except Exception as e:
        return {"error": f"Calculation failed: {e!s}"}


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
        "name": "set_attendance_target",
        "description": (
            "Set and update the student's target attendance percentage (e.g. 67%, 75%, 80%). "
            "Persists the new target to the database, re-verifies the committed state, "
            "and returns verified post-mutation progress."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "target_percentage": {
                    "type": "number",
                    "minimum": 1.0,
                    "maximum": 100.0,
                    "description": "The new target attendance percentage (between 1.0 and 100.0).",
                },
            },
            "required": ["student_id", "target_percentage"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "mutation": {"type": "object"},
                "attendance": {"type": "object"},
                "target": {"type": "object"},
                "provenance": {"type": "object"},
                "error": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "calculate_bunk_allowance",
        "description": (
            "Calculate how many classes the student can safely miss/bunk without dropping below "
            "their attendance target. Can calculate for a specific subject or overall across all subjects."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "subject_code": {
                    "type": ["string", "null"],
                    "description": "Optional: subject code or name to calculate safe bunks for. If omitted, calculates for overall and all subjects.",
                },
            },
            "required": ["student_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "available": {"type": "boolean"},
                "is_overall": {"type": "boolean"},
                "subject_code": {"type": ["string", "null"]},
                "subject_name": {"type": ["string", "null"]},
                "safe_bunks": {"type": ["integer", "null"]},
                "current_percentage": {"type": ["number", "null"]},
                "projected_percentage_after_bunk": {"type": ["number", "null"]},
                "status": {"type": "string"},
                "subjects": {"type": ["array", "null"]},
                "message": {"type": ["string", "null"]},
                "error": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "simulate_day_absence",
        "description": (
            "Simulate missing all scheduled classes on a specific day (e.g. 'tomorrow', 'today', 'Monday', 'Friday'). "
            "Uses the student's CONFIRMED timetable to aggregate periods and predicts impact on individual subjects "
            "and overall attendance with safety checks."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "day": {
                    "type": "string",
                    "description": "Day identifier: 'tomorrow', 'today', or a named weekday like 'Monday', 'Friday'. Defaults to 'tomorrow'.",
                },
            },
            "required": ["student_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "available": {"type": "boolean"},
                "date": {"type": ["string", "null"]},
                "day_name": {"type": ["string", "null"]},
                "scheduled_classes_count": {"type": "integer"},
                "current_overall_percentage": {"type": ["number", "null"]},
                "projected_overall_percentage": {"type": ["number", "null"]},
                "overall_safe": {"type": "boolean"},
                "subjects_safe": {"type": "boolean"},
                "is_safe": {"type": "boolean"},
                "affected_subjects": {"type": ["array", "null"]},
                "message": {"type": ["string", "null"]},
                "error": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "get_attendance_extremes",
        "description": (
            "Identify the student's subjects with the lowest and highest attendance percentages. "
            "Handles multi-course ties gracefully and groups subjects into at-risk vs safe."
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
                "available": {"type": "boolean"},
                "overall_percentage": {"type": ["number", "null"]},
                "target_percentage": {"type": ["number", "null"]},
                "lowest": {"type": "array"},
                "highest": {"type": "array"},
                "below_target": {"type": "array"},
                "at_or_above_target": {"type": "array"},
                "total_subjects": {"type": "integer"},
                "message": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "get_overall_attendance",
        "description": "Get the student's overall attendance percentage and current month attendance.",
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "semester_id": {
                    "type": ["string", "null"],
                    "description": "Optional semester ID to view attendance for a specific semester.",
                },
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
                "monthly_attended": {"type": ["integer", "null"]},
                "monthly_conducted": {"type": ["integer", "null"]},
                "monthly_percentage": {"type": ["number", "null"]},
                "monthly_period": {"type": ["string", "null"]},
                "captured_at": {"type": ["string", "null"]},
                "source": {"type": ["string", "null"]},
                "semester_id": {"type": ["string", "null"]},
                "target_percentage": {"type": ["number", "null"]},
                "target_difference": {"type": ["number", "null"]},
                "target_status": {"type": ["string", "null"]},
                "target_gap_percentage": {"type": ["number", "null"]},
                "legacy_snapshot_reconciled": {"type": ["boolean", "null"]},
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
        "description": (
            "Get complete subject-wise attendance breakdown and summary. "
            "Use this whenever the student asks for subject breakdown, per-subject attendance, "
            "or detailed attendance stats."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "semester_id": {
                    "type": ["string", "null"],
                    "description": "Optional semester ID to view attendance for a specific semester.",
                },
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
                            "classes_needed": {"type": ["integer", "null"]},
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
            "a target attendance percentage, either overall or for a specific subject."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "subject_code": {
                    "type": ["string", "null"],
                    "description": "Optional: subject code or name. If omitted, calculates for overall attendance.",
                },
                "target_percentage": {
                    "type": ["number", "null"],
                    "minimum": 0,
                    "maximum": 100,
                    "description": "Optional target percentage. If omitted, uses student's configured target.",
                },
            },
            "required": ["student_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "already_achieved": {"type": "boolean"},
                "achievable": {"type": "boolean"},
                "classes_needed": {"type": ["integer", "null"]},
                "projected_attended": {"type": ["integer", "null"]},
                "projected_conducted": {"type": ["integer", "null"]},
                "projected_percentage": {"type": ["number", "null"]},
                "target_percentage": {"type": ["number", "null"]},
                "current_percentage": {"type": ["number", "null"]},
                "message": {"type": ["string", "null"]},
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
        "name": "sync_attendance",
        "description": (
            "Sync attendance data from the Doctus portal. "
            "This fetches the latest attendance from the college portal and "
            "stores it as a verified snapshot."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {
                "student_id": {"type": "string", "format": "uuid"},
                "semester_id": {
                    "type": "string",
                    "description": (
                        "Optional: specific semester to sync. "
                        "If not provided, uses the most recent semester."
                    ),
                },
            },
            "required": ["student_id"],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "snapshot_id": {"type": ["string", "null"]},
                "captured_at": {"type": ["string", "null"]},
                "overall_percentage": {"type": ["number", "null"]},
                "subject_count": {"type": ["integer", "null"]},
                "message": {"type": ["string", "null"]},
                "error": {"type": ["string", "null"]},
            },
        },
    },
    {
        "name": "start_portal_connection",
        "description": (
            "Starts the secure portal credential onboarding or reconnection flow "
            "when the student expresses an intention to connect or reconnect their college attendance portal."
        ),
        "arguments_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "result_schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "message": {"type": "string"},
            },
        },
    },
]


# Tool implementations mapping
async def execute_attendance_tool(
    attendance_service,
    timetable_service,
    tool_name: str,
    student_id: str,
    portal_onboarding_service=None,
    chat_id: int | None = None,
    **kwargs,
):
    """Execute an attendance tool by name."""
    if tool_name == "set_attendance_target":
        return await set_attendance_target(
            attendance_service, student_id, kwargs["target_percentage"]
        )
    elif tool_name == "calculate_bunk_allowance":
        return await calculate_bunk_allowance(
            attendance_service, student_id, kwargs.get("subject_code")
        )
    elif tool_name == "simulate_day_absence":
        return await simulate_day_absence(
            attendance_service,
            timetable_service,
            student_id,
            kwargs.get("day", "tomorrow"),
        )
    elif tool_name == "get_attendance_extremes":
        return await get_attendance_extremes(attendance_service, student_id)
    elif tool_name == "start_portal_connection":
        msg = "Sure, Sir. Please send your college roll number."
        if portal_onboarding_service and chat_id:
            from uuid import UUID
            msg = portal_onboarding_service.start_flow(UUID(student_id), chat_id)
        return {
            "status": "AWAITING_ROLL_NUMBER",
            "message": msg,
        }
    elif tool_name == "get_overall_attendance":
        return await get_overall_attendance(
            attendance_service, student_id, kwargs.get("semester_id")
        )
    elif tool_name == "get_subject_attendance":
        return await get_subject_attendance(
            attendance_service, student_id, kwargs["subject_code"]
        )
    elif tool_name == "get_attendance_summary":
        return await get_attendance_summary(
            attendance_service, student_id, kwargs.get("semester_id")
        )
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
            kwargs.get("subject_code"),
            kwargs.get("target_percentage"),
        )
    elif tool_name == "get_attendance_snapshot_info":
        return await get_attendance_snapshot_info(attendance_service, student_id)
    elif tool_name == "get_subject_codes":
        return await get_attendance_summary(
            attendance_service, student_id, kwargs.get("semester_id")
        )
    elif tool_name == "sync_attendance":
        return await sync_attendance(
            attendance_service, student_id, kwargs.get("semester_id")
        )
    else:
        raise ValueError(f"Unknown attendance tool: {tool_name}")
