"""Timetable cell grammar (PDF spec §4.3).

The source uses varied patterns: SUBJECT/FACULTY/ROOM, stacked labs with sub-group suffixes,
electives, multi-line cells and missing components. We therefore do *not* rely on one strict
slash-split rule: tokens are classified by shape, by the page legend and by known room codes.
Unclassifiable tokens are kept in the raw text and reported — never invented or dropped silently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.extraction.timeparse import TimeLabel, parse_inline_range

BREAK_RE = re.compile(r"\b(short\s*break|long\s*break|lunch(\s*break)?|recess|tea\s*break|break)\b", re.I)
ACTIVITY_RE = re.compile(
    r"\b(student\s*activity|activity\s*slot|faculty\s*quality\s*circle|fqc|library|mentoring|mentor\s*meet|"
    r"sports|club\s*activity|seminar\s*slot|self\s*study|project\s*slot|counsel+ing)\b", re.I)
ROOM_RE = re.compile(
    r"^(?:(?:room|rm|r|lab|hall)\s*[-.:]?\s*)?\d{2,4}(?:\s*[-/]?\s*[A-Za-z0-9]{1,3})?(?:\s*\(?old\)?)?$"
    r"|^(?:seminar\s*hall|auditorium|online|drawing\s*hall|workshop|conference\s*room)(?:\s*\d+)?$", re.I)
FACULTY_SHAPE = re.compile(r"^[A-Z]{2,5}(?:\s*[,+&]\s*[A-Z]{2,5})*$")
SUBGROUP_RE = re.compile(r"\b(?:batch\s*[-:]?\s*)?([A-H])\s?-?\s?([1-9])\b", re.I)
BATCH_NUM_RE = re.compile(r"\b(batch\s*[-:]?\s*\d{1,2})\b", re.I)
LAB_WORDS = re.compile(r"\b(lab|laboratory|practical|tut|tutorial)\b", re.I)


@dataclass
class ParsedItem:
    kind: str = "CLASS"
    raw: str = ""
    course_label: str | None = None
    course_name: str | None = None
    staff_labels: list[str] = field(default_factory=list)
    staff_names: list[str] = field(default_factory=list)
    subgroup: str | None = None          # e.g. "A1"
    group_label: str | None = None       # e.g. "Batch1" for electives
    room_label: str | None = None
    explicit_time: TimeLabel | None = None
    unparsed: list[str] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)

    def warn(self, severity: str, code: str, message: str) -> None:
        self.messages.append({"severity": severity, "code": code, "message": message})


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip(" -–,;")


def _split_chunks(text: str) -> list[str]:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    # Re-join wrapped components: "DS Lab A1/AVN/" + "604"  or  "DS Lab A1" + "/AVN/604"
    joined: list[str] = []
    for ln in lines:
        if joined and (joined[-1].endswith("/") or ln.startswith("/")):
            joined[-1] = joined[-1] + ln
        else:
            joined.append(ln)
    slash_lines = [ln for ln in joined if "/" in ln]
    if len(slash_lines) >= 2:
        chunks: list[str] = []
        pending: list[str] = []
        for ln in joined:
            if "/" in ln:
                chunks.append(" ".join(pending + [ln]))
                pending = []
            elif chunks:
                # continuation of the previous entry (room or elective name on its own line)
                chunks[-1] += (" " if ln.startswith("(") else " / ") + ln
            else:
                pending.append(ln)
        if pending:
            chunks.append(" ".join(pending))
        return chunks
    if not slash_lines and len(joined) > 1:
        # Stacked lab rows without slashes: each line names its own sub-group → separate entries
        groups = [SUBGROUP_RE.search(ln) for ln in joined]
        if all(groups) and len({g.group(0).upper() for g in groups if g}) == len(joined):
            return joined
        return [" / ".join(joined)]
    return [" ".join(joined)] if joined else []


def _match_legend(token: str, table: dict[str, str]) -> tuple[str, str] | None:
    key = token.strip().rstrip(".").upper()
    if key in table:
        return key, table[key]
    return None


def parse_cell(text: str, legend: dict[str, dict[str, str]], known_rooms: set[str] | None = None) -> list[ParsedItem]:
    text = (text or "").strip()
    if not text:
        return []
    known_rooms = known_rooms or set()
    faculty_legend = legend.get("faculty", {})
    subject_legend = legend.get("subject", {})

    one_line = _clean(text.replace("\n", " "))
    if BREAK_RE.search(one_line) and not re.search(r"/", one_line):
        return [ParsedItem(kind="BREAK", raw=text, course_label=_clean(BREAK_RE.search(one_line).group(0)).upper())]
    if ACTIVITY_RE.search(one_line) and "/" not in one_line:
        return [ParsedItem(kind="ACTIVITY", raw=text, course_label=one_line[:200])]

    items: list[ParsedItem] = []
    for chunk in _split_chunks(text):
        item = ParsedItem(raw=chunk)
        explicit = parse_inline_range(chunk)
        if explicit:
            item.explicit_time = explicit
            chunk = re.sub(r"\([^)]*\d[^)]*\)", " ", chunk)
        tokens = [_clean(t) for t in re.split(r"/|\n", chunk)]
        tokens = [t for t in tokens if t]
        course_parts: list[str] = []
        for idx, tok in enumerate(tokens):
            norm_room = re.sub(r"[^0-9a-z]", "", tok.lower())
            fac = _match_legend(tok, faculty_legend)
            if fac:
                item.staff_labels.append(fac[0])
                item.staff_names.append(fac[1])
                continue
            if idx > 0 and FACULTY_SHAPE.match(tok) and not _match_legend(tok, subject_legend):
                for code in re.split(r"\s*[,+&]\s*", tok):
                    item.staff_labels.append(code)
                    hit = _match_legend(code, faculty_legend)
                    if hit:
                        item.staff_names.append(hit[1])
                continue
            if ROOM_RE.match(tok) or norm_room in known_rooms:
                if item.room_label:
                    item.unparsed.append(tok)
                else:
                    item.room_label = tok
                continue
            if idx == 0 or not item.staff_labels:
                course_parts.append(tok)
            else:
                item.unparsed.append(tok)

        course = _clean(" ".join(course_parts))
        sg = SUBGROUP_RE.search(course)
        if sg:
            item.subgroup = (sg.group(1) + sg.group(2)).upper()
            course = _clean(course[: sg.start()] + " " + course[sg.end():])
        bn = BATCH_NUM_RE.search(course)
        if bn:
            item.group_label = re.sub(r"\s+", "", bn.group(1)).title()
            course = _clean(course[: bn.start()] + " " + course[bn.end():])
        item.course_label = course or None
        if course:
            hit = _match_legend(course, subject_legend)
            if not hit:
                base = _clean(LAB_WORDS.sub("", course))
                hit_base = _match_legend(base, subject_legend) if base and base != course else None
                if hit_base:
                    lab = LAB_WORDS.search(course)
                    item.course_name = hit_base[1] + (f" ({lab.group(0).title()})" if lab else "")
            else:
                item.course_name = hit[1]
        if not item.course_label:
            item.warn("WARNING", "COURSE_MISSING", "No course/subject label could be identified in this cell.")
        elif not item.course_name and subject_legend:
            item.warn("WARNING", "COURSE_ABBREVIATION_UNKNOWN",
                      f"'{item.course_label}' is not in this page's subject legend; kept as written.")
        if not item.staff_labels:
            item.warn("WARNING", "FACULTY_MISSING", "No faculty abbreviation found in this cell.")
        else:
            unknown = [s for s in item.staff_labels if s not in faculty_legend]
            if unknown and faculty_legend:
                item.warn("WARNING", "FACULTY_ABBREVIATION_UNKNOWN",
                          f"Faculty code(s) {', '.join(unknown)} not found in this page's legend.")
        if not item.room_label:
            item.warn("WARNING", "ROOM_MISSING", "No room label found in this cell.")
        if item.unparsed:
            item.warn("WARNING", "UNPARSED_TOKENS", f"Unrecognised text kept for review: {' / '.join(item.unparsed)}")
        items.append(item)
    return items
