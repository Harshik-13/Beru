"""Response Renderer Registry for Beru.

Maps tool execution results and typed domain objects to deterministic domain renderers,
then passes the rendered content through ResponseStyleLayer to inject Beru's persona:
Tool Result -> ResponseRendererRegistry -> DomainRenderer -> ResponseStyleLayer -> Telegram

Keeps ConversationService free of presentation logic and domain renderers free of persona.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from app.intelligence.rendering.attendance_renderer import AttendanceRenderer
from app.intelligence.rendering.briefing_renderer import BriefingRenderer
from app.intelligence.rendering.schedule_renderer import ScheduleRenderer
from app.intelligence.rendering.style_contract import (
    HONORIFIC,
    sanitize_conversational_response,
)
from app.intelligence.rendering.style_layer import ResponseStyleLayer

if TYPE_CHECKING:
    from app.intelligence.models.context import StudentContext

logger = logging.getLogger(__name__)


class DomainRenderer(Protocol):
    """Protocol for all domain-specific response renderers."""

    def render(
        self,
        tool_name: str,
        result: dict[str, Any],
        student_context: StudentContext,
        user_message: str = "",
    ) -> str:
        """Render tool execution result into structured message text."""
        ...


class DefaultRenderer:
    """Fallback renderer for tools without specialized domain renderers."""

    def render(
        self,
        tool_name: str,
        result: dict[str, Any],
        student_context: StudentContext,
        user_message: str = "",
    ) -> str:
        """Render generic tool result."""
        if isinstance(result, dict) and "message" in result:
            msg = str(result["message"])
        elif isinstance(result, str):
            msg = result
        else:
            msg = str(result)

        cleaned = sanitize_conversational_response(msg, honorific=HONORIFIC)
        return cleaned


class ResponseRendererRegistry:
    """Central registry mapping tool execution results to dedicated domain renderers."""

    def __init__(
        self,
        default_renderer: DomainRenderer | None = None,
        style_layer: ResponseStyleLayer | None = None,
    ) -> None:
        self._type_renderers: dict[type, DomainRenderer] = {}
        self._tool_renderers: dict[str, DomainRenderer] = {}
        self._default_renderer = default_renderer or DefaultRenderer()
        self._style_layer = style_layer or ResponseStyleLayer()

    def register(self, tool_name: str, renderer: DomainRenderer) -> None:
        """Register a domain renderer for a specific tool name."""
        self._tool_renderers[tool_name] = renderer

    def register_type(self, result_type: type, renderer: DomainRenderer) -> None:
        """Register a domain renderer for a typed result class."""
        self._type_renderers[result_type] = renderer

    def register_many(
        self, tool_names: set[str] | list[str], renderer: DomainRenderer
    ) -> None:
        """Register a domain renderer for multiple tool names."""
        for name in tool_names:
            self._tool_renderers[name] = renderer

    def get_renderer(self, tool_name: str = "", result: Any = None) -> DomainRenderer:
        """Get the renderer registered for a result type or tool_name, or default fallback."""
        if result is not None:
            r_type = type(result)
            if r_type in self._type_renderers:
                return self._type_renderers[r_type]

        if tool_name and tool_name in self._tool_renderers:
            return self._tool_renderers[tool_name]

        return self._default_renderer

    def render(
        self,
        tool_name: str = "",
        result: Any = None,
        student_context: StudentContext | None = None,
        user_message: str = "",
    ) -> str:
        """Dispatch rendering to domain renderer, then apply ResponseStyleLayer."""
        renderer = self.get_renderer(tool_name=tool_name, result=result)
        try:
            rendered = renderer.render(
                tool_name=tool_name,
                result=result,
                student_context=student_context,  # type: ignore[arg-type]
                user_message=user_message,
            )
        except Exception as e:
            logger.exception("Error rendering response for tool %s: %s", tool_name, e)
            rendered = self._default_renderer.render(
                tool_name=tool_name,
                result=result,
                student_context=student_context,  # type: ignore[arg-type]
                user_message=user_message,
            )

        # Apply ResponseStyleLayer (personality, honorific 'Sir', layout normalization)
        return self._style_layer.apply(rendered, student_context)


# Alias for backward compatibility
RendererRegistry = ResponseRendererRegistry


def create_default_renderer_registry() -> ResponseRendererRegistry:
    """Create default ResponseRendererRegistry populated with domain renderers."""
    registry = ResponseRendererRegistry()

    schedule_renderer = ScheduleRenderer()
    attendance_renderer = AttendanceRenderer()
    briefing_renderer = BriefingRenderer()

    # Timetable & Schedule Tools
    timetable_tools = {
        "get_schedule",
        "get_today_schedule",
        "get_tomorrow_schedule",
        "get_schedule_for_weekday",
        "get_next_class",
        "get_first_class_tomorrow",
        "get_week_schedule",
        "get_timetable_status",
        "get_extracted_timetable",
        "set_lab_batch",
        "confirm_timetable",
        "needs_lab_batch",
        "get_timetable_metadata",
        "find_activity_details",
        "find_faculty_details",
        "find_room_details",
        "query_schedule_analytics",
        "get_course_mapping",
    }
    registry.register_many(timetable_tools, schedule_renderer)

    # Attendance Tools
    attendance_tools = {
        "set_attendance_target",
        "calculate_bunk_allowance",
        "simulate_day_absence",
        "simulate_schedule_scenario",
        "simulate_subject_periods",
        "get_attendance_extremes",
        "get_attendance_summary",
        "get_overall_attendance",
        "get_subject_attendance",
        "simulate_absence",
        "get_subjects_below_target",
        "calculate_classes_needed",
        "get_attendance_snapshot_info",
        "sync_attendance",
    }
    registry.register_many(attendance_tools, attendance_renderer)

    # Briefing Tools
    briefing_tools = {
        "get_daily_briefing",
        "generate_daily_briefing",
        "get_briefing",
    }
    registry.register_many(briefing_tools, briefing_renderer)

    return registry
