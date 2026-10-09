"""Splits a detected table into heading rows, timetable body and legend rows.

Many institutional timetables are drawn as ONE ruled table per page: a title row
("W.E.F. … | AY … | SE BTech (Division-A)") above the weekday header and the
"Faculties: / Subjects:" legend below the last time row. Without this split the heading is
never read (no class/division scope) and legend lines are mistaken for class cells.
Format-independent: runs on every adapter's `Grid`.
"""
from __future__ import annotations

import re

from app.extraction.model import Grid, GridCell
from app.extraction.timeparse import parse_day, parse_time_label

# A legend block starts with a cell such as "Faculties:", "Subjects", "Course :" …
LEGEND_MARKER = re.compile(
    r"^\s*(faculties|faculty(?:\s+names?)?|teachers?|staff(?:\s+names?)?|subjects?|courses?)\s*(?::|-|$)", re.I)


def find_header(g: Grid) -> tuple[int, dict[int, int]] | None:
    """(header_row, {column: iso_day}) for the first row naming >= 3 distinct weekdays."""
    for r in range(min(g.n_rows, 8)):
        cols: dict[int, int] = {}
        for c in g.cells:
            if c.row == r and c.text:
                d = parse_day(c.text.split("\n")[0])
                if d:
                    for k in range(c.col, c.col + c.colspan):
                        cols[k] = d
        if len(set(cols.values())) >= 3:
            return r, cols
    return None


def _legend_start(g: Grid, header_row: int) -> int | None:
    for r in range(header_row + 1, g.n_rows):
        row = sorted((c for c in g.cells if c.row == r and c.text.strip()), key=lambda c: c.col)
        if not row or parse_time_label(row[0].text):
            continue
        if LEGEND_MARKER.match(row[0].text):
            return r
    return None


def split_layout(g: Grid) -> Grid:
    hdr = find_header(g)
    if hdr is None:
        return g
    header_row, _ = hdr
    heading = [c.text.strip() for c in sorted(g.cells, key=lambda c: (c.row, c.col))
               if c.row < header_row and c.text.strip()]
    if heading:
        g.header_text = "\n".join(heading + ([g.header_text] if g.header_text else []))

    start = _legend_start(g, header_row)
    if start is None:
        return g
    legend: list[list[str]] = []
    for r in range(start, g.n_rows):
        row = [""] * g.n_cols
        for c in g.cells:
            if c.row == r and c.col < g.n_cols:
                row[c.col] = c.text or ""
        if any(x.strip() for x in row):
            legend.append(row)
    kept: list[GridCell] = []
    for c in g.cells:
        if c.row >= start:
            continue
        if c.row + c.rowspan > start:
            c.rowspan = start - c.row
        kept.append(c)
    g.cells = kept
    g.n_rows = start
    # Separate legend tables first: they keep their own cell structure, a trailing merged cell may not.
    g.legend_rows = list(g.legend_rows) + legend
    return g
