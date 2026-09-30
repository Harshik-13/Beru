"""Deterministic Briefing Renderer.

Renders daily morning briefings into clean, ChatGPT-style Telegram HTML responses.
Enforces:
- Morning greeting with 'Sir' honorific
- Structured schedule highlights with time badges and room locations
- Key attendance metrics
- Clean closing
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.intelligence.rendering.schedule_renderer import (
    _normalize_batch_str,
    merge_contiguous_entries,
    resolve_batch_and_filter,
)
from app.intelligence.rendering.style_contract import (
    CHECK_MARK,
    HONORIFIC,
    WARNING_SIGN,
    format_percentage,
    format_time_span,
)

if TYPE_CHECKING:
    from app.intelligence.models.context import StudentContext


class BriefingRenderer:
    """Renderer for daily morning briefing tool results."""

    def render(
        self,
        tool_name: str,
        result: dict[str, Any],
        student_context: StudentContext,
        user_message: str = "",
    ) -> str:
        """Render daily briefing result."""
        date_str = result.get("date", "Today")
        day_name = result.get("day", "Today")
        raw_classes = list(result.get("classes", result.get("entries", [])))
        attendance = result.get("attendance", {})
        target = student_context.profile.attendance_target or 75.0

        # Normalise student batch
        student_batch = _normalize_batch_str(student_context.profile.lab_batch)

        # 1. Resolve batch & filter
        raw_dicts = [
            e.to_dict() if hasattr(e, "to_dict") else dict(e) for e in raw_classes
        ]
        resolved, has_ambiguity = resolve_batch_and_filter(raw_dicts, student_batch)

        # 2. Structurally merge contiguous entries
        merged = merge_contiguous_entries(resolved)

        lines: list[str] = [
            "<b>Good morning.</b>",
            "",
            f"Here is your daily briefing for <b>{day_name}</b> ({date_str}):",
            "",
        ]

        # Schedule section
        if merged:
            session_str = "session" if len(merged) == 1 else "sessions"
            lines.append(f"<b>Today's Schedule ({len(merged)} {session_str}):</b>")
            for idx, entry in enumerate(merged, 1):
                act = entry.get("activity_name", "Class")
                batch = f", {entry['batch_label']}" if entry.get("batch_label") else ""
                act_type = entry.get("activity_type", "lecture").title()
                start = entry.get("start_time", "")
                end = entry.get("end_time", "")
                room = entry.get("room")
                room_tag = f" [Room: <code>{room}</code>]" if room else ""

                time_str = format_time_span(start, end)
                lines.append(
                    f"{idx}. <b>{act}</b> ({act_type}{batch}) — "
                    f"{time_str}{room_tag}"
                )
            lines.append("")
        else:
            lines.append(
                "<b>Today's Schedule:</b>\n"
                "No classes scheduled today.\n"
            )

        # Attendance section
        if attendance:
            pct = float(
                attendance.get(
                    "percentage", attendance.get("cumulative_percentage", 0.0)
                )
            )
            diff = pct - target
            icon = CHECK_MARK if diff >= 0 else WARNING_SIGN
            status_text = "Above target" if diff >= 0 else "Below target"
            lines.append("<b>Attendance Status:</b>")
            lines.append(
                f"• Overall: {format_percentage(pct)} — {icon} {status_text}"
            )
            lines.append("")

        if has_ambiguity:
            ambig_msg = (
                "Note: Lab batch is not yet set. Reply with <b>Batch 1</b> or "
                "<b>Batch 2</b> to resolve your lab allocation."
            )
            lines.append(ambig_msg)
            lines.append("")

        lines.append("Have a productive day.")
        return "\n".join(lines).strip()
