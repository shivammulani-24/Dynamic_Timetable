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
    r"^(?:(?:room|rm|r|lab|hall)\s*[-.:]?\s*)?\d{2,4}(?:\s*[-/]?\s*[A-Za-z0-9]{1,3})?(?:\s*&\s*[A-Za-z0-9]{1,3})*(?:\s*\(?old\)?)?$"
    r"|^(?:seminar\s*hall|auditorium|online|drawing\s*hall|workshop|conference\s*room)(?:\s*\d+)?$", re.I)
FACULTY_SHAPE = re.compile(r"^[A-Z]{2,5}(?:\s*[,+&]\s*[A-Z]{2,5})*$")
SUBGROUP_RE = re.compile(r"\b(?:batch\s*[-:]?\s*)?([A-H])\s?-?\s?([1-9])\b", re.I)
BATCH_NUM_RE = re.compile(r"\b(batch\s*[-:]?\s*\d{1,2})\b", re.I)
LAB_WORDS = re.compile(r"\b(lab|laboratory|practical|tut|tutorial)\b", re.I)
# A whole token naming a group of students rather than a course/faculty/room:
# "Batch 2", "Batch D", "S.N. 1 to 60", "S.N.61onwards" (roll-number ranges).
GROUP_TOKEN_RE = re.compile(
    r"^(?:batch\s*[-:]?\s*(?:\d{1,2}|[A-H])|s\.?\s*n\.?\s*\d+\s*(?:(?:to|-)\s*\d+|onwards?))$", re.I)
# Labels that the source uses for parallel options of which a student attends one
# (electives, multidisciplinary minors, honours). Overlaps between such options are expected.
OPTION_RE = re.compile(
    r"^(?:open\s+elective|program(?:me)?\s+elective|professional\s+elective|elective|OE|PE|MDM|minor|honou?rs)\b", re.I)
EMPTY_PARENS = re.compile(r"\(\s*\)")
COURSE_ROOM_RE = re.compile(r"^([A-Za-z][^()]*?)\s*\((\d{2,4}[^()]*)\)$")
NOTE_RE = re.compile(r"\s*\([A-Za-z][^()]*\)$")


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
    category: str | None = None          # e.g. "Open Elective" heading line above the item
    details_blank: bool = False          # "LLC ()": the source deliberately gives no faculty/room
    room_label: str | None = None
    explicit_time: TimeLabel | None = None
    unparsed: list[str] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)

    def warn(self, severity: str, code: str, message: str) -> None:
        self.messages.append({"severity": severity, "code": code, "message": message})


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip(" -–,;")


def _split_chunks(text: str) -> list[tuple[str, str | None]]:
    """Splits a cell into (item_text, category) chunks.

    A line without '/' that is directly followed by an item line and reads like a heading
    ("Open Elective") labels the items below it; a line ending in "()" ("MDM Lab()") is an item of
    its own with its details left blank in the source.
    """
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    # Re-join wrapped components: "DS Lab A1/AVN/" + "604"  or  "DS Lab A1" + "/AVN/604"
    joined: list[str] = []
    for ln in lines:
        first = ln.split("/")[0].strip()
        if joined and (joined[-1].endswith("/") or ln.startswith("/")):
            joined[-1] = joined[-1] + ln
        elif joined and "/" in ln and re.fullmatch(r"\d{1,2}", first) and re.search(r"\bbatch\s*$", joined[-1], re.I):
            joined[-1] += " " + ln                       # "…/AT/Batch" + "1/505"
        elif joined and "/" in ln and GROUP_TOKEN_RE.match(first):
            joined[-1] += "/" + ln                       # "PE IV- DMBI Lab /NR" + "Batch D /703-A"
        elif joined and "/" in ln and SUBGROUP_RE.fullmatch(first) and "/" not in joined[-1]:
            joined[-1] += " " + ln                       # "Data Sci.Lab" + "D4/ARN/GY/603-3"
        else:
            joined.append(ln)
    slash_lines = [ln for ln in joined if "/" in ln]
    if len(slash_lines) >= 2 or (slash_lines and any(OPTION_RE.match(ln) and "/" not in ln for ln in joined)):
        chunks: list[list] = []
        pending: list[str] = []
        category: str | None = None
        timed_upto = 0   # chunks before this index already received a "(…time…)" line
        for n, ln in enumerate(joined):
            nxt = joined[n + 1] if n + 1 < len(joined) else ""
            if ln.startswith("(") and "/" not in ln and parse_inline_range(ln) and len(chunks) > timed_upto and not pending:
                # "(02:15 PM-03:15 PM)" on its own line times every item listed since the previous time line
                for ch in chunks[timed_upto:]:
                    ch[0] += " " + ln
                timed_upto = len(chunks)
                continue
            if "/" in ln:
                chunks.append([" ".join(pending + [ln]), category])
                pending = []
            elif EMPTY_PARENS.search(ln):
                chunks.append([ln, category])
            elif "/" in nxt and not ln.startswith("(") and OPTION_RE.match(ln):
                category = _clean(ln)
            elif chunks and not pending:
                # continuation of the previous entry (room or elective name on its own line)
                chunks[-1][0] += (" " if ln.startswith("(") else " / ") + ln
            else:
                pending.append(ln)
        if pending:
            chunks.append([" ".join(pending), category])
        return [(c, cat) for c, cat in chunks]
    if not slash_lines and len(joined) > 1:
        # Stacked lab rows without slashes: each line names its own sub-group → separate entries
        groups = [SUBGROUP_RE.search(ln) for ln in joined]
        if all(groups) and len({g.group(0).upper() for g in groups if g}) == len(joined):
            return [(ln, None) for ln in joined]
        return [(" / ".join(joined), None)]
    return [(" ".join(joined), None)] if joined else []


def _match_legend(token: str, table: dict[str, str]) -> tuple[str, str] | None:
    key = token.strip().rstrip(".").upper()
    if key in table:
        return key, table[key]
    # Same letters, different punctuation/spacing only ("AISC" vs legend "AI&SC").
    compact = re.sub(r"[^A-Z0-9]", "", key)
    if len(compact) >= 3:
        same = [k for k in table if re.sub(r"[^A-Z0-9]", "", k) == compact]
        if len(same) == 1:
            return same[0], table[same[0]]
    return None


def _norm_words(s: str) -> str:
    return " ".join(re.findall(r"[A-Z0-9&+]+", (s or "").upper()))


def _code_within(label: str, table: dict[str, str]) -> tuple[str, str] | None:
    """Exactly one legend code appearing as whole word(s) inside a longer label
    ("PE III-TSDA -A" → TSDA). Several or none → no match (never guessed)."""
    words = f" {_norm_words(label)} "
    tokens = set(words.split())
    hits = {code: name for code, name in table.items()
            if len(_norm_words(code)) >= 2 and (f" {_norm_words(code)} " in words
                                               or (len(c := _norm_words(code).replace(" ", "")) >= 3 and c in tokens))}
    return next(iter(hits.items())) if len(hits) == 1 else None


class _Legend:
    """This page's legend first; the same document's other pages as a labelled fallback."""

    def __init__(self, legend: dict[str, dict[str, str]]):
        self.page = {"faculty": legend.get("faculty", {}), "subject": legend.get("subject", {})}
        self.doc = {"faculty": legend.get("doc_faculty", {}), "subject": legend.get("doc_subject", {})}

    def has(self, kind: str) -> bool:
        return bool(self.page[kind] or self.doc[kind])

    def find(self, token: str, kind: str, item: "ParsedItem") -> tuple[str, str] | None:
        hit = _match_legend(token, self.page[kind])
        if hit:
            return hit
        hit = _match_legend(token, self.doc[kind])
        if hit:
            item.warn("INFO", "LEGEND_FROM_OTHER_PAGE",
                      f"'{hit[0]}' is not in this page's legend; expanded from another page of the same document.")
        return hit


def parse_cell(text: str, legend: dict[str, dict[str, str]], known_rooms: set[str] | None = None) -> list[ParsedItem]:
    text = (text or "").strip()
    if not text:
        return []
    known_rooms = known_rooms or set()
    lg = _Legend(legend)

    one_line = _clean(text.replace("\n", " "))
    if BREAK_RE.search(one_line) and not re.search(r"/", one_line):
        return [ParsedItem(kind="BREAK", raw=text, course_label=_clean(BREAK_RE.search(one_line).group(0)).upper())]
    if ACTIVITY_RE.search(one_line) and "/" not in one_line:
        return [ParsedItem(kind="ACTIVITY", raw=text, course_label=one_line[:200])]

    items: list[ParsedItem] = []
    for chunk, category in _split_chunks(text):
        item = ParsedItem(raw=chunk, category=category)
        explicit = parse_inline_range(chunk)
        if explicit:
            item.explicit_time = explicit
            chunk = re.sub(r"\([^)]*\d[^)]*\)", " ", chunk)
        if EMPTY_PARENS.search(chunk) and "/" not in chunk:
            item.details_blank = True
        chunk = EMPTY_PARENS.sub(" ", chunk)
        tokens = [_clean(t) for t in re.split(r"/|\n", chunk)]
        tokens = [t for t in tokens if t]
        course_parts: list[str] = []
        if tokens:
            cr = COURSE_ROOM_RE.match(tokens[0])
            if cr and ROOM_RE.match(cr.group(2)):          # "HSS(609)" → course HSS, room 609
                tokens[0:1] = [cr.group(1).strip(), cr.group(2)]
                item.details_blank = len(tokens) == 2          # the source names no faculty
        for idx, tok in enumerate(tokens):
            norm_room = re.sub(r"[^0-9a-z]", "", tok.lower())
            note = NOTE_RE.search(tok) if idx > 0 else None
            if note and FACULTY_SHAPE.match(tok[: note.start()].strip()):
                tok = tok[: note.start()].strip()             # "AT(Math)" → AT; note stays in raw text
            if idx > 0 and GROUP_TOKEN_RE.match(tok):
                if item.group_label:
                    item.unparsed.append(tok)
                else:
                    item.group_label = re.sub(r"\s+", " ", tok).strip()
                continue
            fac = lg.find(tok, "faculty", item) if idx > 0 or len(tokens) == 1 else None
            if fac and not (idx == 0 and _match_legend(tok, lg.page["subject"])):
                item.staff_labels.append(fac[0])
                item.staff_names.append(fac[1])
                continue
            if idx > 0 and FACULTY_SHAPE.match(tok) and not _match_legend(tok, lg.page["subject"]):
                for code in re.split(r"\s*[,+&]\s*", tok):
                    item.staff_labels.append(code)
                    hit = lg.find(code, "faculty", item)
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
        if bn and not item.group_label:
            item.group_label = re.sub(r"\s+", "", bn.group(1)).title()
            course = _clean(course[: bn.start()] + " " + course[bn.end():])
        item.course_label = course or None
        if course:
            hit = lg.find(course, "subject", item)
            if not hit:
                base = _clean(LAB_WORDS.sub("", course))
                hit_base = lg.find(base, "subject", item) if base and base != course else None
                if hit_base:
                    item.messages.append({"severity": "INFO", "code": "COURSE_CODE_BASE", "details": {"code": hit_base[0]},
                                          "message": f"'{course}' is a lab/tutorial of subject '{hit_base[0]}'."})
                    lab = LAB_WORDS.search(course)
                    item.course_name = hit_base[1] + (f" ({lab.group(0).title()})" if lab else "")
                else:
                    inner = _code_within(course, lg.page["subject"]) or _code_within(course, lg.doc["subject"])
                    if inner:
                        item.course_name = inner[1]
                        item.messages.append({
                            "severity": "INFO", "code": "COURSE_CODE_WITHIN_LABEL", "details": {"code": inner[0]},
                            "message": f"Subject '{inner[0]}' recognised inside the label '{course}'; label kept as written."})
            else:
                item.course_name = hit[1]
        if item.category:
            item.course_name = f"{item.course_name} ({item.category})" if item.course_name else item.category
        if item.category or (course and OPTION_RE.match(course)):
            item.warn("INFO", "PARALLEL_OPTION",
                      "Listed as an elective/minor option; parallel options at the same time are expected.")
        if not item.course_label:
            item.warn("WARNING", "COURSE_MISSING", "No course/subject label could be identified in this cell.")
        elif not item.course_name and lg.has("subject"):
            # The code is shown exactly as printed; it is simply not expanded.
            item.warn("INFO", "COURSE_ABBREVIATION_UNKNOWN",
                      f"'{item.course_label}' is not in this document's subject legend; shown as written.")
        if item.details_blank:
            item.warn("INFO", "DETAILS_NOT_GIVEN",
                      "The source gives only the course" + (" and room" if item.room_label else "")
                      + " for this slot; no faculty is assigned.")
        elif not item.staff_labels:
            item.warn("WARNING", "FACULTY_MISSING", "No faculty abbreviation found in this cell.")
        else:
            unknown = [x for x in item.staff_labels if x not in lg.page["faculty"] and x not in lg.doc["faculty"]]
            if unknown and lg.has("faculty"):
                item.warn("INFO", "FACULTY_ABBREVIATION_UNKNOWN",
                          f"Faculty code(s) {', '.join(unknown)} not found in this document's legend; shown as written.")
        if not item.room_label and not item.details_blank:
            item.warn("WARNING", "ROOM_MISSING", "No room label found in this cell.")
        if item.unparsed:
            item.warn("WARNING", "UNPARSED_TOKENS", f"Unrecognised text kept for review: {' / '.join(item.unparsed)}")
        items.append(item)
    return items
