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

    for row in legend_rows:
        cells = [c.strip() for c in row if c and c.strip()]
        if not cells:
            continue
        joined = " ".join(cells).lower()
        if any(w in joined for w in ("faculty", "teacher", "staff name", "professor")) and len(cells) <= 3 and not _HONORIFIC.match(cells[-1]):
            hint = "faculty"
            continue
        if any(w in joined for w in ("subject", "course")) and len(cells) <= 3 and len(cells[0]) > 6:
            hint = "subject"
            continue
        # A legend table row may hold several abbreviation/name pairs side by side.
        for i in range(0, len(cells) - 1, 2):
            a, b = cells[i], cells[i + 1]
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9&.+\- ]{0,11}", a) and len(b) > len(a):
                put(a, b, hint)

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
