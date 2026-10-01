"""
Normalized DTOs for Doctus portal data.

These DTOs represent the normalized data structures returned
by the Doctus adapter, decoupled from the portal's internal
HTML/JSON structure.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SemesterOption:
    """A semester option from the portal's dropdown."""

    semester_id: str
    display_name: str
    is_selected: bool = False


@dataclass(frozen=True, slots=True)
class PortalStudentContext:
    """
    Portal-derived student context.

    Contains session-derived identifiers needed for attendance
    requests. NOT the same as Beru's permanent student identity.
    """

    protected_student_id: str
    raw_cookie: str  # Session cookie for authenticated requests


@dataclass(frozen=True, slots=True)
class PortalSubjectAttendance:
    """Normalized subject attendance from portal."""

    subject_code: str
    subject_name: str | None
    monthly_period: str | None
    monthly_attended: int | None
    monthly_conducted: int | None
    cumulative_attended: int
    cumulative_conducted: int


@dataclass(frozen=True, slots=True)
class PortalAttendance:
    """Normalized attendance data from Doctus portal."""

    source: str
    semester_id: str
    overall_attended: int
    overall_conducted: int
    overall_percentage_from_portal: float | None
    subjects: tuple[PortalSubjectAttendance, ...]
    monthly_period: str | None = None
