"""Beru Deterministic Rendering Package."""

from app.intelligence.rendering.attendance_renderer import AttendanceRenderer
from app.intelligence.rendering.briefing_renderer import BriefingRenderer
from app.intelligence.rendering.registry import (
    DefaultRenderer,
    DomainRenderer,
    RendererRegistry,
    create_default_renderer_registry,
)
from app.intelligence.rendering.schedule_renderer import (
    ScheduleRenderer,
    merge_contiguous_entries,
    resolve_batch_and_filter,
)
from app.intelligence.rendering.style_contract import (
    CHECK_MARK,
    HONORIFIC,
    WARNING_SIGN,
    clean_greetings,
    format_badge,
    format_label_value,
    format_percentage,
    format_time_span,
    sanitize_conversational_response,
)

__all__ = [
    "CHECK_MARK",
    "HONORIFIC",
    "WARNING_SIGN",
    "AttendanceRenderer",
    "BriefingRenderer",
    "DefaultRenderer",
    "DomainRenderer",
    "RendererRegistry",
    "ScheduleRenderer",
    "clean_greetings",
    "create_default_renderer_registry",
    "format_badge",
    "format_label_value",
    "format_percentage",
    "format_time_span",
    "merge_contiguous_entries",
    "resolve_batch_and_filter",
    "sanitize_conversational_response",
]
