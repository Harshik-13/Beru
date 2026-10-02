"""
Doctus portal HTML parser.

Parses the attendance HTML embedded in the JSON response
from the Doctus attendance endpoint.
"""

import re

from bs4 import BeautifulSoup

from app.integrations.portal.dto import (
    PortalAttendance,
    PortalSubjectAttendance,
    SemesterOption,
)


class DoctusParserError(Exception):
    """Raised when Doctus HTML parsing fails."""

    pass


class DoctusParser:
    """Parses Doctus portal attendance HTML into normalized DTOs."""

    @staticmethod
    def parse_semester_options(html: str) -> list[SemesterOption]:
        """
        Parse semester options from the attendance page HTML.

        Looks for the #StdSemPop select element.
        """
        soup = BeautifulSoup(html, "html.parser")
        select = soup.find("select", id="StdSemPop")
        if not select:
            select = soup.find(
                "select",
                attrs={"id": re.compile(r"sem", re.I)},
            ) or soup.find(
                "select",
                attrs={"name": re.compile(r"sem", re.I)},
            )
        if not select:
            return []

        options = []
        for option in select.find_all("option"):
            sem_id = option.get("value")
            if sem_id:
                is_selected = "selected" in option.attrs or option.get("selected") is not None
                options.append(
                    SemesterOption(
                        semester_id=sem_id,
                        display_name=option.get_text(strip=True),
                        is_selected=is_selected,
                    )
                )
        return options

    @staticmethod
    def parse_attendance(html: str, semester_id: str | None = None) -> PortalAttendance:
        """
        Parse the attendance HTML table into normalized DTO.

        If semester_id is not supplied or is 'undefined', dynamically extracts
        the selected semester from the HTML (#StdSemPop).

        Expected structure:
        - Overall attendance displayed prominently
        - Subject-wise table with monthly and cumulative columns
        """
        soup = BeautifulSoup(html, "html.parser")

        # Resolve semester_id dynamically if omitted or 'undefined'
        if not semester_id or semester_id == "undefined":
            discovered_options = DoctusParser.parse_semester_options(html)
            selected_option = next((s for s in discovered_options if s.is_selected), None)
            if not selected_option and discovered_options:
                selected_option = discovered_options[0]
            resolved_semester_id = selected_option.semester_id if selected_option else "default"
        else:
            resolved_semester_id = semester_id

        # Find the main attendance table
        tables = soup.find_all("table")
        attendance_table = None
        if tables:
            for table in tables:
                rows = table.find_all("tr")
                if len(rows) > 2:  # Header + at least one data row
                    text = table.get_text().lower()
                    if any(
                        kw in text
                        for kw in ["attended", "conducted", "cumulative", "monthly"]
                    ):
                        attendance_table = table
                        break

            if not attendance_table and tables:
                # Fallback: use the largest table
                attendance_table = max(tables, key=lambda t: len(t.find_all("tr")))

        # Parse overall attendance
        overall_attended, overall_conducted, portal_pct = (
            DoctusParser._parse_overall_attendance(soup)
        )

        if not attendance_table and overall_conducted == 0 and portal_pct is None:
            raise DoctusParserError("No attendance table or metrics found in HTML")

        # Parse subject-wise attendance (lenient)
        subjects = DoctusParser._parse_subjects(attendance_table) if attendance_table else []

        return PortalAttendance(
            source="doctus",
            semester_id=resolved_semester_id,
            overall_attended=overall_attended,
            overall_conducted=overall_conducted,
            overall_percentage_from_portal=portal_pct,
            subjects=tuple(subjects),
        )

    @staticmethod
    def _parse_overall_attendance(
        soup: BeautifulSoup,
    ) -> tuple[int, int, float | None]:
        """
        Parse overall attendance from the page.

        Looks for patterns like "178 / 306 (58.17)", "Overall Attendance: 58.17% (178 / 306)",
        "Overall Attendance 58.17", or "58.17%"
        """
        text = soup.get_text()

        # 1. Pattern: X / Y (Z.ZZ)
        match1 = re.search(r"(\d+)\s*/\s*(\d+)\s*\(([\d.]+)\)", text)
        if match1:
            return int(match1.group(1)), int(match1.group(2)), float(match1.group(3))

        attended = 0
        conducted = 0
        pct = None

        # 2. Check for percentage around Overall Attendance or general percentage
        oa_match = re.search(
            r"Overall\s+Attendance\s*[:\n\r\t]*\s*([\d.]+)\s*%?",
            text,
            re.IGNORECASE,
        )
        if oa_match:
            try:
                pct = float(oa_match.group(1))
            except ValueError:
                pass

        if pct is None:
            pct_match = re.search(r"(\d+\.\d+)\s*%", text)
            if pct_match:
                try:
                    pct = float(pct_match.group(1))
                except ValueError:
                    pass

        # 3. Check for fraction (e.g. (178 / 306) or 178 / 306)
        frac_match = re.search(r"\(?\s*(\d+)\s*/\s*(\d+)\s*\)?", text)
        if frac_match:
            try:
                att = int(frac_match.group(1))
                cond = int(frac_match.group(2))
                if att <= cond:
                    attended, conducted = att, cond
            except ValueError:
                pass

        if attended > 0 or conducted > 0 or pct is not None:
            return attended, conducted, pct

        return 0, 0, None

    @staticmethod
    def _parse_subjects(table) -> list[PortalSubjectAttendance]:
        """Parse subject-wise attendance rows from the table."""
        subjects = []
        rows = table.find_all("tr")

        for row in rows:
            cells = row.find_all(["td", "th"])
            cell_texts = [cell.get_text(strip=True) for cell in cells]

            # Skip header rows
            if not cell_texts or any(
                kw in " ".join(cell_texts).lower()
                for kw in ["subject", "code", "monthly", "cumulative", "total"]
            ):
                continue

            # Try to parse subject data
            subject = DoctusParser._parse_subject_row(cell_texts)
            if subject:
                subjects.append(subject)

        return subjects

    @staticmethod
    def _parse_subject_row(cells: list[str]) -> PortalSubjectAttendance | None:
        """Parse a single subject row."""
        if len(cells) < 2:
            return None

        subject_code = None
        monthly_attended = None
        monthly_conducted = None
        cumulative_attended = None
        cumulative_conducted = None

        # Find subject code (usually first non-empty cell that looks like a code)
        for cell in cells:
            if cell and re.match(r"^[A-Z0-9]{4,}$", cell):
                subject_code = cell
                break

        if not subject_code:
            return None

        # Try to extract numeric patterns from cells
        # Look for patterns like "3 / 5", "8 / 25", etc.
        numbers_found = []
        for cell in cells:
            # Pattern: X / Y
            matches = re.findall(r"(\d+)\s*/\s*(\d+)", cell)
            for match in matches:
                numbers_found.append((int(match[0]), int(match[1])))

        if len(numbers_found) >= 2:
            # Assume first pair is monthly, second is cumulative
            monthly_attended, monthly_conducted = numbers_found[0]
            cumulative_attended, cumulative_conducted = numbers_found[1]
        elif len(numbers_found) == 1:
            # Only cumulative available
            monthly_attended = None
            monthly_conducted = None
            cumulative_attended, cumulative_conducted = numbers_found[0]
        else:
            return None

        # Validate
        if cumulative_attended is None or cumulative_conducted is None:
            return None

        if cumulative_attended > cumulative_conducted:
            return None

        if (
            monthly_attended is not None
            and monthly_conducted is not None
            and monthly_attended > monthly_conducted
        ):
            return None

        return PortalSubjectAttendance(
            subject_code=subject_code,
            subject_name=None,
            monthly_period=None,
            monthly_attended=monthly_attended,
            monthly_conducted=monthly_conducted,
            cumulative_attended=cumulative_attended,
            cumulative_conducted=cumulative_conducted,
        )
