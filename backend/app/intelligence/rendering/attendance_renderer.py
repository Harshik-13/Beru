"""Deterministic Attendance Renderer.

Renders attendance queries, summaries, deficits, and simulations into clean,
ChatGPT-style Telegram HTML responses.
Enforces:
- Consistent status indicators (CHECK_MARK for met, WARNING_SIGN for deficit)
- Bold labels and code badges for percentages and counts
- Respectful 'Sir' honorific and zero decorative emojis
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from app.intelligence.rendering.style_contract import (
    CHECK_MARK,
    HONORIFIC,
    WARNING_SIGN,
    format_percentage,
)

if TYPE_CHECKING:
    from app.intelligence.models.context import StudentContext


class AttendanceRenderer:
    """Renderer for attendance tool execution results."""

    def render(
        self,
        tool_name: str,
        result: dict[str, Any],
        student_context: StudentContext,
        user_message: str = "",
    ) -> str:
        """Main dispatch point for attendance tools."""
        if tool_name == "get_attendance_summary":
            return self.render_summary(result, student_context)
        elif tool_name == "get_overall_attendance":
            return self.render_overall(result, student_context)
        elif tool_name == "get_subject_attendance":
            return self.render_subject(result, student_context)
        elif tool_name == "simulate_absence":
            return self.render_simulation(result, student_context)
        elif tool_name == "get_subjects_below_target":
            return self.render_below_target(result, student_context)
        elif tool_name == "calculate_classes_needed":
            return self.render_recovery(result, student_context)
        elif tool_name == "sync_attendance":
            return self.render_sync_result(result, student_context)

        return self.render_generic_attendance(result, student_context)

    def _format_provenance_badge(self, result: dict[str, Any]) -> str:
        """Format provenance timestamp and freshness note."""
        provenance = result.get("provenance")
        captured_at_str = result.get("captured_at")
        notice = result.get("notice")

        lines: list[str] = []
        if notice:
            lines.append(f"<i>⚠️ {notice}</i>")

        if provenance == "portal_live_sync":
            lines.append("<i>📅 Synced live from Doctus just now</i>")
        elif provenance == "portal_snapshot_stale":
            if captured_at_str:
                formatted = self._format_timestamp(captured_at_str)
                lines.append(f"<i>⚠️ Cached snapshot from {formatted} (Live refresh unavailable)</i>")
            else:
                lines.append("<i>⚠️ Live refresh unavailable</i>")
        elif captured_at_str:
            formatted = self._format_timestamp(captured_at_str)
            lines.append(f"<i>📅 Sourced from Doctus snapshot ({formatted})</i>")

        return "\n".join(lines).strip()

    def _format_timestamp(self, ts_str: str) -> str:
        """Convert ISO timestamp string into readable representation."""
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            return dt.strftime("%d %b, %I:%M %p")
        except Exception:
            return ts_str

    def render_sync_result(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render result of manual or automated sync_attendance tool."""
        if not result.get("success"):
            error_msg = result.get("error") or result.get("message") or "Sync failed"
            return (
                f"<b>Attendance Sync:</b>\n\n"
                f"⚠️ <b>Unable to sync attendance:</b> {error_msg}\n"
                f"<i>If your credentials changed, use /connect_portal to reconnect.</i>"
            )

        pct = result.get("overall_percentage")
        pct_str = format_percentage(pct) if pct is not None else "N/A"
        subjects_count = result.get("subject_count", 0)

        lines = [
            "<b>Attendance Sync:</b>",
            "",
            f"{CHECK_MARK} <b>Successfully synced from Doctus!</b>",
            f"• <b>Overall Attendance:</b> {pct_str}",
            f"• <b>Subjects Updated:</b> <code>{subjects_count}</code>",
            "",
            "<i>📅 Synced live from Doctus just now</i>",
        ]
        return "\n".join(lines).strip()

    def render_summary(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render complete attendance summary."""
        overall = result.get("overall", {})
        subjects = result.get("subjects", [])
        target = student_context.profile.attendance_target or 75.0

        cum_pct = float(overall.get("cumulative_percentage", 0.0))
        attended = overall.get("cumulative_attended", 0)
        conducted = overall.get("cumulative_conducted", 0)

        diff = cum_pct - target
        if diff >= 0:
            status_text = f"{CHECK_MARK} Above target (+{diff:.1f}% margin)"
        else:
            status_text = f"{WARNING_SIGN} Below target ({diff:.1f}% deficit)"

        lines: list[str] = [
            "<b>Attendance Summary:</b>",
            "",
            (
                f"• <b>Overall:</b> {format_percentage(cum_pct)} "
                f"({attended}/{conducted} classes attended)"
            ),
            f"• <b>Target:</b> {format_percentage(target)}",
            f"• <b>Status:</b> {status_text}",
            "",
        ]

        if subjects:
            lines.append("<b>Subject Breakdown:</b>")
            for idx, sub in enumerate(subjects, 1):
                name = sub.get("subject_name") or sub.get("subject_code", "Course")
                s_pct = float(sub.get("cumulative_percentage", 0.0))
                s_att = sub.get("cumulative_attended", 0)
                s_cond = sub.get("cumulative_conducted", 0)

                if s_pct >= target:
                    badge = f"{CHECK_MARK} Met"
                else:
                    needed = sub.get("classes_needed")
                    if needed:
                        classes_word = "classes" if needed > 1 else "class"
                        badge = (
                            f"{WARNING_SIGN} {needed} {classes_word} "
                            f"needed to reach {target:.0f}%"
                        )
                    else:
                        badge = f"{WARNING_SIGN} Needs attention"

                pct_str = format_percentage(s_pct)
                lines.append(
                    f"{idx}. <b>{name}:</b> {pct_str} ({s_att}/{s_cond}) \u2014 {badge}"
                )

        badge_footer = self._format_provenance_badge(result)
        if badge_footer:
            lines.append("")
            lines.append(badge_footer)

        return "\n".join(lines).strip()

    def render_overall(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render overall attendance status card."""
        cum_pct = float(result.get("cumulative_percentage", 0.0))
        attended = result.get("cumulative_attended", 0)
        conducted = result.get("cumulative_conducted", 0)
        target = student_context.profile.attendance_target or 75.0

        diff = cum_pct - target
        status_icon = CHECK_MARK if diff >= 0 else WARNING_SIGN

        lines: list[str] = [
            "<b>Overall Attendance:</b>",
            "",
            (
                f"• <b>Current:</b> {format_percentage(cum_pct)} "
                f"({attended}/{conducted} attended)"
            ),
            f"• <b>Target:</b> {format_percentage(target)}",
            f"• <b>Margin:</b> {status_icon} {diff:+.1f}%",
        ]

        badge_footer = self._format_provenance_badge(result)
        if badge_footer:
            lines.append("")
            lines.append(badge_footer)

        return "\n".join(lines).strip()

    def render_subject(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render attendance for an individual subject."""
        code = result.get("subject_code", "")
        name = result.get("subject_name") or code
        cum_pct = float(result.get("cumulative_percentage", 0.0))
        attended = result.get("cumulative_attended", 0)
        conducted = result.get("cumulative_conducted", 0)
        target = student_context.profile.attendance_target or 75.0

        status_icon = CHECK_MARK if cum_pct >= target else WARNING_SIGN
        status_label = "Meeting target" if cum_pct >= target else "Below target"

        lines: list[str] = [
            f"<b>Subject Attendance: {name}:</b>",
            "",
            f"• <b>Code:</b> <code>{code}</code>",
            (
                f"• <b>Attendance:</b> {format_percentage(cum_pct)} "
                f"({attended}/{conducted})"
            ),
            f"• <b>Status:</b> {status_icon} {status_label}",
        ]

        badge_footer = self._format_provenance_badge(result)
        if badge_footer:
            lines.append("")
            lines.append(badge_footer)

        return "\n".join(lines).strip()

    def render_simulation(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render absence simulation projection."""
        curr_pct = float(result.get("current_percentage", 0.0))
        proj_pct = float(result.get("projected_percentage", 0.0))
        missed = result.get("missed_classes", 1)
        target = student_context.profile.attendance_target or 75.0

        alert = WARNING_SIGN if proj_pct < target else CHECK_MARK
        safety_text = (
            "Safe" if proj_pct >= target else "Falls below required target"
        )

        lines: list[str] = [
            "<b>Absence Simulation Projection:</b>",
            "",
            f"• <b>Classes Skipped:</b> <code>{missed}</code>",
            f"• <b>Current Attendance:</b> {format_percentage(curr_pct)}",
            (
                f"• <b>Projected Attendance:</b> {format_percentage(proj_pct)} "
                f"({proj_pct - curr_pct:+.1f}%)"
            ),
            f"• <b>Target Safety:</b> {alert} {safety_text}",
        ]
        return "\n".join(lines).strip()

    def render_below_target(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render list of subjects falling below target."""
        subjects = result.get("subjects_below_target", [])
        lines: list[str] = ["<b>Subjects Below Target:</b>", ""]

        if not subjects:
            msg = f"{CHECK_MARK} All subjects currently meet or exceed your target."
            lines.append(msg)
            return "\n".join(lines).strip()

        for idx, sub in enumerate(subjects, 1):
            name = sub.get("subject_name") or sub.get("subject_code", "Course")
            pct = float(sub.get("cumulative_percentage", 0.0))
            defic = float(sub.get("deficit", 0.0))
            lines.append(
                f"{idx}. <b>{name}:</b> {format_percentage(pct)} — "
                f"{WARNING_SIGN} {defic:.1f}% deficit"
            )

        badge_footer = self._format_provenance_badge(result)
        if badge_footer:
            lines.append("")
            lines.append(badge_footer)

        return "\n".join(lines).strip()

    def render_recovery(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render recovery classes required."""
        needed = result.get("classes_needed", 0)
        proj_pct = float(result.get("projected_percentage", 0.0))
        achieved = result.get("target_achieved", True)
        feasibility = "Achievable" if achieved else "Exceeds remaining schedule"

        lines: list[str] = [
            "<b>Attendance Recovery Plan:</b>",
            "",
            f"• <b>Consecutive Classes Needed:</b> <code>{needed}</code>",
            f"• <b>Projected Outcome:</b> {format_percentage(proj_pct)}",
            f"• <b>Feasibility:</b> {feasibility}",
        ]

        badge_footer = self._format_provenance_badge(result)
        if badge_footer:
            lines.append("")
            lines.append(badge_footer)

        return "\n".join(lines).strip()

    def render_generic_attendance(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Fallback for generic attendance tool results."""
        msg = result.get("message", str(result))
        return f"<b>Attendance Update:</b>\n\n{msg}"
