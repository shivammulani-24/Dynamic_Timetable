"""Section heading and legend parsing."""
from __future__ import annotations

import re

from app.extraction.timeparse import parse_date_text

_LEVEL = re.compile(r"\b(FE|SE|TE|BE|F\.?Y|S\.?Y|T\.?Y|L\.?Y|M\.?E|M\.?TECH|FY|SY|TY|LY)\b\.?(?:\s*(?:B\.?\s?TECH|B\.?\s?E|M\.?\s?TECH))?", re.I)
_DIV = re.compile(r"\bDiv(?:ision)?\.?\s*[-:]?\s*\(?\s*([A-Z](?:\s*(?:,|&|and|/)\s*[A-Z])*)\s*\)?", re.I)
_TENTATIVE = re.compile(r"\btentative\b", re.I)
_WEF = re.compile(r"\b(?:W\.?\s?E\.?\s?F\.?|with effect from|effective from)\s*[:.-]?\s*([^\n]{4,40})", re.I)
_AY = re.compile(r"\b(?:A\.?\s?Y\.?|academic year)\s*[:.-]?\s*(\d{4})\s*[-–/]\s*(\d{2,4})", re.I)
_TERM = re.compile(r"\b(odd|even)\s+sem(?:ester)?\b|\bsem(?:ester)?\s*[-:]?\s*([IVX]+|\d+)\b", re.I)

_NORMAL_LEVEL = {"FY": "FE", "SY": "SE", "TY": "TE", "LY": "BE"}


def parse_heading(text: str) -> dict:
    t = text or ""
    level = None
    m = _LEVEL.search(t)
    if m:
        lv = re.sub(r"[^A-Z]", "", m.group(1).upper())
        level = _NORMAL_LEVEL.get(lv, lv)
    divisions: list[str] = []
    for dm in _DIV.finditer(t):
        divisions += [d.upper() for d in re.findall(r"[A-Z]", dm.group(1), re.I)]
    divisions = sorted(set(divisions))
    eff, eff_raw, eff_ambiguous = None, None, False
    wm = _WEF.search(t)
    if wm:
        eff_raw = wm.group(0).strip()
        eff, eff_ambiguous = parse_date_text(wm.group(1))
    ay = None
    am = _AY.search(t)
    if am:
        y2 = am.group(2)
        y2 = y2 if len(y2) == 4 else am.group(1)[:2] + y2
        ay = f"{am.group(1)}-{y2}"
    term = None
    tm = _TERM.search(t)
    if tm:
        term = (tm.group(1).upper() + " SEMESTER") if tm.group(1) else f"SEMESTER {tm.group(2).upper()}"
    title_line = next((ln.strip() for ln in t.splitlines() if _LEVEL.search(ln) or _DIV.search(ln)), None)
    return {
        "program_level": level,
        "divisions": divisions,
        "is_tentative": bool(_TENTATIVE.search(t)),
        "effective_from": eff,
        "effective_from_raw": eff_raw,
        "effective_from_ambiguous": eff_ambiguous,
        "academic_year_label": ay,
        "term_label": term,
        "title": (title_line or "")[:300] or None,
    }


_HONORIFIC = re.compile(r"^(prof|dr|mr|mrs|ms|miss|smt|shri)\.?\b", re.I)
# "KKD - Prof. Kiran Desai", "KKD : Data Base...", "KKD = ...", "KKD – ..."
# One or more "ABBR - Expansion" pairs on a line; each expansion runs until the next pair starts.
_LEGEND_PAIR = re.compile(
    r"(?:^|(?<=\s)|(?<=[,;]))([A-Z][A-Za-z0-9&+]{0,9})\s*[-–—:=]\s+(.+?)(?=\s*[,;]?\s+[A-Z][A-Za-z0-9&+]{0,9}\s*[-–—:=]\s+|\s*$)"
)


def _classify(code: str, value: str, hint: str | None) -> str:
    if hint in ("faculty", "subject"):
        return hint
    return "faculty" if _HONORIFIC.match(value.strip()) else "subject"


# One "ABBR: Expansion" (or "ABBR - Expansion") per line inside a single cell.
_CELL_PAIR = re.compile(r"^\s*(?:\([A-Z]\)\s*)?([A-Za-z][A-Za-z0-9&+.\- ]{0,14}?)\s*(?::|\s[-–—=]\s)\s*(\S.*)$")
# "AI&SC Artificial Intelligence & Soft Computing" — capitals code, no separator.
_CELL_PAIR_NOSEP = re.compile(r"^\s*([A-Z][A-Z0-9&+\-]{1,9})\s+([A-Z][a-z].{3,})$")
_INLINE_COLON_CODE = re.compile(r"(?:^|(?<=\s))([A-Z][A-Z0-9&+\-]{1,9})\s*:\s")
_CODE_ONLY = re.compile(r"[A-Za-z][A-Za-z0-9&.+\- ]{0,11}")


def _marker_kind(text: str) -> str | None:
    t = text.strip().lower()
    if not re.match(r"^(faculties|faculty|teachers?|staff|subjects?|courses?)\b", t):
        return None
    has_f = bool(re.search(r"\b(faculties|faculty|teachers?|staff)\b", t))
    has_s = bool(re.search(r"\b(subjects?|courses?)\b", t))
    if has_f and has_s:
        return "mixed"
    return "faculty" if has_f else "subject"


def _cell_pairs(text: str) -> list[tuple[str, str]]:
    out: list[list[str]] = []
    for line in (text or "").splitlines():
        if not line.strip() or _marker_kind(line) and len(line) < 40:
            continue
        if re.search(r"\d{1,2}[:.]\d{2}", line):
            continue
        # Several "ABBR: Name" pairs flowed onto one line (merged legend cell).
        starts = [m.start(1) for m in _INLINE_COLON_CODE.finditer(line)]
        if len(starts) > 1:
            for a, b in zip(starts, starts[1:] + [len(line)]):
                code, _, value = line[a:b].partition(":")
                out.append([code.strip(), value.strip()])
            continue
        colon = line.find(":")
        if 0 < colon <= 16 and re.match(r"^\s*(?:\([A-Z]\)\s*)?[A-Za-z]", line):
            code = re.sub(r"^\s*\([A-Z]\)\s*", "", line[:colon]).strip()
            out.append([code, line[colon + 1:].strip()])
            continue
        m = _CELL_PAIR.match(line) or _CELL_PAIR_NOSEP.match(line)
        if m:
            out.append([m.group(1).strip(), m.group(2).strip()])
        elif out:
            out[-1][1] += " " + line.strip()   # wrapped expansion
    return [(a, b) for a, b in out]


def _legend_table_pairs(legend_rows: list[list[str]]):
    """Yields (hint, code, expansion) from legend table rows.

    A marker row ("Faculties:" | | "Subjects:") assigns a hint to the columns from each marker up
    to the next one. Pairs are either one cell "ABBR: Name" or two adjacent cells "ABBR" | "Name".
    """
    col_hint: dict[int, str | None] = {}
    for row in legend_rows:
        cells = [(i, (c or "").strip()) for i, c in enumerate(row) if c and c.strip()]
        if not cells:
            continue
        kinds = [(i, _marker_kind(t)) for i, t in cells if len(t) < 40]
        if kinds and all(k for _, k in kinds) and len(kinds) == len(cells):
            col_hint = {}
            marks = sorted(kinds)
            for n, (i, k) in enumerate(marks):
                stop = marks[n + 1][0] if n + 1 < len(marks) else max(len(row), i + 1) + 64
                for j in range(i, stop):
                    col_hint[j] = None if k == "mixed" else k
            continue
        j = 0
        while j < len(cells):
            i, t = cells[j]
            hint = col_hint.get(i)
            own = _marker_kind(t.splitlines()[0])
            if own:  # a merged cell carrying its own "Faculties: Subjects:" heading
                hint = None if own == "mixed" else own
            pairs = _cell_pairs(t)
            if pairs:
                for a, b in pairs:
                    yield hint, a, b
                j += 1
                continue
            if j + 1 < len(cells) and _CODE_ONLY.fullmatch(t) and len(cells[j + 1][1]) > len(t):
                yield hint, t, cells[j + 1][1]
                j += 2
                continue
            j += 1


def parse_legend(context_text: str, legend_rows: list[list[str]]) -> dict[str, dict[str, str]]:
    """Builds {'faculty': {ABBR: name}, 'subject': {ABBR: name}} from page legends.

    Only explicit abbreviation → expansion pairs found on the page are used; nothing is invented.
    """
    faculty: dict[str, str] = {}
    subject: dict[str, str] = {}
    hint: str | None = None

    def put(code: str, value: str, h: str | None) -> None:
        code = code.strip().rstrip(".").upper()
        value = re.sub(r"\s+", " ", value).strip()
        if not code or not value or len(value) < 2 or code == value.upper():
            return
        kind = _classify(code, value, h)
        (faculty if kind == "faculty" else subject).setdefault(code, value)

    for kind, code, value in _legend_table_pairs(legend_rows):
        put(code, value, kind)
    if faculty or subject:
        # A ruled legend was found; free page text would only re-read it with less structure.
        return {"faculty": faculty, "subject": subject}

    hint = None
    for line in (context_text or "").splitlines():
        low = line.lower()
        if re.search(r"\b(faculty|teacher)s?\b", low) and len(line) < 40:
            hint = "faculty"
            continue
        if re.search(r"\b(subject|course)s?\b", low) and len(line) < 40:
            hint = "subject"
            continue
        if re.search(r"\d{1,2}[:.]\d{2}", line):
            continue
        for m in _LEGEND_PAIR.finditer(line):
            put(m.group(1), m.group(2), hint)
    return {"faculty": faculty, "subject": subject}
