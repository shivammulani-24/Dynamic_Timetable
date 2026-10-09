"""Day and time-label parsing for extracted timetables.

Rules (PDF spec §4.2):
* Preserve the raw label; normalise to 24-hour only when unambiguous.
* Explicit a.m./p.m. markers are honoured *only if* the literal reading is a plausible same-day
  interval that fits the row sequence. Otherwise the label is flagged inconsistent; a candidate
  derived from the row sequence may be kept but the time is marked UNCERTAIN (never silently fixed).
* Labels without markers are resolved from the row sequence (rows must increase, within the
  plausible teaching window). If more than one reading fits, the time stays ambiguous.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from datetime import date, time

WINDOW_START = 7 * 60    # 07:00 — plausible teaching window used only to *reject* readings
WINDOW_END = 21 * 60     # 21:00

DAYS = {
    "monday": 1, "mon": 1, "tuesday": 2, "tue": 2, "tues": 2, "wednesday": 3, "wed": 3,
    "thursday": 4, "thu": 4, "thur": 4, "thurs": 4, "friday": 5, "fri": 5,
    "saturday": 6, "sat": 6, "sunday": 7, "sun": 7,
}
BREAK_WORDS_RE = re.compile(r"\b(break|lunch|recess)\b", re.I)
DAY_NAMES = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}

_T = r"(\d{1,2})(?:\s*[:.]\s*(\d{2}))?\s*(a\.?\s*m\.?|p\.?\s*m\.?|noon)?"
_RANGE = re.compile(_T + r"\s*(?:-|–|—|to|till|until)\s*" + _T, re.I)
_SINGLE = re.compile(r"\b" + _T + r"\b", re.I)


def parse_day(text: str) -> int | None:
    t = re.sub(r"[^a-z]", "", (text or "").lower())
    if t in DAYS:
        return DAYS[t]
    for k in sorted(DAYS, key=len, reverse=True):
        if len(k) > 3 and t.startswith(k):
            return DAYS[k]
    return None


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def parse_date_text(text: str) -> tuple[date | None, bool]:
    """Returns (date, ambiguous). Accepts ISO, '10 August 2026', 'August 10, 2026', and dd/mm/yyyy
    only when day > 12 (otherwise day/month order is ambiguous and we refuse to guess)."""
    s = (text or "").strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3])), False
        except ValueError:
            return None, False
    m = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", s)
    if m and m[2][:3].lower() in _MONTHS:
        try:
            return date(int(m[3]), _MONTHS[m[2][:3].lower()], int(m[1])), False
        except ValueError:
            return None, False
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", s)
    if m and m[1][:3].lower() in _MONTHS:
        try:
            return date(int(m[3]), _MONTHS[m[1][:3].lower()], int(m[2])), False
        except ValueError:
            return None, False
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b", s)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if a > 12 and b <= 12:
            try:
                return date(y, b, a), False
            except ValueError:
                return None, False
        return None, True
    return None, False


@dataclass
class TimePoint:
    hour: int
    minute: int
    marker: str | None  # "am" | "pm" | "noon" | None

    def candidates(self) -> list[int]:
        """Minutes-since-midnight readings consistent with the *literal* label."""
        h, m = self.hour, self.minute
        if h > 23 or m > 59:
            return []
        if self.marker == "noon":
            return [12 * 60 + m] if h == 12 else []
        if self.marker == "am":
            if h > 12:
                return []
            return [(0 if h == 12 else h) * 60 + m]
        if self.marker == "pm":
            if h > 12:
                return []
            return [(12 if h == 12 else h + 12) * 60 + m]
        if h >= 13 or h == 0:
            return [h * 60 + m]
        if h == 12:
            return [12 * 60 + m]
        return [h * 60 + m, (h + 12) * 60 + m]

    def free_candidates(self) -> list[int]:
        """Readings ignoring the marker (used only to *suggest* a fix for an inconsistent label)."""
        return TimePoint(self.hour, self.minute, None).candidates()


@dataclass
class TimeLabel:
    raw: str
    start: TimePoint | None
    end: TimePoint | None

    @property
    def has_markers(self) -> bool:
        return bool((self.start and self.start.marker) or (self.end and self.end.marker))


def _marker(s: str | None) -> str | None:
    if not s:
        return None
    s = s.lower().replace(".", "").replace(" ", "")
    return "noon" if s == "noon" else ("am" if s.startswith("a") else "pm")


def parse_time_label(raw: str) -> TimeLabel | None:
    if not raw:
        return None
    text = raw.replace("\n", " ")
    m = _RANGE.search(text)
    if not m:
        return None
    h1, m1, k1, h2, m2, k2 = m.groups()
    # "9-10" without minutes is accepted only when it is clearly a range of hours
    start = TimePoint(int(h1), int(m1 or 0), _marker(k1))
    end = TimePoint(int(h2), int(m2 or 0), _marker(k2))
    # "10 to 11 a.m." - a trailing marker applies to both ends when only the end has one
    if start.marker is None and end.marker in ("am", "pm") and start.hour <= end.hour and end.hour != 12:
        start.marker = end.marker
    return TimeLabel(raw.strip(), start, end)


def _plausible(s: int, e: int) -> bool:
    return WINDOW_START <= s < e <= WINDOW_END and (e - s) <= 6 * 60


@dataclass
class ResolvedTime:
    start: time | None
    end: time | None
    uncertain: bool
    issues: list[dict] = field(default_factory=list)


def _t(minutes: int) -> time:
    return time(minutes // 60, minutes % 60)


def resolve_sequence(labels: list[TimeLabel | None]) -> list[ResolvedTime]:
    """Resolve a top-to-bottom sequence of row labels.

    Every label gets the readings allowed by its *literal* text. We search for assignments where
    each row is a plausible interval and rows do not go backwards. Rows that have exactly one
    reading across all valid assignments are certain. Labels whose literal reading cannot fit
    are flagged TIME_LABEL_INCONSISTENT; if the sequence implies a unique alternative it is kept
    as an UNCERTAIN suggestion for review.
    """
    n = len(labels)
    options: list[list[tuple[int, int, bool]]] = []  # (start, end, literal?)
    for lab in labels:
        opts: list[tuple[int, int, bool]] = []
        if lab and lab.start and lab.end:
            for s, e in itertools.product(lab.start.candidates(), lab.end.candidates()):
                if _plausible(s, e):
                    opts.append((s, e, True))
            if not opts:
                for s, e in itertools.product(lab.start.free_candidates(), lab.end.free_candidates()):
                    if _plausible(s, e):
                        opts.append((s, e, False))
        options.append(opts)

    # Enumerate consistent assignments (rows are few: typically <= 12, options <= 4 each).
    solutions: list[list[tuple[int, int, bool] | None]] = []

    def walk(i: int, prev_end: int, acc: list):
        if len(solutions) > 64:
            return
        if i == n:
            solutions.append(list(acc))
            return
        if not options[i]:
            acc.append(None)
            walk(i + 1, prev_end, acc)
            acc.pop()
            return
        for opt in options[i]:
            if opt[0] >= prev_end:
                acc.append(opt)
                walk(i + 1, opt[1], acc)
                acc.pop()

    walk(0, 0, [])
    out: list[ResolvedTime] = []
    for i, lab in enumerate(labels):
        if lab is None or not (lab.start and lab.end):
            out.append(ResolvedTime(None, None, True, [{"severity": "CRITICAL", "code": "TIME_LABEL_MISSING",
                                                        "message": "No readable time label for this row."}]))
            continue
        readings = {tuple(s[i][:2]) for s in solutions if s[i] is not None}
        literal = {s[i][2] for s in solutions if s[i] is not None}
        if not options[i]:
            out.append(ResolvedTime(None, None, True, [{"severity": "CRITICAL", "code": "TIME_LABEL_INVALID",
                                                        "message": f"Time label '{lab.raw}' is not a valid same-day interval."}]))
        elif len(readings) == 1:
            s, e = next(iter(readings))
            if literal == {False}:
                out.append(ResolvedTime(_t(s), _t(e), True, [{
                    "severity": "CRITICAL", "code": "TIME_LABEL_INCONSISTENT",
                    "message": f"Time label '{lab.raw}' contradicts its a.m./p.m. markers or the row sequence; "
                               f"the sequence suggests {_t(s):%H:%M}–{_t(e):%H:%M}. Needs review.",
                }]))
            else:
                out.append(ResolvedTime(_t(s), _t(e), False, []))
        elif not readings:
            out.append(ResolvedTime(None, None, True, [{"severity": "CRITICAL", "code": "TIME_SEQUENCE_CONFLICT",
                                                        "message": f"Time label '{lab.raw}' does not fit the row sequence."}]))
        else:
            opts = ", ".join(f"{_t(s):%H:%M}–{_t(e):%H:%M}" for s, e in sorted(readings))
            out.append(ResolvedTime(None, None, True, [{"severity": "CRITICAL", "code": "TIME_AMBIGUOUS_AMPM",
                                                        "message": f"Time label '{lab.raw}' is ambiguous ({opts})."}]))
    return out


def parse_inline_range(text: str) -> TimeLabel | None:
    """Explicit time range written inside a cell, e.g. 'DBMS Lab (1.15-3.15)'."""
    m = re.search(r"\(([^)]*\d[^)]*)\)", text or "")
    if not m:
        return None
    return parse_time_label(m.group(1))
