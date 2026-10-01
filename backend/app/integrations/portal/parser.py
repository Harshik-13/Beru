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
                is_selected = option.get("selected") is not None
                options.append(
                    SemesterOption(
                        semester_id=sem_id,
                        display_name=option.get_text(strip=True),
                        is_selected=is_selected,
                    )
                )
        return options

    @staticmethod
    def parse_attendance(html: str, semester_id: str) -> PortalAttendance:
        """
        Parse the attendance HTML table into normalized DTO.

        Expected structure:
        - Overall attendance displayed prominently
        - Subject-wise table with monthly and cumulative columns
        """
        soup = BeautifulSoup(html, "html.parser")

        # Find the main attendance table
        # Doctus typically uses a table with subject codes and attendance data
        tables = soup.find_all("table")
        if not tables:
            raise DoctusParserError("No attendance table found in HTML")

        # Look for the table containing attendance data
        # Usually the largest table with subject codes
        attendance_table = None
        for table in tables:
            rows = table.find_all("tr")
            if len(rows) > 2:  # Header + at least one data row
                # Check if this looks like an attendance table
                text = table.get_text().lower()
                if any(
                    kw in text
                    for kw in ["attended", "conducted", "cumulative", "monthly"]
                ):
                    attendance_table = table
                    break

        if not attendance_table:
            # Fallback: use the largest table
            attendance_table = max(tables, key=lambda t: len(t.find_all("tr")))

        # Parse overall attendance
        overall_attended, overall_conducted, portal_pct = (
            DoctusParser._parse_overall_attendance(soup)
        )

        # Parse subject-wise attendance
        subjects = DoctusParser._parse_subjects(attendance_table)

        return PortalAttendance(
            source="doctus",
            semester_id=semester_id,
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

        Looks for patterns like "57.39" or "163 / 284 (57.39)"
        """
        text = soup.get_text()

        # Look for pattern like "163 / 284 (57.39)" or just "57.39"
        # Pattern: X / Y (Z.ZZ)
        pattern1 = r"(\d+)\s*/\s*(\d+)\s*\(([\d.]+)\)"
        match = re.search(pattern1, text)
        if match:
            attended = int(match.group(1))
            conducted = int(match.group(2))
            pct = float(match.group(3))
            return attended, conducted, pct

        # Pattern: just percentage
        pattern2 = r"(\d+\.\d+)\s*%"
        match = re.search(pattern2, text)
        if match:
            pct = float(match.group(1))
            # Can't determine counts from percentage alone
            return 0, 0, pct

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
