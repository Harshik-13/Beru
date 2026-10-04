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
        if tool_name == "set_attendance_target":
            return self.render_set_target(result, student_context)
        elif tool_name == "calculate_bunk_allowance":
            return self.render_bunk_allowance(result, student_context)
        elif tool_name == "simulate_day_absence":
            return self.render_day_absence(result, student_context)
        elif tool_name == "get_attendance_extremes":
            return self.render_extremes(result, student_context)
        elif tool_name == "get_attendance_summary":
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
        elif tool_name == "simulate_schedule_scenario":
            return self.render_schedule_scenario(result, student_context)
        elif tool_name == "simulate_subject_periods":
            return self.render_subject_periods(result, student_context)
        elif tool_name == "sync_attendance":
            return self.render_sync_result(result, student_context)

        return self.render_generic_attendance(result, student_context)

    def render_set_target(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render target update card with verified post-mutation metrics."""
        if not result.get("success"):
            err = result.get("error", "Unable to update target.")
            return f"<b>Target Update:</b>\n\n⚠️ <b>Update failed:</b> {err}"

        mutation = result.get("mutation", {})
        old_target = mutation.get("old_target", 75.0)
        new_target = mutation.get("new_target", 75.0)
        is_idempotent = mutation.get("idempotent", False)

        attendance = result.get("attendance", {})
        pct = float(attendance.get("current_percentage", 0.0))
        att = attendance.get("attended", 0)
        cond = attendance.get("conducted", 0)

        target_info = result.get("target", {})
        diff = target_info.get("difference", 0.0)
        status = target_info.get("status", "at_target")
        gap = target_info.get("gap_percentage", 0.0)
        recovery = target_info.get("recovery_classes_needed", 0)
        safe_bunks = target_info.get("safe_bunks", 0)

        if is_idempotent:
            note_line = f"• Attendance target is already set to <b>{format_percentage(new_target)}</b>."
        else:
            note_line = (
                f"• Target updated from <b>{format_percentage(old_target)}</b> "
                f"to <b>{format_percentage(new_target)}</b>."
            )

        if status == "below":
            status_line = (
                f"• <b>Status:</b> {WARNING_SIGN} {gap:.1f}% more needed to reach {new_target:.0f}%"
            )
            rec_line = (
                f"• <b>Recovery:</b> <code>{recovery}</code> consecutive classes needed"
                if recovery > 0
                else ""
            )
        elif status == "at_target":
            status_line = f"• <b>Status:</b> {CHECK_MARK} Exactly at {new_target:.0f}% target"
            rec_line = ""
        else:
            status_line = f"• <b>Status:</b> {CHECK_MARK} {diff:.1f}% above {new_target:.0f}% target"
            rec_line = (
                f"• <b>Safe Bunks:</b> Up to <code>{safe_bunks}</code> classes can be missed without dropping below target"
                if safe_bunks > 0
                else ""
            )

        lines = [
            "<b>Attendance Target Updated:</b>",
            "",
            f"{CHECK_MARK} {note_line}",
            f"• <b>Current Overall:</b> {format_percentage(pct)} ({att}/{cond} attended)",
            status_line,
        ]
        if rec_line:
            lines.append(rec_line)

        return "\n".join(lines).strip()

    def render_bunk_allowance(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render safe bunk allowance."""
        if not result.get("available"):
            msg = result.get("message") or result.get("error") or "Attendance data unavailable."
            return f"<b>Safe Bunk Allowance:</b>\n\n⚠️ {msg}"

        target = float(result.get("target_percentage", 75.0))
        is_overall = result.get("is_overall", False)

        if is_overall:
            safe_bunks = result.get("safe_bunks", 0)
            curr_pct = float(result.get("current_percentage", 0.0))
            proj_pct = float(result.get("projected_percentage_after_bunk", curr_pct))
            status = result.get("status")

            lines = ["<b>Safe Bunk Allowance (Overall):</b>", ""]
            if status == "below_target":
                lines.append(
                    f"• <b>Current Overall:</b> {format_percentage(curr_pct)} "
                    f"(Target: {format_percentage(target)})"
                )
                lines.append(f"• <b>Safe Bunks:</b> <code>0</code> classes")
                lines.append(
                    f"• <b>Status:</b> {WARNING_SIGN} Your attendance is currently below your target. "
                    "Attending upcoming classes is required to recover."
                )
            elif status == "no_classes_conducted":
                lines.append("• <b>Safe Bunks:</b> <code>0</code> (no classes conducted yet)")
            else:
                bunk_word = "classes" if safe_bunks != 1 else "class"
                lines.append(
                    f"• <b>Safe Bunks:</b> Up to <code>{safe_bunks}</code> {bunk_word} "
                    f"can be missed overall without dropping below {target:.0f}%"
                )
                lines.append(
                    f"• <b>Current Overall:</b> {format_percentage(curr_pct)} → "
                    f"<b>Projected:</b> {format_percentage(proj_pct)}"
                )

            # Per-subject breakdown
            subs = result.get("subjects", [])
            if subs:
                lines.append("")
                lines.append("<b>Subject Breakdown:</b>")
                for s in subs:
                    s_name = s.get("subject_name") or s.get("subject_code")
                    s_bunk = s.get("safe_bunks", 0)
                    s_pct = float(s.get("current_percentage", 0.0))
                    if s_bunk > 0:
                        b_badge = f"{CHECK_MARK} <code>{s_bunk}</code> safe to miss"
                    elif s_pct >= target:
                        b_badge = f"{CHECK_MARK} At target (0 safe)"
                    else:
                        b_badge = f"{WARNING_SIGN} Below target (0 safe)"
                    lines.append(f"• <b>{s_name}:</b> {format_percentage(s_pct)} — {b_badge}")

            lines.append("")
            lines.append(
                "<i>ℹ️ Note: Bunk allowance represents total future classes you can miss under current totals.</i>"
            )
            return "\n".join(lines).strip()

        # Specific subject
        sub_name = result.get("subject_name") or result.get("subject_code", "Subject")
        safe_bunks = result.get("safe_bunks", 0)
        curr_pct = float(result.get("current_percentage", 0.0))
        proj_pct = float(result.get("projected_percentage_after_bunk", curr_pct))
        status = result.get("status")

        lines = [f"<b>Safe Bunk Allowance: {sub_name}:</b>", ""]
        if status == "below_target":
            lines.append(
                f"• <b>Current Attendance:</b> {format_percentage(curr_pct)} "
                f"(Target: {format_percentage(target)})"
            )
            lines.append("• <b>Safe Bunks:</b> <code>0</code> classes")
            lines.append(
                f"• <b>Status:</b> {WARNING_SIGN} Attendance is below target. "
                "You cannot afford to skip any classes in this subject."
            )
        elif status == "no_classes_conducted":
            lines.append("• <b>Safe Bunks:</b> <code>0</code> (no classes conducted yet)")
        else:
            bunk_word = "classes" if safe_bunks != 1 else "class"
            lines.append(
                f"• <b>Safe Bunk Allowance:</b> <code>{safe_bunks}</code> {bunk_word}"
            )
            lines.append(
                f"• <b>Current Attendance:</b> {format_percentage(curr_pct)} → "
                f"<b>Projected:</b> {format_percentage(proj_pct)}"
            )
            lines.append(
                f"• <b>Status:</b> {CHECK_MARK} Safe to miss up to {safe_bunks} {bunk_word} "
                f"while maintaining ≥ {target:.0f}%"
            )

        lines.append("")
        lines.append(
            "<i>ℹ️ Note: This is your total future bunk allowance under current assumptions, "
            "not classes you can skip on a single day.</i>"
        )
        return "\n".join(lines).strip()

    def render_day_absence(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render day-leave simulation prediction."""
        if not result.get("available"):
            msg = result.get("message") or result.get("error") or "Simulation unavailable."
            return f"<b>Day-Leave Simulation:</b>\n\n⚠️ {msg}"

        day_name = result.get("day_name", "Day")
        total_periods = result.get("scheduled_classes_count", 0)
        target = float(result.get("target_percentage", 75.0))

        if total_periods == 0:
            return f"<b>Day-Leave Simulation: {day_name}:</b>\n\n{CHECK_MARK} {result.get('message')}"

        curr_overall = float(result.get("current_overall_percentage", 0.0))
        proj_overall = float(result.get("projected_overall_percentage", 0.0))
        is_safe = result.get("is_safe", False)
        overall_safe = result.get("overall_safe", False)
        subjects_safe = result.get("subjects_safe", False)

        if is_safe:
            feasibility_text = (
                f"{CHECK_MARK} <b>Safe:</b> Both overall attendance and individual subjects "
                f"remain at or above your {target:.0f}% target."
            )
        elif overall_safe and not subjects_safe:
            feasibility_text = (
                f"{WARNING_SIGN} <b>Caution:</b> Overall attendance stays above {target:.0f}%, "
                f"but one or more scheduled subjects will drop below target."
            )
        else:
            feasibility_text = (
                f"{WARNING_SIGN} <b>Unsafe:</b> Missing scheduled classes will drop overall "
                f"attendance below your {target:.0f}% target."
            )

        lines = [
            f"<b>Day-Leave Simulation: {day_name}:</b>",
            "",
            f"• <b>Scheduled Periods:</b> <code>{total_periods}</code>",
            (
                f"• <b>Overall Attendance Impact:</b> {format_percentage(curr_overall)} → "
                f"<b>{format_percentage(proj_overall)}</b> "
                f"({proj_overall - curr_overall:+.1f}%)"
            ),
            f"• <b>Leave Feasibility:</b> {feasibility_text}",
            "",
            "<b>Scheduled Subjects Impact:</b>",
        ]

        for s in result.get("affected_subjects", []):
            name = s.get("subject_name") or s.get("subject_code")
            periods = s.get("scheduled_periods", 1)
            p_word = "period" if periods == 1 else "periods"
            c_pct = s.get("current_percentage")
            p_pct = s.get("projected_percentage")
            safe = s.get("is_safe", True)

            if c_pct is not None and p_pct is not None:
                badge = f"{CHECK_MARK} Safe" if safe else f"{WARNING_SIGN} Drops below {target:.0f}%"
                lines.append(
                    f"• <b>{name}</b> (<code>{periods}</code> {p_word}): "
                    f"{format_percentage(c_pct)} → {format_percentage(p_pct)} — {badge}"
                )
            else:
                lines.append(f"• <b>{name}</b> (<code>{periods}</code> {p_word})")

        lines.append("")
        lines.append(
            "<i>📅 Based on your confirmed timetable and verified attendance records.</i>"
        )
        return "\n".join(lines).strip()

    def render_schedule_scenario(
        self, result: dict[str, Any], student_context: StudentContext | None = None
    ) -> str:
        """Render multi-day or mixed schedule simulation results."""
        if not result.get("available"):
            msg = result.get("message") or result.get("error") or "Simulation unavailable."
            return f"<b>Schedule Simulation:</b>\n\n⚠️ {msg}"

        dates = result.get("scenario_dates", [])
        total_periods = result.get("total_scheduled_periods", 0)
        target = float(result.get("target_percentage", 75.0))
        curr_pct = float(result.get("current_percentage", 0.0))
        proj_pct = float(result.get("projected_percentage", 0.0))
        change = float(result.get("percentage_change", 0.0))
        is_safe = result.get("is_safe", False)
        overall_safe = result.get("overall_safe", False)
        subjects_safe = result.get("subjects_safe", False)
        critical_breaches = result.get("critical_breaches", [])
        snapshot_age = result.get("snapshot_age_hours")

        lines = ["<b>Schedule Simulation:</b>", ""]
        if snapshot_age is not None:
            lines.append(f"<i>ℹ️ Based on attendance snapshot from {snapshot_age}h ago (offline simulation)</i>")
            lines.append("")

        if dates:
            lines.append("<b>Simulated Dates:</b>")
            for d_desc in dates:
                lines.append(f"• {d_desc}")
            lines.append("")

        lines.append(f"• <b>Total Periods:</b> <code>{total_periods}</code>")
        lines.append(
            f"• <b>Overall Attendance:</b> {format_percentage(curr_pct)} → "
            f"<b>{format_percentage(proj_pct)}</b> ({change:+.1f}%)"
        )
        lines.append(f"• <b>Target:</b> {format_percentage(target)}")

        # Safety verdict
        if is_safe:
            status_text = (
                f"{CHECK_MARK} <b>Safe:</b> Both overall attendance and individual subjects "
                f"remain at or above {target:.0f}%."
            )
        elif overall_safe and not subjects_safe:
            status_text = (
                f"{WARNING_SIGN} <b>Caution:</b> Overall attendance stays above {target:.0f}%, "
                f"but {len(critical_breaches)} subject(s) drop below target: {', '.join(critical_breaches)}."
            )
        else:
            breach_info = f" ({', '.join(critical_breaches)})" if critical_breaches else ""
            status_text = (
                f"{WARNING_SIGN} <b>High Risk:</b> Projected attendance drops below your "
                f"{target:.0f}% target{breach_info}."
            )

        lines.append(f"• <b>Feasibility:</b> {status_text}")

        # Per-subject breakdown
        breakdown = result.get("subject_breakdown", [])
        if breakdown:
            lines.append("")
            lines.append("<b>Subject Breakdown:</b>")
            for s in breakdown:
                s_name = s.get("subject_name") or s.get("subject_code")
                s_curr = float(s.get("current_percentage", 0.0))
                s_proj = float(s.get("projected_percentage", 0.0))
                s_safe = s.get("is_safe", True)
                d_att = s.get("delta_attended", 0)
                d_cond = s.get("delta_conducted", 0)
                badge = CHECK_MARK if s_safe else WARNING_SIGN
                period_note = f"+{d_att}/+{d_cond} periods" if d_att > 0 else f"{d_cond} periods missed"
                lines.append(
                    f"• <b>{s_name}:</b> {format_percentage(s_curr)} → <b>{format_percentage(s_proj)}</b> "
                    f"({period_note}) {badge}"
                )

        return "\n".join(lines).strip()

    def render_subject_periods(
        self, result: dict[str, Any], student_context: StudentContext | None = None
    ) -> str:
        """Render subject period simulation results."""
        if not result.get("available"):
            msg = result.get("message") or result.get("error") or "Simulation unavailable."
            return f"<b>Subject Simulation:</b>\n\n⚠️ {msg}"

        sub_code = result.get("subject_code", "Subject")
        sub_name = result.get("subject_name") or sub_code
        missed = result.get("periods_missed", 0)
        attended = result.get("periods_attended", 0)
        target = float(result.get("target_percentage", 75.0))

        s_curr = float(result.get("subject_current_percentage", 0.0))
        s_proj = float(result.get("subject_projected_percentage", 0.0))
        s_safe = result.get("subject_is_safe", True)

        o_curr = float(result.get("overall_current_percentage", 0.0))
        o_proj = float(result.get("overall_projected_percentage", 0.0))
        o_change = float(result.get("overall_percentage_change", 0.0))
        o_safe = result.get("overall_is_safe", True)
        snapshot_age = result.get("snapshot_age_hours")

        lines = [f"<b>Subject Simulation: {sub_name}:</b>", ""]
        if snapshot_age is not None:
            lines.append(f"<i>ℹ️ Based on attendance snapshot from {snapshot_age}h ago (offline simulation)</i>")
            lines.append("")

        if attended > 0 and missed > 0:
            lines.append(f"• <b>Simulation:</b> Attending {attended} & missing {missed} periods")
        elif missed > 0:
            lines.append(f"• <b>Simulation:</b> Missing <code>{missed}</code> periods")
        else:
            lines.append(f"• <b>Simulation:</b> Attending <code>{attended}</code> periods")

        lines.append(
            f"• <b>{sub_code} Attendance:</b> {format_percentage(s_curr)} → <b>{format_percentage(s_proj)}</b> "
            f"({CHECK_MARK if s_safe else WARNING_SIGN})"
        )
        lines.append(
            f"• <b>Overall Attendance:</b> {format_percentage(o_curr)} → <b>{format_percentage(o_proj)}</b> "
            f"({o_change:+.1f}%) ({CHECK_MARK if o_safe else WARNING_SIGN})"
        )
        lines.append(f"• <b>Target:</b> {format_percentage(target)}")

        return "\n".join(lines).strip()

    def render_extremes(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render lowest and highest attendance courses with multi-subject tie handling."""
        if not result.get("available"):
            msg = result.get("message") or "Attendance data unavailable."
            return f"<b>Attendance Extremes:</b>\n\n⚠️ {msg}"

        target = float(result.get("target_percentage", 75.0))
        lowest = result.get("lowest", [])
        highest = result.get("highest", [])
        below = result.get("below_target", [])
        total = result.get("total_subjects", 0)

        lines = ["<b>Attendance Extremes:</b>", ""]

        lines.append("• <b>Lowest Attendance:</b>")
        for s in lowest:
            name = s.get("subject_name") or s.get("subject_code")
            pct = float(s.get("percentage", 0.0))
            att = s.get("attended", 0)
            cond = s.get("conducted", 0)
            icon = CHECK_MARK if pct >= target else WARNING_SIGN
            lines.append(f"  {icon} <b>{name}:</b> {format_percentage(pct)} ({att}/{cond})")

        lines.append("")
        lines.append("• <b>Highest Attendance:</b>")
        for s in highest:
            name = s.get("subject_name") or s.get("subject_code")
            pct = float(s.get("percentage", 0.0))
            att = s.get("attended", 0)
            cond = s.get("conducted", 0)
            icon = CHECK_MARK if pct >= target else WARNING_SIGN
            lines.append(f"  {icon} <b>{name}:</b> {format_percentage(pct)} ({att}/{cond})")

        lines.append("")
        below_count = len(below)
        if below_count > 0:
            lines.append(
                f"• <b>Subjects Below Target ({target:.0f}%):</b> "
                f"<code>{below_count}</code> of <code>{total}</code> subjects need attention."
            )
        else:
            lines.append(
                f"• <b>All Subjects Safe:</b> {CHECK_MARK} All <code>{total}</code> subjects meet or exceed {target:.0f}%."
            )

        return "\n".join(lines).strip()

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
        target = float(
            overall.get("target_percentage")
            or student_context.profile.attendance_target
            or 75.0
        )

        cum_pct = float(overall.get("cumulative_percentage", 0.0))
        attended = overall.get("cumulative_attended", 0)
        conducted = overall.get("cumulative_conducted", 0)

        target_status = overall.get("target_status")
        target_diff = overall.get("target_difference")
        target_gap = overall.get("target_gap_percentage")

        if target_status is None or target_diff is None or target_gap is None:
            diff = round(cum_pct - target, 2)
            gap = round(abs(diff), 2)
            if diff < -0.05:
                target_status = "below"
            elif diff > 0.05:
                target_status = "above"
            else:
                target_status = "at_target"
            target_diff = diff
            target_gap = gap

        if target_status == "below":
            status_text = f"{WARNING_SIGN} {target_gap:.1f}% more needed to reach {target:.0f}%"
        elif target_status == "at_target":
            status_text = f"{CHECK_MARK} At {target:.0f}% target"
        else:
            status_text = f"{CHECK_MARK} {target_diff:.1f}% above {target:.0f}% target"

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
                name = sub.get("subject_name")
                code = sub.get("subject_code")
                if name and code and name != code:
                    display_label = f"{name} ({code})"
                elif name:
                    display_label = name
                elif code:
                    display_label = code
                else:
                    display_label = "Course"
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
                    f"{idx}. <b>{display_label}:</b> {pct_str} ({s_att}/{s_cond}) — {badge}"
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
        target = float(
            result.get("target_percentage")
            or student_context.profile.attendance_target
            or 75.0
        )

        target_status = result.get("target_status")
        target_diff = result.get("target_difference")
        target_gap = result.get("target_gap_percentage")

        if target_status is None or target_diff is None or target_gap is None:
            diff = round(cum_pct - target, 2)
            gap = round(abs(diff), 2)
            if diff < -0.05:
                target_status = "below"
            elif diff > 0.05:
                target_status = "above"
            else:
                target_status = "at_target"
            target_diff = diff
            target_gap = gap

        if target_status == "below":
            status_text = f"{WARNING_SIGN} {target_gap:.1f}% more needed to reach {target:.0f}%"
        elif target_status == "at_target":
            status_text = f"{CHECK_MARK} At {target:.0f}% target"
        else:
            status_text = f"{CHECK_MARK} {target_diff:.1f}% above {target:.0f}% target"

        lines: list[str] = [
            "<b>Overall Attendance:</b>",
            "",
            (
                f"• <b>Overall:</b> {format_percentage(cum_pct)} "
                f"({attended}/{conducted} attended)"
            ),
            f"• <b>Target:</b> {format_percentage(target)}",
            f"• <b>Status:</b> {status_text}",
        ]

        # Add current month attendance if available
        monthly_att = result.get("monthly_attended")
        monthly_cond = result.get("monthly_conducted")
        monthly_pct = result.get("monthly_percentage")
        monthly_period = result.get("monthly_period")
        if monthly_att is not None and monthly_cond is not None and monthly_cond > 0:
            pct_val = (
                monthly_pct
                if monthly_pct is not None
                else round((monthly_att / monthly_cond) * 100.0, 2)
            )
            period_label = (
                f" ({monthly_period})" if monthly_period else " (This Month)"
            )
            lines.append(
                f"• <b>Monthly{period_label}:</b> {format_percentage(pct_val)} "
                f"({monthly_att}/{monthly_cond} attended)"
            )

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

        target = float(
            result.get("target_percentage")
            or student_context.profile.attendance_target
            or 75.0
        )
        for idx, sub in enumerate(subjects, 1):
            name = sub.get("subject_name") or sub.get("subject_code", "Course")
            pct = float(sub.get("cumulative_percentage", 0.0))
            defic = float(sub.get("deficit", 0.0))
            t_pct = float(sub.get("target_percentage") or target)
            lines.append(
                f"{idx}. <b>{name}:</b> {format_percentage(pct)} — "
                f"{WARNING_SIGN} {defic:.1f}% more needed to reach {t_pct:.0f}%"
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
        if isinstance(result, dict) and "message" in result:
            msg = str(result["message"])
        else:
            msg = "Attendance details processed successfully."
        return f"<b>Attendance Update:</b>\n\n{msg}"
