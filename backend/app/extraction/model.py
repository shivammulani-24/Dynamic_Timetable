"""Intermediate representation shared by every input format.

PDF / image / spreadsheet / Word adapters all produce `Grid`s. The grid parser, validator and
persistence layer never know which format the data came from (except for provenance/method).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from typing import Any

PARSER_VERSION = "tt-grid-parser/1.1.0"


@dataclass
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float | None = None  # OCR confidence 0..100 when available

    @property
    def xc(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def yc(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class GridCell:
    row: int
    col: int
    text: str
    rowspan: int = 1
    colspan: int = 1
    bbox: tuple[float, float, float, float] | None = None
    ocr_conf: float | None = None


@dataclass
class Grid:
    """One rectangular timetable table found on a page/sheet/table."""

    page: int                    # 1-based page / sheet / table index
    method: str                  # TEXT | OCR | SPREADSHEET | DOCX
    n_rows: int
    n_cols: int
    cells: list[GridCell]
    header_text: str = ""        # text above the table (section heading)
    context_text: str = ""       # other page text (legends, notes)
    legend_rows: list[list[str]] = field(default_factory=list)  # extra 2+ column tables (possible legends)
    page_size: tuple[float, float] | None = None

    def at(self, r: int, c: int) -> GridCell | None:
        for cell in self.cells:
            if cell.row <= r < cell.row + cell.rowspan and cell.col <= c < cell.col + cell.colspan:
                return cell
        return None


@dataclass
class Finding:
    severity: str          # BLOCKING | PAGE_ERROR | CRITICAL | WARNING | INFO | SECTION_FLAG | METADATA_WARNING
    code: str
    message: str
    page: int | None = None
    entry_index: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class SectionInfo:
    key: int
    page: int
    title: str | None
    program_level: str | None
    divisions: list[str]
    is_tentative: bool
    header_raw: str
    legend: dict[str, dict[str, str]]  # {"faculty": {...}, "subject": {...}}
    method: str
    effective_from: date | None = None
    effective_from_raw: str | None = None
    academic_year_label: str | None = None
    term_label: str | None = None


@dataclass
class CandidateEntry:
    section_key: int | None
    page: int
    entry_kind: str                      # CLASS | BREAK | ACTIVITY
    day_of_week: int | None
    class_date: date | None
    start_time: time | None
    end_time: time | None
    time_label_raw: str | None
    time_uncertain: bool
    course_label: str | None
    course_name: str | None
    staff_label: str | None
    staff_name: str | None
    batch_label: str | None
    room_label: str | None
    raw_text: str
    region: dict[str, Any] | None
    method: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    verification_status: str = "UNVERIFIED"
    confidence: float = 1.0
    is_tentative: bool = False

    def warn(self, severity: str, code: str, message: str, **details: Any) -> None:
        self.messages.append({"severity": severity, "code": code, "message": message, **({"details": details} if details else {})})

    def has_code(self, code: str) -> bool:
        return any(m["code"] == code for m in self.messages)


@dataclass
class ExtractionResult:
    page_count: int
    pages: list[dict[str, Any]]          # per page: {"page":n,"method":..,"status":PARSED|OCR|NO_TABLE|FAILED}
    sections: list[SectionInfo]
    entries: list[CandidateEntry]
    findings: list[Finding]
    file_format: str
    effective_from: date | None = None
    effective_from_raw: str | None = None
    term_label: str | None = None
    academic_year_label: str | None = None
