"""Deterministic Schedule Renderer.

Renders timetable tool results into clean, ChatGPT-style Telegram HTML responses.
Enforces:
- Structural period merging from contiguous entry topology
- Dynamic batch resolution based on authenticated student's lab_batch
- Faithful ambiguity preservation when batch is unknown
- Bold labels, code badges, and 'Sir' honorific
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.intelligence.rendering.style_contract import (
    HONORIFIC,
    format_label_value,
    format_time_span,
)

if TYPE_CHECKING:
    from app.intelligence.models.context import StudentContext


def _normalize_batch_str(batch: str | None) -> str | None:
    """Normalize batch representation to 'Batch 1' | 'Batch 2' | None."""
    if not batch:
        return None
    b = str(batch).lower().strip().replace("_", " ")
    if "1" in b:
        return "Batch 1"
    if "2" in b:
        return "Batch 2"
    return None


def merge_contiguous_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Merge consecutive periods that belong to the same block based on entry topology.

    Two entries E1 and E2 are merged into [E1.start_time, E2.end_time] if and only if:
    1. E1.day_of_week == E2.day_of_week (or both None)
    2. E1.end_time == E2.start_time
    3. E1.activity_name == E2.activity_name
    4. E1.lab_batch == E2.lab_batch
    5. E1.room == E2.room (or both None)
    """
    if not entries or len(entries) <= 1:
        return list(entries)

    def sort_key(e: dict[str, Any]) -> tuple[int, str]:
        day = e.get("day_of_week")
        day_int = int(day) if day is not None else 0
        return (day_int, str(e.get("start_time", "")))

    sorted_entries = sorted(entries, key=sort_key)
    merged: list[dict[str, Any]] = []

    for entry in sorted_entries:
        if not merged:
            merged.append(dict(entry))
            continue

        prev = merged[-1]
        same_day = prev.get("day_of_week") == entry.get("day_of_week")
        contiguous = prev.get("end_time") == entry.get("start_time")
        same_activity = prev.get("activity_name") == entry.get("activity_name")
        same_batch = prev.get("lab_batch") == entry.get("lab_batch")
        same_room = prev.get("room") == entry.get("room")

        if same_day and contiguous and same_activity and same_batch and same_room:
            # Merge into prev by extending end_time
            prev["end_time"] = entry.get("end_time")
            # If entry has richer data, retain it
            if not prev.get("faculty") and entry.get("faculty"):
                prev["faculty"] = entry["faculty"]
            if not prev.get("room") and entry.get("room"):
                prev["room"] = entry["room"]
        else:
            merged.append(dict(entry))

    return merged


def resolve_batch_and_filter(
    entries: list[dict[str, Any]], student_batch_norm: str | None
) -> tuple[list[dict[str, Any]], bool]:
    """
    Resolve slash labs and filter entries according to student's lab_batch.

    Returns:
        (resolved_entries, has_unresolved_ambiguity)
    """
    resolved: list[dict[str, Any]] = []
    has_unresolved_ambiguity = False

    for e in entries:
        item = dict(e)
        activity = item.get("activity_name", "")
        item_batch = _normalize_batch_str(item.get("lab_batch"))

        # Check if this entry is for another batch
        if student_batch_norm and item_batch and item_batch != student_batch_norm:
            # Skip entries meant specifically for other batch
            continue

        # Check for slash-separated activity (e.g. 'CF LAB / CN LAB')
        if "/" in activity:
            parts = [p.strip() for p in activity.split("/")]
            if len(parts) == 2:
                if student_batch_norm == "Batch 1":
                    item["activity_name"] = parts[0]
                    item["batch_label"] = "Batch 1"
                elif student_batch_norm == "Batch 2":
                    item["activity_name"] = parts[1]
                    item["batch_label"] = "Batch 2"
                else:
                    # Unknown batch: preserve slash ambiguity explicitly
                    item["activity_name"] = activity
                    item["batch_label"] = "Batch 1 / Batch 2"
                    has_unresolved_ambiguity = True
            else:
                if student_batch_norm:
                    item["batch_label"] = student_batch_norm
                else:
                    has_unresolved_ambiguity = True
        elif item_batch:
            item["batch_label"] = item_batch

        resolved.append(item)

    return resolved, has_unresolved_ambiguity


class ScheduleRenderer:
    """Renderer for all timetable and schedule-related tool results."""

    def render(
        self,
        tool_name: str,
        result: dict[str, Any],
        student_context: StudentContext,
        user_message: str = "",
    ) -> str:
        """Main dispatch entry point for timetable tools."""
        if tool_name in {
            "get_schedule",
            "get_today_schedule",
            "get_tomorrow_schedule",
            "get_schedule_for_weekday",
        }:
            return self.render_day_schedule(result, student_context)
        elif tool_name in {"get_next_class", "get_first_class_tomorrow"}:
            return self.render_next_class(result, student_context, tool_name)
        elif tool_name == "get_week_schedule":
            return self.render_week_schedule(result, student_context)
        elif tool_name == "get_timetable_status":
            return self.render_status(result, student_context)
        elif tool_name == "get_extracted_timetable":
            return self.render_extracted_preview(result, student_context)
        elif tool_name == "set_lab_batch":
            return self.render_batch_set(result, student_context)
        elif tool_name == "confirm_timetable":
            return self.render_confirmation(result, student_context)
        elif tool_name == "get_timetable_metadata":
            return self.render_timetable_metadata(result, student_context)
        elif tool_name == "find_activity_details":
            return self.render_activity_details(result, student_context)
        elif tool_name == "find_faculty_details":
            return self.render_faculty_details(result, student_context)
        elif tool_name == "find_room_details":
            return self.render_room_details(result, student_context)
        elif tool_name == "query_schedule_analytics":
            return self.render_schedule_analytics(result, student_context)

        return self.render_generic_timetable(result, student_context)

    def render_day_schedule(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render a single day's schedule."""
        day = result.get("day", "Requested Day")
        raw_entries = list(result.get("entries", []))

        # Convert tuples or dicts to uniform dicts
        entries_dicts = []
        for e in raw_entries:
            if hasattr(e, "to_dict"):
                entries_dicts.append(e.to_dict())
            elif isinstance(e, dict):
                entries_dicts.append(dict(e))

        student_batch = _normalize_batch_str(student_context.profile.lab_batch)

        # 1. Resolve batch & filter
        resolved_entries, has_ambiguity = resolve_batch_and_filter(
            entries_dicts, student_batch
        )

        # 2. Structurally merge contiguous entries
        merged_entries = merge_contiguous_entries(resolved_entries)

        lines: list[str] = [f"<b>Schedule for {day}:</b>", ""]

        if not merged_entries:
            lines.append("No classes are scheduled for this day.")
            return "\n".join(lines)

        for idx, entry in enumerate(merged_entries, 1):
            act_name = entry.get("activity_name", "Class")
            batch_tag = f" ({entry['batch_label']})" if entry.get("batch_label") else ""
            act_type = entry.get("activity_type", "lecture").title()
            room = entry.get("room")
            faculty = entry.get("faculty")
            start = entry.get("start_time", "")
            end = entry.get("end_time", "")

            lines.append(f"{idx}. <b>{act_name}</b>{batch_tag}")
            lines.append(format_label_value("Time", format_time_span(start, end)))
            lines.append(format_label_value("Type", act_type))
            if room:
                lines.append(format_label_value("Room", f"<code>{room}</code>"))
            if faculty:
                lines.append(format_label_value("Faculty", faculty))
            lines.append("")

        count = len(merged_entries)
        session_str = "session" if count == 1 else "sessions"

        if has_ambiguity:
            footer = (
                f"{count} {session_str} scheduled. Note: Lab batch is not yet set. "
                "Reply with <b>Batch 1</b> or <b>Batch 2</b> to resolve "
                "your lab allocation."
            )
        else:
            footer = (
                f"{count} {session_str} scheduled. Let me know if you need "
                "room details or further assistance."
            )

        lines.append(footer)
        return "\n".join(lines).strip()

    def render_next_class(
        self,
        result: dict[str, Any],
        student_context: StudentContext,
        tool_name: str = "get_next_class",
    ) -> str:
        """Render single card for next upcoming class."""
        has_class = result.get("has_class", False)
        title = (
            "First Class Tomorrow"
            if tool_name == "get_first_class_tomorrow"
            else "Next Upcoming Class"
        )
        lines: list[str] = [f"<b>{title}:</b>", ""]

        if not has_class or not result.get("entry"):
            msg = result.get("message", "No upcoming classes scheduled.")
            lines.append(f"{msg}")
            return "\n".join(lines).strip()

        entry = result["entry"]
        if hasattr(entry, "to_dict"):
            entry = entry.to_dict()

        act_name = entry.get("activity_name", "Class")
        batch = _normalize_batch_str(entry.get("lab_batch"))
        batch_tag = f" ({batch})" if batch else ""
        act_type = entry.get("activity_type", "lecture").title()
        room = entry.get("room")
        faculty = entry.get("faculty")
        day = entry.get("day", "Today")
        start = entry.get("start_time", "")
        end = entry.get("end_time", "")

        lines.append(f"• <b>Subject:</b> <b>{act_name}</b>{batch_tag}")
        lines.append(f"• <b>Time:</b> {format_time_span(start, end)}")
        lines.append(f"• <b>Day:</b> {day}")
        lines.append(f"• <b>Type:</b> {act_type}")
        if room:
            lines.append(f"• <b>Room:</b> <code>{room}</code>")
        if faculty:
            lines.append(f"• <b>Faculty:</b> {faculty}")

        return "\n".join(lines).strip()

    def render_week_schedule(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render the complete week schedule organized by day."""
        days_data = result.get("week") or result.get("days", {})
        lines: list[str] = ["<b>Weekly Schedule Overview:</b>", ""]

        if not days_data:
            lines.append("No schedule data available for this week.")
            return "\n".join(lines).strip()

        student_batch = _normalize_batch_str(student_context.profile.lab_batch)

        for day_name, day_entries in days_data.items():
            raw_list = [
                e.to_dict() if hasattr(e, "to_dict") else dict(e) for e in day_entries
            ]
            resolved, _ = resolve_batch_and_filter(raw_list, student_batch)
            merged = merge_contiguous_entries(resolved)

            lines.append(f"<b>{day_name}</b>")
            if not merged:
                lines.append("   <i>No scheduled classes</i>\n")
                continue

            for e in merged:
                start = e.get("start_time", "")
                end = e.get("end_time", "")
                act = e.get("activity_name", "")
                batch = f" ({e['batch_label']})" if e.get("batch_label") else ""
                lines.append(
                    f"   • {format_time_span(start, end)}: <b>{act}</b>{batch}"
                )
            lines.append("")

        return "\n".join(lines).strip()

    def render_status(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render timetable status card."""
        status = result.get("status", "none").upper()
        ver = result.get("version", 1)
        sec = result.get("section", "N/A")
        sem = result.get("semester", "N/A")
        year = result.get("academic_year", "N/A")

        lines: list[str] = [
            "<b>Timetable Status:</b>",
            "",
            f"• <b>Status:</b> <code>{status}</code>",
            f"• <b>Version:</b> <code>v{ver}</code>",
            f"• <b>Semester / Section:</b> Sem {sem}, Sec {sec}",
            f"• <b>Academic Year:</b> {year}",
        ]
        return "\n".join(lines).strip()

    def render_extracted_preview(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render extracted timetable preview awaiting confirmation."""
        count = result.get("entry_count", 0)
        classroom = result.get("default_classroom", "N/A")
        sec = result.get("section", "N/A")
        branch = result.get("branch", "N/A")

        lines: list[str] = [
            "<b>Extracted Timetable Preview:</b>",
            "",
            f"• <b>Classroom:</b> <code>{classroom}</code>",
            f"• <b>Branch / Section:</b> {branch} (Sec {sec})",
            f"• <b>Total Entries:</b> <code>{count}</code>",
            "",
            (
                "Please review the extracted classes. Reply <b>Confirm</b> to "
                "activate this timetable, or specify any edits required."
            ),
        ]
        return "\n".join(lines).strip()

    def render_batch_set(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render lab batch selection confirmation."""
        batch_val = result.get("lab_batch", "")
        formatted_batch = _normalize_batch_str(batch_val) or batch_val
        lines: list[str] = [
            "<b>Lab Batch Confirmed:</b>",
            "",
            f"Your allocation has been updated to <b>{formatted_batch}</b>.",
            (
                "All slash-separated lab sessions have been resolved "
                "to your batch schedule."
            ),
            (
                "Please reply <b>Confirm</b> when ready to activate "
                "your timetable."
            ),
        ]
        return "\n".join(lines).strip()

    def render_confirmation(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render timetable confirmation activation notice."""
        lines: list[str] = [
            "<b>Timetable Confirmed:</b>",
            "",
            "Your timetable is now officially confirmed and active.",
            (
                "You will receive your daily morning briefing and "
                "proactive class alerts."
            ),
        ]
        return "\n".join(lines).strip()

    def render_timetable_metadata(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render academic profile and timetable metadata."""
        lines: list[str] = ["<b>Academic Profile & Timetable:</b>", ""]

        branch = result.get("branch")
        section = result.get("section")
        semester = result.get("semester")
        year = result.get("year")
        programme = result.get("programme")
        regulation = result.get("regulation")
        classroom = result.get("default_classroom")
        acad_year = result.get("academic_year")

        if branch:
            lines.append(f"• <b>Branch:</b> {branch}")
        if section:
            lines.append(f"• <b>Section:</b> <code>{section}</code>")
        if semester or year:
            sem_str = f"Semester {semester}" if semester else ""
            yr_str = f"Year {year}" if year else ""
            combined = ", ".join(filter(None, [sem_str, yr_str]))
            lines.append(f"• <b>Semester:</b> <code>{combined}</code>")
        if programme:
            lines.append(f"• <b>Programme:</b> {programme}")
        if regulation:
            lines.append(f"• <b>Regulation:</b> <code>{regulation}</code>")
        if classroom:
            lines.append(f"• <b>Default Classroom:</b> <code>{classroom}</code>")
        if acad_year:
            lines.append(f"• <b>Academic Year:</b> {acad_year}")

        return "\n".join(lines).strip()

    def render_activity_details(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render course or lab search results."""
        query = result.get("query", "Activity")
        if not result.get("found", False) or not result.get("matches"):
            return (
                f"<b>Activity Details:</b>\n\n"
                f"No scheduled sessions found for <b>{query}</b>."
            )

        matches = result.get("matches", [])
        lines: list[str] = [f"<b>Activity Details — {query.upper()}:</b>", ""]

        for idx, entry in enumerate(matches, 1):
            act_name = entry.get("activity_name", query)
            batch_tag = f" ({entry['batch_label']})" if entry.get("batch_label") else ""
            day = entry.get("day", "")
            start = entry.get("start_time", "")
            end = entry.get("end_time", "")
            act_type = entry.get("activity_type", "lecture").title()
            room = entry.get("room")
            faculty = entry.get("faculty")

            lines.append(f"{idx}. <b>{act_name}</b>{batch_tag}")
            if day:
                lines.append(format_label_value("Day", day))
            lines.append(format_label_value("Time", format_time_span(start, end)))
            lines.append(format_label_value("Type", act_type))
            if room:
                lines.append(format_label_value("Room", f"<code>{room}</code>"))
            if faculty:
                lines.append(format_label_value("Faculty", faculty))
            lines.append("")

        if result.get("has_ambiguity"):
            lines.append(
                "Note: Lab batch is not yet set. Reply with <b>Batch 1</b> or "
                "<b>Batch 2</b> to resolve your specific lab schedule."
            )

        return "\n".join(lines).strip()

    def render_faculty_details(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render faculty lookup and professor directory."""
        res_type = result.get("type", "directory")

        if res_type == "directory":
            lines = ["<b>Faculty Directory:</b>", ""]
            faculty_list = result.get("faculty_list", [])
            if not faculty_list:
                lines.append("No faculty details currently available in your timetable.")
            else:
                for item in faculty_list:
                    lines.append(f"• <b>{item['subject']}:</b> {item['faculty']}")
            return "\n".join(lines).strip()

        elif res_type == "subject_faculty":
            subject = result.get("subject", "Subject")
            lines = [f"<b>Faculty — {subject}:</b>", ""]
            faculty_names = result.get("faculty_names", [])
            if not faculty_names:
                lines.append(f"No faculty details listed for <b>{subject}</b>.")
            else:
                lines.append(f"• <b>Instructor:</b> {', '.join(faculty_names)}")
                sessions = result.get("sessions", [])
                if sessions:
                    lines.append("")
                    lines.append("<b>Scheduled Sessions:</b>")
                    for s in sessions:
                        room_str = f" (Room: <code>{s['room']}</code>)" if s.get("room") else ""
                        lines.append(
                            f"• {s.get('day')}: {format_time_span(s.get('start_time', ''), s.get('end_time', ''))}{room_str}"
                        )
            return "\n".join(lines).strip()

        elif res_type == "faculty_schedule":
            faculty_name = result.get("faculty_name", "Professor")
            lines = [f"<b>Faculty Schedule — {faculty_name}:</b>", ""]
            subjects = result.get("subjects", [])
            if subjects:
                lines.append(f"• <b>Courses:</b> {', '.join(subjects)}")
            sessions = result.get("sessions", [])
            if sessions:
                lines.append("")
                lines.append("<b>Scheduled Sessions:</b>")
                for s in sessions:
                    room_str = f" (Room: <code>{s['room']}</code>)" if s.get("room") else ""
                    lines.append(
                        f"• {s.get('day')} {format_time_span(s.get('start_time', ''), s.get('end_time', ''))}: <b>{s.get('subject')}</b>{room_str}"
                    )
            return "\n".join(lines).strip()

        return self.render_generic_timetable(result, student_context)

    def render_room_details(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render room schedule and default classroom lookup."""
        room = result.get("room", "")
        lines = [f"<b>Room Details — <code>{room}</code>:</b>", ""]
        is_default = result.get("is_default_classroom", False)
        sessions = result.get("sessions", [])

        if is_default:
            lines.append(f"<code>{room}</code> is your default classroom for regular lectures.")
            if sessions:
                lines.append("")

        if sessions:
            lines.append("<b>Scheduled Sessions:</b>")
            for s in sessions:
                time_span = format_time_span(s.get("start_time", ""), s.get("end_time", ""))
                lines.append(f"• {s.get('day')}: <b>{s.get('activity_name')}</b> ({time_span})")
        elif not is_default:
            lines.append(f"No scheduled sessions found in <code>{room}</code>.")

        return "\n".join(lines).strip()

    def render_schedule_analytics(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Render deterministic calculations: counts, workload, frequency, free slots."""
        metric = result.get("metric")

        if metric == "classes_vs_labs":
            lines = ["<b>Schedule Breakdown:</b>", ""]
            t_count = result.get("theory_count", 0)
            t_hours = result.get("theory_hours", 0)
            l_count = result.get("lab_count", 0)
            l_hours = result.get("lab_hours", 0)
            tot_count = result.get("total_count", 0)
            tot_hours = result.get("total_hours", 0)

            lines.append(f"• <b>Theory Classes:</b> <code>{t_count}</code> ({t_hours} hrs)")
            lines.append(f"• <b>Lab Sessions:</b> <code>{l_count}</code> ({l_hours} hrs)")
            lines.append(f"• <b>Total Workload:</b> <code>{tot_count}</code> sessions ({tot_hours} hrs/week)")
            return "\n".join(lines).strip()

        elif metric == "subject_count":
            subject = result.get("subject", "Course")
            lines = [f"<b>Course Frequency — {subject}:</b>", ""]
            scope = result.get("scope")
            tot = result.get("total_in_week", 0)
            scoped = result.get("count_in_scope", 0)

            if scope in {"remaining_days", "remaining"}:
                lines.append(f"• <b>Remaining This Week:</b> <code>{scoped}</code> sessions")
                lines.append(f"• <b>Total in Week:</b> <code>{tot}</code> sessions")
            else:
                lines.append(f"• <b>Total in Week:</b> <code>{tot}</code> sessions")

            sessions = result.get("sessions", [])
            if sessions:
                lines.append("")
                lines.append("<b>Scheduled Slots:</b>")
                for s in sessions:
                    day = s.get("day", "")
                    start = s.get("start_time", "")
                    end = s.get("end_time", "")
                    lines.append(f"• {day}: {format_time_span(start, end)}")

            return "\n".join(lines).strip()

        elif metric == "daily_workload":
            lines = ["<b>Weekly Workload Distribution:</b>", ""]
            days = result.get("days", {})
            for d_name, d_info in days.items():
                if d_info.get("count", 0) > 0:
                    lines.append(f"• <b>{d_name}:</b> <code>{d_info['count']}</code> sessions ({d_info['hours']} hrs)")
                else:
                    lines.append(f"• <b>{d_name}:</b> <i>No classes</i>")

            heaviest = result.get("heaviest")
            lightest = result.get("lightest")
            if heaviest:
                lines.append("")
                lines.append(f"• <b>Busiest Day:</b> {heaviest[0]} ({heaviest[1]} hrs)")
            if lightest:
                lines.append(f"• <b>Lightest Day:</b> {lightest[0]} ({lightest[1]} hrs)")

            return "\n".join(lines).strip()

        elif metric == "free_slots":
            day = result.get("day", "Requested Day")
            lines = [f"<b>Free Slots — {day}:</b>", ""]
            slots = result.get("free_slots", [])
            if slots:
                for slot in slots:
                    lines.append(f"• {format_time_span(slot['start_time'], slot['end_time'])}")
            else:
                lines.append("No breaks between classes found for this day.")

            return "\n".join(lines).strip()

        msg = result.get("message", "Schedule analytics computed.")
        return f"<b>Schedule Analytics:</b>\n\n{msg}"

    def render_generic_timetable(
        self, result: dict[str, Any], student_context: StudentContext
    ) -> str:
        """Fallback renderer for other timetable tools."""
        msg = result.get("message") or str(result)
        return f"<b>Timetable Update:</b>\n\n{msg}"
