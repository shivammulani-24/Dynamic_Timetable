"""Grid → candidate entries. Format-independent."""
from __future__ import annotations

from app.extraction.cellparse import BREAK_RE, parse_cell
from app.extraction.model import CandidateEntry, Finding, Grid, GridCell, SectionInfo
from app.extraction.timeparse import (
    BREAK_WORDS_RE,
    ResolvedTime,
    parse_day,
    parse_time_label,
    resolve_sequence,
)


def _transpose(g: Grid) -> Grid:
    cells = [GridCell(c.col, c.row, c.text, c.colspan, c.rowspan, c.bbox, c.ocr_conf) for c in g.cells]
    return Grid(g.page, g.method, g.n_cols, g.n_rows, cells, g.header_text, g.context_text, g.legend_rows, g.page_size)


def _anchors(g: Grid) -> dict[tuple[int, int], GridCell]:
    return {(c.row, c.col): c for c in g.cells}


def _find_header(g: Grid) -> tuple[int, dict[int, int]] | None:
    """Returns (header_row, {column: iso_day}) for the first row naming >= 3 distinct weekdays."""
    for r in range(min(g.n_rows, 5)):
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


def _batch_label(section: SectionInfo | None, subgroup: str | None) -> tuple[str | None, list[dict]]:
    msgs: list[dict] = []
    level = section.program_level if section else None
    divs = section.divisions if section else []
    if subgroup:
        if divs and subgroup[0] not in divs:
            msgs.append({"severity": "WARNING", "code": "SUBGROUP_DIVISION_MISMATCH",
                         "message": f"Sub-group {subgroup} does not belong to the section's division(s) {', '.join(divs)}."})
        return (f"{level}-{subgroup}" if level else subgroup), msgs
    if len(divs) == 1:
        return (f"{level}-{divs[0]}" if level else f"DIV-{divs[0]}"), msgs
    if len(divs) > 1:
        msgs.append({"severity": "WARNING", "code": "DIVISION_SCOPE_COMBINED",
                     "message": f"This section combines divisions {', '.join(divs)}; the cell does not name one, "
                                "so no single division is assigned."})
        return (f"{level}-{'/'.join(divs)}" if level else "/".join(divs)), msgs
    return level, msgs


def parse_grid(g: Grid, section: SectionInfo | None, *, require_scope: bool, known_rooms: set[str]) -> tuple[list[CandidateEntry], list[Finding]]:
    findings: list[Finding] = []
    hdr = _find_header(g)
    if hdr is None:
        t = _transpose(g)
        hdr = _find_header(t)
        if hdr is None:
            return [], [Finding("PAGE_ERROR", "NO_WEEKDAY_HEADER", "Could not find a weekday header in this table.", g.page)]
        g = t
    header_row, day_cols = hdr
    anchors = _anchors(g)
    first_day_col = min(day_cols)
    body_rows = list(range(header_row + 1, g.n_rows))

    # Choose the time column: left of the first day column with the most readable time labels.
    best_col, best_hits = None, 0
    for c in range(0, first_day_col):
        hits = sum(1 for r in body_rows if (cell := anchors.get((r, c))) and parse_time_label(cell.text))
        if hits > best_hits:
            best_col, best_hits = c, hits
    labels = []
    label_text: dict[int, str] = {}
    for r in body_rows:
        cell = anchors.get((r, best_col)) if best_col is not None else None
        txt = cell.text if cell else ""
        label_text[r] = txt
        labels.append(parse_time_label(txt) if txt else None)
    if best_col is None:
        findings.append(Finding("CRITICAL", "TIME_COLUMN_NOT_FOUND",
                                "No time labels were found for this table; its entries have no times.", g.page))
    resolved: dict[int, ResolvedTime] = dict(zip(body_rows, resolve_sequence(labels)))

    legend = section.legend if section else {"faculty": {}, "subject": {}}
    tentative = bool(section and section.is_tentative)
    entries: list[CandidateEntry] = []

    def make(item_kind: str, day: int, rows: list[int], raw: str, region, item=None, ocr_conf=None) -> CandidateEntry:
        rts = [resolved.get(r) for r in rows if resolved.get(r)]
        start = rts[0].start if rts else None
        end = rts[-1].end if rts else None
        uncertain = (not rts) or any(rt.uncertain for rt in rts) or start is None or end is None
        raw_label = " | ".join(label_text.get(r, "") for r in rows if label_text.get(r))
        e = CandidateEntry(
            section_key=section.key if section else None, page=g.page, entry_kind=item_kind, day_of_week=day,
            class_date=None, start_time=start, end_time=end, time_label_raw=raw_label[:120] or None,
            time_uncertain=uncertain, course_label=None, course_name=None, staff_label=None, staff_name=None,
            batch_label=None, room_label=None, raw_text=raw, region=region, method=g.method, is_tentative=tentative,
        )
        if ocr_conf is not None:
            e.region = {**(region or {}), "ocr_confidence": round(ocr_conf, 1)}
        seen = set()
        for rt in rts:
            for issue in rt.issues:
                if issue["code"] not in seen:
                    e.messages.append(dict(issue))
                    seen.add(issue["code"])
        if start and end and end <= start:
            e.messages.append({"severity": "CRITICAL", "code": "TIME_RANGE_INVALID", "message": "End time is not after start time."})
            e.start_time = e.end_time = None
            e.time_uncertain = True
        if item is not None:
            e.course_label = item.course_label + (f" ({item.group_label})" if item.group_label else "") if item.course_label else item.group_label
            e.course_name = item.course_name
            e.staff_label = "+".join(item.staff_labels) or None
            e.staff_name = ", ".join(item.staff_names) or None
            e.room_label = item.room_label
            e.messages += [dict(m) for m in item.messages]
            if item_kind == "CLASS":
                e.batch_label, msgs = _batch_label(section, item.subgroup)
                e.messages += msgs
                if require_scope and not e.batch_label:
                    e.messages.append({"severity": "CRITICAL", "code": "SECTION_SCOPE_UNKNOWN",
                                       "message": "The class/division this entry belongs to could not be determined."})
                if item.explicit_time:
                    _check_explicit(e, item.explicit_time)
        return e

    for (r, c), cell in sorted(anchors.items()):
        if r <= header_row or c not in day_cols or not cell.text.strip():
            continue
        rows = [x for x in range(r, r + cell.rowspan) if x in resolved]
        days = sorted({day_cols[k] for k in range(c, c + cell.colspan) if k in day_cols})
        region = {"bbox": list(cell.bbox) if cell.bbox else None, "grid_row": r, "grid_col": c,
                  "rowspan": cell.rowspan, "colspan": cell.colspan}
        for item in parse_cell(cell.text, legend, known_rooms):
            for d in days:
                e = make(item.kind, d, rows, cell.text, region, item, cell.ocr_conf)
                if item.kind != "CLASS":
                    e.course_label = item.course_label
                entries.append(e)

    # Rows whose time-column label itself is a break (e.g. "11:00-11:15 SHORT BREAK") with empty day cells.
    for r in body_rows:
        txt = label_text.get(r, "")
        if txt and BREAK_WORDS_RE.search(txt) and not any(
            (cell := g.at(r, c)) and cell.text.strip() and cell.col in day_cols for c in day_cols
        ):
            m = BREAK_RE.search(txt)
            for d in sorted(set(day_cols.values())):
                e = make("BREAK", d, [r], txt, {"grid_row": r, "grid_col": best_col})
                e.course_label = (m.group(0) if m else "BREAK").upper()
                entries.append(e)
    return entries, findings


def _check_explicit(e: CandidateEntry, label) -> None:
    rt = resolve_sequence([label])[0]
    if rt.start is None:
        e.messages.append({"severity": "WARNING", "code": "EXPLICIT_TIME_UNREADABLE",
                           "message": f"The cell's own time '{label.raw}' could not be interpreted; row time kept for review."})
        e.time_uncertain = True
        return
    if e.start_time is None:
        e.start_time, e.end_time = rt.start, rt.end
        e.time_uncertain = rt.uncertain
        e.messages.append({"severity": "INFO", "code": "TIME_FROM_CELL", "message": f"Time taken from the cell text '{label.raw}'."})
        return
    if (rt.start, rt.end) != (e.start_time, e.end_time):
        e.messages.append({
            "severity": "WARNING", "code": "EXPLICIT_TIME_CONFLICT",
            "message": f"Cell says {rt.start:%H:%M}–{rt.end:%H:%M} but the row is "
                       f"{e.start_time:%H:%M}–{e.end_time:%H:%M}. Both preserved; needs review.",
            "details": {"cell_start": rt.start.strftime("%H:%M"), "cell_end": rt.end.strftime("%H:%M")},
        })
        e.time_uncertain = True
