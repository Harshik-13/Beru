"""Renderer Registry for Beru.

Maps tool names to deterministic domain renderers:
Tool Result -> RendererRegistry -> DomainRenderer -> Style Contract -> Telegram
Keeps ConversationService free of presentation logic.
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


class RendererRegistry:
    """Central registry mapping tool execution results to dedicated domain renderers."""

    def __init__(self, default_renderer: DomainRenderer | None = None) -> None:
        self._renderers: dict[str, DomainRenderer] = {}
        self._default_renderer = default_renderer or DefaultRenderer()

    def register(self, tool_name: str, renderer: DomainRenderer) -> None:
        """Register a domain renderer for a specific tool name."""
        self._renderers[tool_name] = renderer

    def register_many(
        self, tool_names: set[str] | list[str], renderer: DomainRenderer
    ) -> None:
        """Register a domain renderer for multiple tool names."""
        for name in tool_names:
            self._renderers[name] = renderer

    def get_renderer(self, tool_name: str) -> DomainRenderer:
        """Get the renderer registered for tool_name, or default fallback."""
        return self._renderers.get(tool_name, self._default_renderer)

    def render(
        self,
        tool_name: str,
        result: dict[str, Any],
        student_context: StudentContext,
        user_message: str = "",
    ) -> str:
        """Dispatch rendering to appropriate domain renderer."""
        renderer = self.get_renderer(tool_name)
        try:
            return renderer.render(
                tool_name=tool_name,
                result=result,
                student_context=student_context,
                user_message=user_message,
            )
        except Exception as e:
            logger.exception("Error rendering response for tool %s: %s", tool_name, e)
            return self._default_renderer.render(
                tool_name=tool_name,
                result=result,
                student_context=student_context,
                user_message=user_message,
            )


def create_default_renderer_registry() -> RendererRegistry:
    """Create default RendererRegistry populated with domain renderers."""
    registry = RendererRegistry()

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
    }
    registry.register_many(timetable_tools, schedule_renderer)

    # Attendance Tools
    attendance_tools = {
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
