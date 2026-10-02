"""
Doctus portal HTML parser.

Parses the attendance HTML embedded in the JSON response
from the Doctus attendance endpoint.
"""

import logging
import re

from bs4 import BeautifulSoup

from app.integrations.portal.dto import (
    PortalAttendance,
    PortalSubjectAttendance,
    SemesterOption,
)

logger = logging.getLogger(__name__)


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
        - Overall attendance displayed prominently or in total row
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

        # Parse subject-wise attendance and detected monthly period
        subjects, detected_month = (
            DoctusParser._parse_subjects(attendance_table)
            if attendance_table
            else ([], None)
        )

        # Parse cumulative and monthly overall attendance
        (
            overall_attended,
            overall_conducted,
            portal_pct,
            monthly_attended,
            monthly_conducted,
            monthly_pct,
        ) = DoctusParser._parse_overall_and_monthly(soup, attendance_table)

        # Validate and reconcile with subject sums if overall not found
        subj_cum_att = sum(s.cumulative_attended for s in subjects)
        subj_cum_cond = sum(s.cumulative_conducted for s in subjects)
        subj_month_att = sum(
            s.monthly_attended for s in subjects if s.monthly_attended is not None
        )
        subj_month_cond = sum(
            s.monthly_conducted for s in subjects if s.monthly_conducted is not None
        )

        if overall_conducted == 0 and subj_cum_cond > 0:
            overall_attended = subj_cum_att
            overall_conducted = subj_cum_cond
            portal_pct = round((subj_cum_att / subj_cum_cond) * 100.0, 2)
        elif (
            overall_conducted > 0
            and subj_cum_cond > 0
            and (overall_attended, overall_conducted)
            != (subj_cum_att, subj_cum_cond)
        ):
            logger.info(
                "Subject cumulative sum (%d/%d) differs from portal aggregate (%d/%d); preserving portal aggregate.",
                subj_cum_att,
                subj_cum_cond,
                overall_attended,
                overall_conducted,
            )

        if (monthly_conducted is None or monthly_conducted == 0) and subj_month_cond > 0:
            monthly_attended = subj_month_att
            monthly_conducted = subj_month_cond
            monthly_pct = round((subj_month_att / subj_month_cond) * 100.0, 2)

        if not attendance_table and overall_conducted == 0 and portal_pct is None:
            raise DoctusParserError("No attendance table or metrics found in HTML")

        return PortalAttendance(
            source="doctus",
            semester_id=resolved_semester_id,
            overall_attended=overall_attended,
            overall_conducted=overall_conducted,
            overall_percentage_from_portal=portal_pct,
            subjects=tuple(subjects),
            monthly_period=detected_month,
            monthly_attended=monthly_attended,
            monthly_conducted=monthly_conducted,
            monthly_percentage_from_portal=monthly_pct,
        )

    @staticmethod
    def _parse_overall_attendance(
        soup: BeautifulSoup,
    ) -> tuple[int, int, float | None]:
        """
        Parse overall attendance from the page.

        Preserved for backwards compatibility with test fixtures.
        """
        att, cond, pct, _, _, _ = DoctusParser._parse_overall_and_monthly(soup, None)
        return att, cond, pct

    @staticmethod
    def _parse_overall_and_monthly(
        soup: BeautifulSoup,
        attendance_table=None,
    ) -> tuple[int, int, float | None, int | None, int | None, float | None]:
        """
        Parse cumulative and monthly overall attendance metrics.

        Returns:
            (cumulative_att, cumulative_cond, cumulative_pct,
             monthly_att, monthly_cond, monthly_pct)
        """
        # 1. Try total row in attendance_table first
        if attendance_table:
            total_row = None
            for tr in attendance_table.find_all("tr"):
                cells = tr.find_all(["td", "th"])
                cell_texts = [c.get_text(strip=True) for c in cells]
                if any("total" in c.lower() for c in cell_texts):
                    total_row = tr
                    break

            if total_row:
                pairs = []
                for cell in total_row.find_all(["td", "th"]):
                    text = cell.get_text(strip=True)
                    for m in re.finditer(
                        r"(\d+)\s*/\s*(\d+)(?:\s*\(([\d.]+)\))?", text
                    ):
                        att = int(m.group(1))
                        cond = int(m.group(2))
                        pct = float(m.group(3)) if m.group(3) else None
                        if att <= cond and cond > 0:
                            if pct is None:
                                pct = round((att / cond) * 100.0, 2)
                            pairs.append((att, cond, pct))

                if len(pairs) >= 2:
                    # First pair is monthly, second pair is cumulative
                    monthly_att, monthly_cond, monthly_pct = pairs[0]
                    cum_att, cum_cond, cum_pct = pairs[1]
                    return (
                        cum_att,
                        cum_cond,
                        cum_pct,
                        monthly_att,
                        monthly_cond,
                        monthly_pct,
                    )
                elif len(pairs) == 1:
                    cum_att, cum_cond, cum_pct = pairs[0]
                    return cum_att, cum_cond, cum_pct, None, None, None

        # 2. Check soup text
        text = soup.get_text()

        # Extract all fraction patterns
        all_fractions = []
        for m in re.finditer(r"(\d+)\s*/\s*(\d+)(?:\s*\(([\d.]+)\))?", text):
            att = int(m.group(1))
            cond = int(m.group(2))
            pct = float(m.group(3)) if m.group(3) else None
            if att <= cond and cond > 0:
                if pct is None:
                    pct = round((att / cond) * 100.0, 2)
                all_fractions.append((att, cond, pct))

        # Check explicit "Overall" or "Cumulative" label:
        # Form A: Overall Attendance: 163 / 284 (57.39)
        oa_frac_match = re.search(
            r"(?:Overall|Cumulative)\s*(?:Attendance)?\s*[:\n\r\t]*\s*(\d+)\s*/\s*(\d+)(?:\s*\(?([\d.]+)\%?\)?|\s*([\d.]+)\%)?",
            text,
            re.IGNORECASE,
        )
        if oa_frac_match:
            att_val = int(oa_frac_match.group(1))
            cond_val = int(oa_frac_match.group(2))
            pct_raw = oa_frac_match.group(3) or oa_frac_match.group(4)
            pct_val = (
                float(pct_raw)
                if pct_raw
                else round((att_val / cond_val) * 100.0, 2)
            )
            # Find monthly from all_fractions if distinct
            monthly_att, monthly_cond, monthly_pct = None, None, None
            for f_att, f_cond, f_pct in all_fractions:
                if (f_att, f_cond) != (att_val, cond_val) and f_cond < cond_val:
                    monthly_att, monthly_cond, monthly_pct = f_att, f_cond, f_pct
                    break
            return att_val, cond_val, pct_val, monthly_att, monthly_cond, monthly_pct

        # Form B: Overall Attendance: 65.5% (200 / 305) or Overall Attendance: 75.50%
        oa_pct_match = re.search(
            r"(?:Overall|Cumulative)\s*(?:Attendance)?\s*[:\n\r\t]*\s*([\d.]+)\s*%?(?:\s*\(?\s*(\d+)\s*/\s*(\d+)\s*\)?)?",
            text,
            re.IGNORECASE,
        )
        if oa_pct_match:
            pct_val = float(oa_pct_match.group(1))
            att_val = int(oa_pct_match.group(2)) if oa_pct_match.group(2) else 0
            cond_val = int(oa_pct_match.group(3)) if oa_pct_match.group(3) else 0
            if cond_val > 0:
                monthly_att, monthly_cond, monthly_pct = None, None, None
                for f_att, f_cond, f_pct in all_fractions:
                    if (f_att, f_cond) != (att_val, cond_val) and f_cond < cond_val:
                        monthly_att, monthly_cond, monthly_pct = f_att, f_cond, f_pct
                        break
                return att_val, cond_val, pct_val, monthly_att, monthly_cond, monthly_pct
            else:
                if all_fractions:
                    largest = max(all_fractions, key=lambda x: x[1])
                    m_att, m_cond, m_pct = (
                        min(all_fractions, key=lambda x: x[1])
                        if len(all_fractions) > 1
                        else (None, None, None)
                    )
                    return largest[0], largest[1], pct_val, m_att, m_cond, m_pct
                return 0, 0, pct_val, None, None, None

        if len(all_fractions) >= 2:
            sorted_f = sorted(all_fractions, key=lambda x: x[1])
            monthly = sorted_f[0]
            cumulative = sorted_f[-1]
            return (
                cumulative[0],
                cumulative[1],
                cumulative[2],
                monthly[0],
                monthly[1],
                monthly[2],
            )
        elif len(all_fractions) == 1:
            cum = all_fractions[0]
            return cum[0], cum[1], cum[2], None, None, None

        pct_match = re.search(r"(\d+\.\d+)\s*%", text)
        if pct_match:
            return 0, 0, float(pct_match.group(1)), None, None, None

        return 0, 0, None, None, None, None

    @staticmethod
    def _parse_subjects(table) -> tuple[list[PortalSubjectAttendance], str | None]:
        """Parse subject-wise attendance rows and detected monthly period from the table."""
        subjects = []
        rows = table.find_all("tr")

        # Discover monthly period from table header
        monthly_period = None
        month_pattern = re.compile(
            r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
            r"(?:\s*,\s*\d{4}|\s+\d{4})?",
            re.IGNORECASE,
        )
        for row in rows:
            for cell in row.find_all(["th", "td"]):
                m = month_pattern.search(cell.get_text(strip=True))
                if m:
                    monthly_period = m.group(0).strip()
                    break
            if monthly_period:
                break

        for row in rows:
            cells = row.find_all(["td", "th"])
            cell_texts = [cell.get_text(strip=True) for cell in cells]

            # Skip header rows and total rows
            if not cell_texts or any(
                kw in " ".join(cell_texts).lower()
                for kw in ["subject", "code", "monthly", "cumulative", "total"]
            ):
                continue

            # Try to parse subject data
            subject = DoctusParser._parse_subject_row(
                cell_texts, monthly_period=monthly_period
            )
            if subject:
                subjects.append(subject)

        return subjects, monthly_period

    @staticmethod
    def _parse_subject_row(
        cells: list[str], monthly_period: str | None = None
    ) -> PortalSubjectAttendance | None:
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
            monthly_period=monthly_period,
            monthly_attended=monthly_attended,
            monthly_conducted=monthly_conducted,
            cumulative_attended=cumulative_attended,
            cumulative_conducted=cumulative_conducted,
        )
