"""
Timetable extraction abstraction and implementation.

The VNR VJIET timetable format has specific layout-dependent structure.
This module provides the extraction interface and a practical implementation
using pdfplumber for PDF extraction with layout preservation.
"""

import logging
import re
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.timetable import TimetableEntry

logger = logging.getLogger(__name__)


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


class OcrTimetableExtractor(TimetableExtractor):
    """
    OCR-based timetable extractor using RapidOCR and pypdfium2.

    Handles scanned PDFs, camera photos, and screenshot images of timetables
    when direct vector PDF table extraction is unavailable or produces no cells.
    """

    def __init__(self):
        self._ocr = None

    def _get_ocr(self):
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr = RapidOCR()
        return self._ocr

    def _load_images(self, file_path: str) -> list[Any]:
        from PIL import Image

        lower = file_path.lower()
        if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
            return [Image.open(file_path)]

        # Otherwise treat as PDF
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(file_path)
        images = []
        for page in pdf:
            images.append(page.render(scale=2).to_pil())
        return images

    def _normalize_cell_text(self, text: str) -> str:
        t = text.strip()
        subs = {
            "OOPILAB": "OOPJ LAB",
            "OOPJLAB": "OOPJ LAB",
            "CNLAB": "CN LAB",
            "CFLAB": "CF LAB",
            "OSLAB": "OS LAB",
            "DVLAB": "DV LAB",
            "CMLAB": "CM LAB",
        }
        for k, v in subs.items():
            t = re.sub(rf"\b{k}\b", v, t, flags=re.IGNORECASE)
        t = re.sub(r"\s*/\s*", " / ", t)
        return t

    async def extract(self, file_path: str) -> TimetableExtractionResult:
        try:
            images = self._load_images(file_path)
            ocr = self._get_ocr()
        except Exception as e:
            return TimetableExtractionResult(
                metadata=ExtractedMetadata(),
                cells=(),
                slash_labs=(),
                errors=(f"OCR initialization failed: {e!s}",),
            )

        all_cells: list[ExtractedCell] = []
        all_slash_labs: list[SlashLabCandidate] = []
        meta_kwargs: dict[str, Any] = {"course_metadata": {}}
        warnings: list[str] = []
        errors: list[str] = []

        day_keywords = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
        }

        for page_idx, img in enumerate(images):
            _img_w, img_h = img.size
            result, _ = ocr(img)
            if not result:
                continue

            items = []
            for bbox, text, score in result:
                xs = [pt[0] for pt in bbox]
                ys = [pt[1] for pt in bbox]
                items.append(
                    {
                        "text": text.strip(),
                        "score": score,
                        "x0": min(xs),
                        "x1": max(xs),
                        "y0": min(ys),
                        "y1": max(ys),
                        "cx": (min(xs) + max(xs)) / 2,
                        "cy": (min(ys) + max(ys)) / 2,
                    }
                )

            # 1. Parse Metadata from Header items
            for it in items:
                t = it["text"]
                if re.search(r"20\d\d[-\u2013]20\d\d", t):
                    meta_kwargs["academic_year"] = re.search(
                        r"20\d\d[-\u2013]20\d\d", t
                    ).group(0)
                elif re.search(r"\bR\d+\b", t, re.IGNORECASE):
                    meta_kwargs["regulation"] = (
                        re.search(r"\bR\d+\b", t, re.IGNORECASE).group(0).upper()
                    )
                elif re.search(r"\bCSE-[A-Z]+\b", t, re.IGNORECASE):
                    meta_kwargs["branch"] = (
                        re.search(r"\bCSE-[A-Z]+\b", t, re.IGNORECASE).group(0).upper()
                    )
                elif "b.tech" in t.lower() or "b. tech" in t.lower():
                    meta_kwargs["programme"] = "B. Tech"
                elif re.search(r"\b(I|II|III|IV)\s*Year\b", t, re.IGNORECASE):
                    yr_str = (
                        re.search(r"\b(I|II|III|IV)\s*Year\b", t, re.IGNORECASE)
                        .group(1)
                        .upper()
                    )
                    meta_kwargs["year"] = {"I": 1, "II": 2, "III": 3, "IV": 4}.get(
                        yr_str
                    )
                elif re.search(
                    r"\bsem(?:ester)?\b\s*[:\uff1a]?\s*([I|V|X]+|\d+)", t, re.IGNORECASE
                ):
                    sem_str = (
                        re.search(
                            r"\bsem(?:ester)?\b\s*[:\uff1a]?\s*([I|V|X]+|\d+)",
                            t,
                            re.IGNORECASE,
                        )
                        .group(1)
                        .upper()
                    )
                    meta_kwargs["semester"] = {
                        "I": 1,
                        "II": 2,
                        "III": 3,
                        "IV": 4,
                        "V": 5,
                        "VI": 6,
                        "VII": 7,
                        "VIII": 8,
                    }.get(sem_str, int(sem_str) if sem_str.isdigit() else None)
                elif re.search(
                    r"\bsec(?:tion)?\b\s*[:\uff1a]?\s*([A-Z])\b", t, re.IGNORECASE
                ):
                    meta_kwargs["section"] = (
                        re.search(
                            r"\bsec(?:tion)?\b\s*[:\uff1a]?\s*([A-Z])\b",
                            t,
                            re.IGNORECASE,
                        )
                        .group(1)
                        .upper()
                    )
                elif re.search(
                    r"\broom\s*no\.?\b\s*[:\uff1a]?\s*([A-Za-z0-9\-]+)",
                    t,
                    re.IGNORECASE,
                ):
                    meta_kwargs["default_classroom"] = (
                        re.search(
                            r"\broom\s*no\.?\b\s*[:\uff1a]?\s*([A-Za-z0-9\-]+)",
                            t,
                            re.IGNORECASE,
                        )
                        .group(1)
                        .upper()
                    )
                elif re.search(
                    r"\bw\.?e\.?f\.?\b\s*[:\uff1a]?\s*(\d{2}/\d{2}/\d{4})",
                    t,
                    re.IGNORECASE,
                ):
                    meta_kwargs["effective_from"] = re.search(
                        r"\bw\.?e\.?f\.?\b\s*[:\uff1a]?\s*(\d{2}/\d{2}/\d{4})",
                        t,
                        re.IGNORECASE,
                    ).group(1)

            # Pair up adjacent labels/values if separate OCR items
            for it in items:
                t_lower = it["text"].lower()
                same_line = [
                    other
                    for other in items
                    if abs(other["cy"] - it["cy"]) < 12
                    and other["cx"] > it["cx"]
                    and (other["cx"] - it["cx"]) < 220
                ]
                if same_line:
                    closest = min(same_line, key=lambda x: x["cx"])
                    val = closest["text"].lstrip(":\uff1a ").strip()
                    if (
                        "section" in t_lower
                        and not meta_kwargs.get("section")
                        and len(val) == 1
                        and val.isalpha()
                    ):
                        meta_kwargs["section"] = val.upper()
                    elif (
                        ("room" in t_lower or "classroom" in t_lower)
                        and not meta_kwargs.get("default_classroom")
                        and val
                    ):
                        meta_kwargs["default_classroom"] = val.upper()
                    elif (
                        "w.e.f" in t_lower
                        and not meta_kwargs.get("effective_from")
                        and re.search(r"\d{2}/\d{2}/\d{4}", val)
                    ):
                        meta_kwargs["effective_from"] = re.search(
                            r"\d{2}/\d{2}/\d{4}", val
                        ).group(0)
                    elif (
                        "academic" in t_lower
                        and not meta_kwargs.get("academic_year")
                        and re.search(r"20\d\d[-\u2013]20\d\d", val)
                    ):
                        meta_kwargs["academic_year"] = re.search(
                            r"20\d\d[-\u2013]20\d\d", val
                        ).group(0)
                    elif "branch" in t_lower and not meta_kwargs.get("branch") and val:
                        meta_kwargs["branch"] = val.upper()
                    elif (
                        "regulation" in t_lower
                        and not meta_kwargs.get("regulation")
                        and val
                    ):
                        meta_kwargs["regulation"] = val.upper()
                    elif "class" in t_lower and not meta_kwargs.get("year"):
                        if "ii" in val.lower() or "2" in val:
                            meta_kwargs["year"] = 2
                        elif "iii" in val.lower() or "3" in val:
                            meta_kwargs["year"] = 3
                        elif "iv" in val.lower() or "4" in val:
                            meta_kwargs["year"] = 4
                        elif "i" in val.lower() or "1" in val:
                            meta_kwargs["year"] = 1
                    elif "semester" in t_lower and not meta_kwargs.get("semester"):
                        roman_map = {
                            "I": 1,
                            "II": 2,
                            "III": 3,
                            "IV": 4,
                            "V": 5,
                            "VI": 6,
                            "VII": 7,
                            "VIII": 8,
                        }
                        val_up = val.upper()
                        if val_up in roman_map:
                            meta_kwargs["semester"] = roman_map[val_up]

            # Parse course code table below schedule
            course_items = [it for it in items if it["cy"] > img_h * 0.45]
            for it in course_items:
                code_match = re.match(
                    r"^(2[0-9][A-Z0-9]{6,8})$", it["text"].replace(" ", "")
                )
                if code_match:
                    code = code_match.group(1)
                    same_row = [
                        o
                        for o in course_items
                        if abs(o["cy"] - it["cy"]) < 16 and o != it
                    ]
                    same_row_sorted = sorted(same_row, key=lambda x: x["cx"])
                    name = same_row_sorted[0]["text"] if same_row_sorted else ""
                    faculty = ""
                    for o in same_row_sorted[1:]:
                        if any(
                            title in o["text"].lower()
                            for title in ["dr.", "mr.", "mrs.", "ms."]
                        ):
                            faculty = o["text"]
                    meta_kwargs["course_metadata"][code] = {
                        "name": name,
                        "faculty": faculty,
                    }

            # 2. Detect Days and establish Row Bands
            detected_days = {}
            for it in items:
                clean = re.sub(r"[^a-zA-Z]", "", it["text"].lower())
                for d_name, d_idx in day_keywords.items():
                    if clean == d_name or (
                        len(clean) >= 5 and d_name.startswith(clean)
                    ):
                        detected_days[d_idx] = it
                        break

            if not detected_days:
                warnings.append(f"Page {page_idx}: No day rows detected.")
                continue

            sorted_d_indices = sorted(
                detected_days.keys(), key=lambda d: detected_days[d]["cy"]
            )
            row_bands = {}
            for i, d_idx in enumerate(sorted_d_indices):
                curr_y = detected_days[d_idx]["cy"]
                prev_y = (
                    detected_days[sorted_d_indices[i - 1]]["cy"]
                    if i > 0
                    else curr_y - 25
                )
                next_y = (
                    detected_days[sorted_d_indices[i + 1]]["cy"]
                    if i < len(sorted_d_indices) - 1
                    else curr_y + 25
                )
                row_bands[d_idx] = ((curr_y + prev_y) / 2, (curr_y + next_y) / 2)

            # 3. Detect Period Columns (P1-P6 and Lunch)
            first_day_y = min(it["y0"] for it in detected_days.values())
            period_num_items = [
                it
                for it in items
                if it["cy"] < first_day_y
                and it["cy"] > first_day_y - 80
                and it["text"] in {"1", "2", "3", "4", "5", "6"}
            ]
            period_centers: dict[int, float] = {}
            for it in period_num_items:
                with suppress(ValueError):
                    period_centers[int(it["text"])] = it["cx"]

            # Also check for time header items (10.00 AM -> P1, 11.00 AM -> P2, etc.)
            for it in items:
                if it["cy"] < first_day_y and it["cy"] > first_day_y - 80:
                    t_up = it["text"].upper()
                    if "10.00" in t_up and 1 not in period_centers:
                        period_centers[1] = it["cx"]
                    elif "11.00" in t_up and 2 not in period_centers:
                        period_centers[2] = it["cx"]
                    elif "12.00" in t_up and 3 not in period_centers:
                        period_centers[3] = it["cx"]
                    elif "01.40" in t_up and 4 not in period_centers:
                        period_centers[4] = it["cx"]
                    elif "02.40" in t_up and 5 not in period_centers:
                        period_centers[5] = it["cx"]
                    elif "03.40" in t_up and 6 not in period_centers:
                        period_centers[6] = it["cx"]

            # Derive slot width from adjacent period centers
            slot_w = None
            if 2 in period_centers and 3 in period_centers:
                slot_w = period_centers[3] - period_centers[2]
            elif 4 in period_centers and 5 in period_centers:
                slot_w = period_centers[5] - period_centers[4]
            elif 5 in period_centers and 6 in period_centers:
                slot_w = period_centers[6] - period_centers[5]
            else:
                day_left_x = min(it["x1"] for it in detected_days.values())
                table_right_x = max(
                    it["x1"]
                    for it in items
                    if first_day_y <= it["cy"] <= max(b[1] for b in row_bands.values())
                )
                slot_w = (table_right_x - day_left_x) / 7.2

            if 1 not in period_centers and 2 in period_centers:
                period_centers[1] = period_centers[2] - slot_w
            if 2 not in period_centers and 1 in period_centers:
                period_centers[2] = period_centers[1] + slot_w
            if 3 not in period_centers and 2 in period_centers:
                period_centers[3] = period_centers[2] + slot_w
            if 5 not in period_centers and 4 in period_centers:
                period_centers[5] = period_centers[4] + slot_w
            if 6 not in period_centers and 5 in period_centers:
                period_centers[6] = period_centers[5] + slot_w
            if 4 not in period_centers and 5 in period_centers:
                period_centers[4] = period_centers[5] - slot_w

            col_bounds: dict[int, tuple[float, float]] = {}
            for p in range(1, 7):
                if p in period_centers:
                    cx = period_centers[p]
                    col_bounds[p] = (cx - slot_w / 2, cx + slot_w / 2)

            grid_top = min(b[0] for b in row_bands.values())
            grid_bottom = max(b[1] for b in row_bands.values())
            min_grid_x = min(b[0] for b in col_bounds.values())
            max_grid_x = max(b[1] for b in col_bounds.values())

            grid_items = [
                it
                for it in items
                if grid_top <= it["cy"] <= grid_bottom
                and min_grid_x - 10 <= it["cx"] <= max_grid_x + 10
            ]

            for it in grid_items:
                day = None
                for d_idx, (y_t, y_b) in row_bands.items():
                    if y_t <= it["cy"] <= y_b:
                        day = d_idx
                        break
                if day is None:
                    continue

                if it["text"].upper() in {"L", "U", "N", "C", "H", "LUNCH"}:
                    continue

                raw_text = self._normalize_cell_text(it["text"])
                if not raw_text or len(raw_text) < 2:
                    continue

                overlapping = []
                for p, (p_left, p_right) in col_bounds.items():
                    overlap_l = max(it["x0"], p_left)
                    overlap_r = min(it["x1"], p_right)
                    if overlap_r > overlap_l:
                        overlap_w = overlap_r - overlap_l
                        if overlap_w > 12 or (
                            it["x1"] - it["x0"] < 30 and p_left <= it["cx"] <= p_right
                        ):
                            overlapping.append(p)

                if not overlapping:
                    closest_p = min(
                        col_bounds.keys(),
                        key=lambda p: abs(
                            (col_bounds[p][0] + col_bounds[p][1]) / 2 - it["cx"]
                        ),
                    )
                    overlapping = [closest_p]

                start_p = min(overlapping)
                end_p = max(overlapping)

                confidence = (
                    ExtractionConfidence.HIGH
                    if it["score"] >= 0.85
                    else ExtractionConfidence.MEDIUM
                )

                if "/" in raw_text:
                    parts = [p.strip() for p in raw_text.split("/")]
                    if len(parts) == 2 and all(parts):
                        all_slash_labs.append(
                            SlashLabCandidate(
                                raw_content=raw_text,
                                alternatives=tuple(parts),
                                day_of_week=day,
                                start_period=start_p,
                                end_period=end_p,
                                confidence=ExtractionConfidence.MEDIUM,
                            )
                        )
                        all_cells.append(
                            ExtractedCell(
                                day_of_week=day,
                                start_period=start_p,
                                end_period=end_p,
                                content=raw_text,
                                confidence=ExtractionConfidence.AMBIGUOUS,
                                notes=f"Slash-separated lab: {raw_text}",
                            )
                        )
                    else:
                        all_cells.append(
                            ExtractedCell(
                                day_of_week=day,
                                start_period=start_p,
                                end_period=end_p,
                                content=raw_text,
                                confidence=confidence,
                            )
                        )
                else:
                    all_cells.append(
                        ExtractedCell(
                            day_of_week=day,
                            start_period=start_p,
                            end_period=end_p,
                            content=raw_text,
                            confidence=confidence,
                        )
                    )

        metadata = ExtractedMetadata(**meta_kwargs)
        return TimetableExtractionResult(
            metadata=metadata,
            cells=tuple(all_cells),
            slash_labs=tuple(all_slash_labs),
            warnings=tuple(warnings),
            errors=tuple(errors),
        )


class HybridTimetableExtractor(TimetableExtractor):
    """
    Hybrid timetable extractor: tries vector PDF table extraction first,
    and falls back to OCR extraction when 0 cells are found or on image files.
    """

    def __init__(self):
        self._pdf_extractor = PdfTimetableExtractor()
        self._ocr_extractor = OcrTimetableExtractor()

    async def extract(self, file_path: str) -> TimetableExtractionResult:
        lower = file_path.lower()
        if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
            logger.info("Extracting timetable via OCR for image file: %s", file_path)
            return await self._ocr_extractor.extract(file_path)

        # First attempt: PDF text/table extraction
        try:
            result = await self._pdf_extractor.extract(file_path)
            if result.cells and not result.errors:
                logger.info(
                    "Extracted %d cells via PDF vector extractor for %s",
                    len(result.cells),
                    file_path,
                )
                return result
            logger.info(
                "PDF vector extractor returned %d cells; "
                "falling back to OCR extractor for %s",
                len(result.cells),
                file_path,
            )
        except Exception as e:
            logger.warning(
                "PDF vector extractor failed with %s; falling back to OCR", e
            )

        # Fallback: OCR extraction
        return await self._ocr_extractor.extract(file_path)


def create_timetable_extractor() -> TimetableExtractor:
    """Factory function to create a timetable extractor."""
    return HybridTimetableExtractor()
