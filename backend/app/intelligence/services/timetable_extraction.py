"""
Timetable extraction abstraction and implementation.

The VNR VJIET timetable format has specific layout-dependent structure.
This module provides the extraction interface and a practical implementation
using pdfplumber for PDF extraction with layout preservation.
"""

from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import time
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.timetable import TimetableEntry


class ExtractionConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class ExtractedCell:
    """A cell from the timetable grid with layout information."""

    day_of_week: int  # 0=Monday, 5=Saturday
    start_period: int  # 1-6 (P1-P6)
    end_period: int  # 1-6 (inclusive)
    content: str
    confidence: ExtractionConfidence = ExtractionConfidence.HIGH
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractedMetadata:
    """Metadata extracted from the timetable document."""

    academic_year: str | None = None
    regulation: str | None = None
    programme: str | None = None
    branch: str | None = None
    year: int | None = None
    semester: int | None = None
    section: str | None = None
    effective_from: str | None = None  # ISO date string
    default_classroom: str | None = None
    course_metadata: dict[str, dict] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SlashLabCandidate:
    """A slash-separated lab entry that needs batch resolution."""

    raw_content: str
    alternatives: tuple[str, ...]  # e.g., ("OOPJ LAB", "DBMS LAB")
    day_of_week: int
    start_period: int
    end_period: int
    confidence: ExtractionConfidence = ExtractionConfidence.MEDIUM


@dataclass(frozen=True, slots=True)
class TimetableExtractionResult:
    """Result of timetable extraction."""

    metadata: ExtractedMetadata
    cells: tuple[ExtractedCell, ...]
    slash_labs: tuple[SlashLabCandidate, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_ambiguity(self) -> bool:
        return any(
            c.confidence in (ExtractionConfidence.LOW, ExtractionConfidence.AMBIGUOUS)
            for c in self.cells
        ) or bool(self.slash_labs)

    @property
    def requires_review(self) -> bool:
        return self.has_ambiguity or bool(self.errors)


# Period time mapping for VNR VJIET
PERIOD_TIMES: dict[int, tuple[time, time]] = {
    1: (time(10, 0), time(11, 0)),  # P1
    2: (time(11, 0), time(12, 0)),  # P2
    3: (time(12, 0), time(13, 0)),  # P3
    4: (time(13, 40), time(14, 40)),  # P4 (after lunch)
    5: (time(14, 40), time(15, 40)),  # P5
    6: (time(15, 40), time(16, 40)),  # P6
}

LUNCH_START = time(13, 0)
LUNCH_END = time(13, 40)


def period_to_time(period: int) -> tuple[time, time] | None:
    """Convert period number to start/end time."""
    return PERIOD_TIMES.get(period)


def _confidence_to_float(confidence: ExtractionConfidence) -> float:
    """Convert confidence enum to float."""
    if confidence == ExtractionConfidence.HIGH:
        return 1.0
    if confidence == ExtractionConfidence.MEDIUM:
        return 0.5
    return 0.1


def cell_to_entry(
    cell: ExtractedCell, lab_batch: str | None = None
) -> "TimetableEntry":
    """Convert an extracted cell to a TimetableEntry."""
    # Import here to avoid circular imports
    from app.models.timetable import ActivityType, TimetableEntry

    start_time, end_time = (
        period_to_time(cell.start_period)[0],
        period_to_time(cell.end_period)[1],
    )

    # Determine activity type from content
    content_lower = cell.content.lower().strip()
    if any(kw in content_lower for kw in ["lab", "laboratory"]):
        activity_type = ActivityType.LAB
    elif any(kw in content_lower for kw in ["lunch", "break"]):
        activity_type = ActivityType.BREAK
    elif any(
        kw in content_lower
        for kw in ["library", "sports", "mtp", "cva", "eca", "cca", "activity"]
    ):
        activity_type = ActivityType.ACTIVITY
    else:
        activity_type = ActivityType.ACADEMIC

    return TimetableEntry(
        day_of_week=cell.day_of_week,
        start_time=start_time,
        end_time=end_time,
        activity_name=cell.content.strip(),
        activity_type=activity_type,
        lab_batch=lab_batch,
        extraction_confidence=_confidence_to_float(cell.confidence),
        extraction_notes=cell.notes,
    )


class TimetableExtractor(ABC):
    """Abstract interface for timetable extraction."""

    @abstractmethod
    async def extract(self, file_path: str) -> TimetableExtractionResult:
        """Extract timetable data from a file."""
        ...


class PdfTimetableExtractor(TimetableExtractor):
    """
    PDF-based timetable extractor using pdfplumber.

    Preserves layout information to handle multi-period cells and
    slash-separated labs correctly.
    """

    def __init__(self):
        self._pdfplumber = None

    def _get_pdfplumber(self):
        if self._pdfplumber is None:
            import pdfplumber

            self._pdfplumber = pdfplumber
        return self._pdfplumber

    async def extract(self, file_path: str) -> TimetableExtractionResult:
        pdfplumber = self._get_pdfplumber()

        cells = []
        slash_labs = []
        warnings = []
        errors = []
        metadata = ExtractedMetadata()

        try:
            with pdfplumber.open(file_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    # Extract tables with layout preservation
                    tables = page.extract_tables(
                        table_settings={
                            "vertical_strategy": "lines",
                            "horizontal_strategy": "lines",
                            "intersection_tolerance": 5,
                        }
                    )

                    for table in tables:
                        if not table or len(table) < 2:
                            continue

                        # Try to identify if this is the main schedule grid
                        # or the metadata section
                        if self._is_metadata_table(table):
                            self._extract_metadata(table, metadata)
                        else:
                            # Process schedule grid
                            extracted_cells, extracted_slash = (
                                self._extract_schedule_grid(table, page_num)
                            )
                            cells.extend(extracted_cells)
                            slash_labs.extend(extracted_slash)

        except Exception as e:
            errors.append(f"Extraction failed: {e!s}")

        return TimetableExtractionResult(
            metadata=metadata,
            cells=tuple(cells),
            slash_labs=tuple(slash_labs),
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    def _is_metadata_table(self, table: list[list[str | None]]) -> bool:
        """Check if table contains metadata rather than schedule."""
        if not table:
            return False

        # Check first few rows for metadata keywords
        for row in table[:3]:
            if not row:
                continue
            row_text = " ".join(str(c or "") for c in row).lower()
            if any(
                kw in row_text
                for kw in ["course code", "subject", "faculty", "room", "credits"]
            ):
                return True
        return False

    def _extract_metadata(
        self, table: list[list[str | None]], metadata: ExtractedMetadata
    ) -> None:
        """Extract metadata from the course info table."""
        for row in table:
            if not row or len(row) < 2:
                continue

            key = str(row[0] or "").strip().lower()
            value = str(row[1] or "").strip()

            if not value:
                continue

            if "academic" in key and "year" in key:
                metadata.academic_year = value
            elif "regulation" in key:
                metadata.regulation = value
            elif "programme" in key or "program" in key:
                metadata.programme = value
            elif "branch" in key:
                metadata.branch = value
            elif "year" in key and "academic" not in key:
                with suppress(ValueError):
                    metadata.year = int(value)
            elif "semester" in key:
                with suppress(ValueError):
                    metadata.semester = int(value)
            elif "section" in key:
                metadata.section = value
            elif "effective" in key or "date" in key:
                metadata.effective_from = value
            elif "classroom" in key or "room" in key:
                metadata.default_classroom = value
            elif (
                any(
                    kw in key
                    for kw in ["code", "subject", "course", "faculty", "credits"]
                )
                and len(row) >= 3
            ):
                # Course metadata row
                code = str(row[0] or "").strip()
                name = str(row[1] or "").strip()
                if code:
                    faculty_val = str(row[2] or "").strip() if len(row) > 2 else ""
                    metadata.course_metadata[code] = {
                        "name": name,
                        "faculty": faculty_val,
                    }

    def _extract_schedule_grid(
        self, table: list[list[str | None]], page_num: int
    ) -> tuple[list[ExtractedCell], list[SlashLabCandidate]]:
        """Extract cells from the main schedule grid."""
        cells = []
        slash_labs = []

        if not table or len(table) < 2:
            return cells, slash_labs

        # Find header row (days of week)
        header_row_idx = None
        day_cols = {}  # col_idx -> day_of_week

        for idx, row in enumerate(table):
            if not row:
                continue
            row_text = " ".join(str(c or "") for c in row).lower()
            if any(
                day in row_text
                for day in [
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                    "saturday",
                ]
            ):
                header_row_idx = idx
                for col_idx, cell in enumerate(row):
                    if not cell:
                        continue
                    cell_lower = str(cell).strip().lower()
                    if "monday" in cell_lower:
                        day_cols[col_idx] = 0
                    elif "tuesday" in cell_lower:
                        day_cols[col_idx] = 1
                    elif "wednesday" in cell_lower:
                        day_cols[col_idx] = 2
                    elif "thursday" in cell_lower:
                        day_cols[col_idx] = 3
                    elif "friday" in cell_lower:
                        day_cols[col_idx] = 4
                    elif "saturday" in cell_lower:
                        day_cols[col_idx] = 5
                break

        if header_row_idx is None:
            return cells, slash_labs

        # Process data rows (periods)
        period = 1
        for row_idx in range(header_row_idx + 1, len(table)):
            row = table[row_idx]
            if not row:
                continue

            # Check if this row indicates a period
            row_text = " ".join(str(c or "") for c in row).lower()
            if "lunch" in row_text or "break" in row_text:
                # Lunch row - skip but note it
                continue

            # Try to identify period from first column
            first_cell = str(row[0] or "").strip().upper() if row else ""
            if first_cell in {"P1", "P2", "P3", "P4", "P5", "P6"}:
                with suppress(ValueError, IndexError):
                    period = int(first_cell[1])

            # Extract cells for each day column
            for col_idx, day_of_week in day_cols.items():
                if col_idx >= len(row):
                    continue

                cell_content = row[col_idx]
                if not cell_content:
                    continue

                content = str(cell_content).strip()
                if not content:
                    continue

                # Check for multi-period cells (merged cells)
                # pdfplumber returns None for merged cells, so we need to detect
                # by looking at subsequent rows
                end_period = period
                for next_row_idx in range(row_idx + 1, len(table)):
                    next_row = table[next_row_idx]
                    if not next_row or col_idx >= len(next_row):
                        break
                    next_cell = next_row[col_idx]
                    if next_cell is None or next_cell == "":
                        # Merged cell continues
                        next_first = (
                            str(next_row[0] or "").strip().upper() if next_row else ""
                        )
                        if next_first in {"P1", "P2", "P3", "P4", "P5", "P6"}:
                            with suppress(ValueError, IndexError):
                                end_period = int(next_first[1])
                            continue
                        break
                    else:
                        break

                # Check for slash-separated labs
                if "/" in content:
                    parts = [p.strip() for p in content.split("/")]
                    if len(parts) == 2 and all(p for p in parts):
                        slash_labs.append(
                            SlashLabCandidate(
                                raw_content=content,
                                alternatives=tuple(parts),
                                day_of_week=day_of_week,
                                start_period=period,
                                end_period=end_period,
                            )
                        )
                        # Add as ambiguous cell
                        cells.append(
                            ExtractedCell(
                                day_of_week=day_of_week,
                                start_period=period,
                                end_period=end_period,
                                content=content,
                                confidence=ExtractionConfidence.AMBIGUOUS,
                                notes=f"Slash-separated lab: {content}",
                            )
                        )
                    else:
                        cells.append(
                            ExtractedCell(
                                day_of_week=day_of_week,
                                start_period=period,
                                end_period=end_period,
                                content=content,
                                confidence=ExtractionConfidence.MEDIUM,
                            )
                        )
                else:
                    cells.append(
                        ExtractedCell(
                            day_of_week=day_of_week,
                            start_period=period,
                            end_period=end_period,
                            content=content,
                            confidence=ExtractionConfidence.HIGH,
                        )
                    )

        return cells, slash_labs


def create_timetable_extractor() -> TimetableExtractor:
    """Factory function to create a timetable extractor."""
    return PdfTimetableExtractor()
