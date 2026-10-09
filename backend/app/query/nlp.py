"""Deterministic natural-language interpretation for timetable queries.

This is a rule-based classifier (tokenisation, controlled synonyms, ordered patterns) — not a
trained machine-learning model. Its only output is a candidate intent name plus raw mentions;
the engine validates everything against the registry and the selected timetable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.extraction.timeparse import DAYS

WORD_NUM = {"ground": 0, "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
            "eighth": 8, "ninth": 9, "tenth": 10, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


@dataclass
class TimeMention:
    hour: int
    minute: int
    marker: str | None       # "am" | "pm" | None
    raw: str

    @property
    def ambiguous(self) -> bool:
        return self.marker is None and 1 <= self.hour <= 12 and not (self.hour == 12 and self.marker == "noon")

    def readings(self) -> list[tuple[int, int]]:
        h, m = self.hour, self.minute
        if self.marker == "am":
            return [(0 if h == 12 else h, m)]
        if self.marker in ("pm", "noon"):
            return [(12 if h == 12 else h + 12, m)]
        if h == 0 or h >= 13:
            return [(h, m)]
        return [(h, m), (12 if h == 12 else h + 12, m)] if h != 12 else [(12, m), (0, m)]


@dataclass
class Parsed:
    text: str
    norm: str
    today: date
    self_ref: bool = False
    now: bool = False
    dates: list[date] = field(default_factory=list)
    date_ambiguous_raw: str | None = None
    weekday: int | None = None
    weekday_next: bool = False
    week_ref: str | None = None            # "this" | "next"
    date_range: tuple[date, date] | None = None
    times: list[TimeMention] = field(default_factory=list)
    time_is_range: bool = False
    after: bool = False                     # "after <time>"
    after_lunch: bool = False
    professor: str | None = None
    room: str | None = None
    floor: int | None = None
    floor_raw: str | None = None
    batch: str | None = None
    course: str | None = None
    archive_modifier: bool = False
    detail_request: bool = False
    leftover: str = ""

    @property
    def date(self) -> date | None:
        return self.dates[0] if self.dates else None


def normalize(text: str) -> str:
    t = text.lower().replace("’", "'").replace("–", "-").replace("—", "-")
    t = re.sub(r"[?!,;]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_TIME = re.compile(
    r"(?<![\w./-])(?:(?P<noon>noon|midday)|(?P<h>\d{1,2})(?:[:.](?P<m>\d{2}))?\s*(?P<mk>a\.?\s?m\.?|p\.?\s?m\.?|o'?clock|hrs|hours)?)"
    r"(?![\w/-])"
)
_TIME_CONTEXT = re.compile(r"\b(at|by|from|between|after|before|till|until|to|and|around|@)\s*$")
_QUAL = re.compile(r"\b(?:in the )?(morning|afternoon|evening|night)\b")


def _extract_times(t: str) -> tuple[list[TimeMention], bool]:
    found: list[TimeMention] = []
    for m in _TIME.finditer(t):
        raw = m.group(0).strip()
        if m.group("noon"):
            found.append(TimeMention(12, 0, "noon", raw))
            continue
        h = int(m.group("h"))
        mins = int(m.group("m")) if m.group("m") else 0
        mk = (m.group("mk") or "").replace(".", "").replace(" ", "")
        before = t[: m.start()]
        # accept bare numbers only when they look like times (context word, minutes, or a marker)
        if not mk and not m.group("m") and not _TIME_CONTEXT.search(before):
            continue
        if h > 23 or mins > 59:
            continue
        if re.search(r"(room|rm|lab|floor|hall|batch|div|division)\s*$", before):
            continue
        # "o'clock"/"hrs" carry no a.m./p.m. information
        marker = "am" if mk.startswith("a") else ("pm" if mk.startswith("p") else None)
        found.append(TimeMention(h, mins, marker, raw))
    q = _QUAL.search(t)
    if q:
        for tm in found:
            if tm.marker is None and 1 <= tm.hour <= 12:
                tm.marker = "am" if q.group(1) == "morning" else "pm"
    is_range = len(found) >= 2 and bool(re.search(r"\b(between|from)\b.*\b(and|to|till|until)\b|\d\s*-\s*\d", t))
    if is_range and found[0].marker is None and found[1].marker in ("am", "pm"):
        # "10 to 12 pm": try the end's marker on the start; keep only if it yields start < end
        s_try = TimeMention(found[0].hour, found[0].minute, found[1].marker, found[0].raw)
        if s_try.readings()[0] < found[1].readings()[0]:
            found[0] = s_try
        else:
            alt = TimeMention(found[0].hour, found[0].minute, "am", found[0].raw)
            if found[1].marker == "pm" and alt.readings()[0] < found[1].readings()[0]:
                found[0] = alt
    return found, is_range


def _extract_dates(p: Parsed, t: str) -> None:
    today = p.today
    if re.search(r"\bday after tomorrow\b", t):
        p.dates.append(today + timedelta(days=2))
    elif re.search(r"\btomorrow\b|\btmrw\b|\btmr\b", t):
        p.dates.append(today + timedelta(days=1))
    elif re.search(r"\byesterday\b", t):
        p.dates.append(today - timedelta(days=1))
    elif re.search(r"\btoday\b|\btonight\b|\bthis (morning|afternoon|evening)\b", t):
        p.dates.append(today)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        try:
            p.dates.append(date(int(m[1]), int(m[2]), int(m[3])))
        except ValueError:
            p.date_ambiguous_raw = m.group(0)
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3,9})\b(?:\s+(\d{4}))?", t):
        mon = MONTHS.get(m[2][:3])
        if mon:
            _add_date(p, int(m[3]) if m[3] else today.year, mon, int(m[1]))
    for m in re.finditer(r"\b([a-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4}))?", t):
        mon = MONTHS.get(m[1][:3])
        if mon and m[1] not in DAYS:
            _add_date(p, int(m[3]) if m[3] else today.year, mon, int(m[2]))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        a, b = int(m[1]), int(m[2])
        y = int(m[3]) if m[3] else today.year
        y = y + 2000 if y < 100 else y
        if a > 12 >= b:
            _add_date(p, y, b, a)
        elif b > 12 >= a:
            _add_date(p, y, a, b)
        else:
            p.date_ambiguous_raw = m.group(0)  # day/month order unclear → ask
    wm = re.search(r"\b(?:(next|this|coming)\s+)?(monday|mon|tuesday|tue|tues|wednesday|wed|thursday|thu|thurs|friday|fri|saturday|sat|sunday|sun)(?:'s)?\b", t)
    if wm:
        p.weekday = DAYS[wm.group(2)]
        p.weekday_next = wm.group(1) in ("next", "coming")
    wk = re.search(r"\b(this|next|current|coming)\s+week\b|\bweekly\b|\bwhole week\b|\bfull week\b|\bweek's\b", t)
    if wk:
        p.week_ref = "next" if wk.group(1) in ("next", "coming") else "this"


def _add_date(p: Parsed, y: int, mo: int, d: int) -> None:
    try:
        p.dates.append(date(y, mo, d))
    except ValueError:
        p.date_ambiguous_raw = f"{d}/{mo}/{y}"


_PROF = re.compile(
    r"\b(?:prof(?:essor)?|dr|mr|mrs|ms|miss|sir|madam|ma'am|faculty|teacher)\.?\s+"
    r"(?P<name>[a-z][a-z.]*(?:\s+[a-z][a-z.]*){0,3}?)"
    r"(?='s\b|\s+(?:schedule|timetable|free|teach|teaches|teaching|take|takes|class|classes|lectures?|now|today|tomorrow|"
    r"on|at|this|next|in|scheduled|right|available|busy|located|sitting|be|is|do|does)\b|\s*$)"
)
_ROOM = re.compile(r"\b(?:room|rm|classroom|lab|hall|cabin)\s*(?:no\.?|number|#)?\s*(?P<room>[a-z]?-?\d{2,4}(?:\s*-\s*[a-z0-9]{1,3}|[a-z])?(?:\s+old)?)\b")
_BARE_ROOM = re.compile(r"\b(?P<room>[a-z]{1,2}-\d{2,4}[a-z]?)\b")
_FLOOR = re.compile(r"\b(?:(?P<w>ground|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|\d{1,2}(?:st|nd|rd|th)?)\s+floor"
                    r"|floor\s*(?:no\.?|number)?\s*(?P<n>\d{1,2}|ground))\b")
_BATCH = re.compile(r"\b(?:batch|division|div|class|section)\s+(?P<batch>[a-z]{1,4}(?:[- ]?[a-z])?(?:[- ]?\d)?)\b")
_SELF = re.compile(r"\b(i|i'm|im|me|my|mine|am i|do i|have i)\b")


def parse(text: str, today: date) -> Parsed:
    t = normalize(text)
    p = Parsed(text=text, norm=t, today=today)
    p.self_ref = bool(_SELF.search(t))
    p.now = bool(re.search(r"\b(now|right now|currently|current|at the moment|ongoing|going on|happening|this moment)\b", t))
    _extract_dates(p, t)
    p.times, p.time_is_range = _extract_times(t)
    p.after = bool(re.search(r"\b(after|post|later than|past)\s+(\d|noon)", t))
    p.after_lunch = bool(re.search(r"\b(after|post)[- ]?lunch\b", t))
    m = _PROF.search(t)
    if m:
        name = re.sub(r"\b(schedule|timetable)\b", "", m.group("name")).strip(" .")
        if name and name not in ("free", "now"):
            p.professor = name
    m = _ROOM.search(t) or _BARE_ROOM.search(t)
    if m:
        p.room = m.group("room").strip()
    m = _FLOOR.search(t)
    if m:
        raw = (m.group("w") or m.group("n") or "").strip()
        p.floor_raw = raw
        num = re.match(r"\d+", raw)
        p.floor = int(num.group(0)) if num else WORD_NUM.get(raw)
    m = _BATCH.search(t)
    if m and not re.match(r"(details|time|schedule|is|on|at|now)$", m.group("batch")):
        p.batch = m.group("batch").strip()
    p.archive_modifier = bool(re.search(r"\b(this|selected|current|that|the)\s+(archive|archived timetable|archived|old timetable|selected timetable)\b"
                                        r"|\barchived timetable\b|\bin (the|this) archive\b", t))
    p.detail_request = bool(re.search(r"\b(details?|more info|information about|tell me about|describe)\b", t))
    return p


# --------------------------------------------------------------------------- classification

_RULES: list[tuple[str, re.Pattern]] = [
    ("CROSS_DOMAIN_COMPARE", re.compile(
        r"\b(compare|comparison|difference|differences|diff|versus|vs|clash|overlap|both)\b.*\b(personal|private|my own)\b.*\b(college|institutional|official|institute)\b"
        r"|\b(compare|comparison|difference|differences|versus|vs|clash|overlap|both)\b.*\b(college|institutional|official)\b.*\b(personal|private)\b"
        r"|\b(personal|private)\b.*\band\b.*\b(college|institutional|official)\b.*\b(timetables?|schedules?)\b.*\b(compare|together|combined|merge)\b"
        r"|\b(merge|combine)\b.*\b(personal|private)\b.*\b(college|institutional|official)\b")),
    ("MAKE_TIMETABLE_PRIMARY", re.compile(r"\b(make|set|mark|use)\b.*\b(primary|default|main)\b|\b(primary|default)\b.*\b(make|set)\b")),
    ("SHOW_PRIMARY_TIMETABLE", re.compile(r"\b(which|what)\b.*\b(primary|default|active|official)\b.*\b(timetable|schedule)\b|\bprimary timetable\b|\bcurrent(ly)? (primary|default|active)\b")),
    ("LIST_TIMETABLE_ARCHIVES", re.compile(r"\b(archives?|old timetables?|previous timetables?|past timetables?|earlier timetables?|uploaded timetables?|my uploads|all (my )?timetables|list (my |the )?timetables)\b")),
    ("TIME_UNTIL_NEXT_CLASS", re.compile(r"\bhow (long|much time|many (minutes|hours|mins))\b.*\b(next|until|till|before)\b|\btime (left|remaining)? ?(until|till|before) (my |the )?next\b|\bwhen does (my |the )?next\b")),
]


def classify(p: Parsed, *, has_professor: bool, has_room: bool, has_batch: bool, has_course: bool, has_floor: bool) -> str | None:
    t = p.norm
    for name, rx in _RULES:
        if rx.search(t):
            return name
    free_word = re.search(r"\b(free|available|vacant|empty|unoccupied|not occupied|occupied|busy|in use|booked)\b", t)
    rooms_word = re.search(r"\b(rooms|classrooms|labs|halls|spaces)\b", t)

    if has_professor:
        if re.search(r"\bwhen\b.*\b(free|available)\b|\bfree (time|slots?|periods?|hours?)\b|\b(free|available) (slots?|periods?)\b", t):
            return "PROFESSOR_FREE_TIME"
        if free_word and p.times:
            return "CHECK_SCHEDULE_FREE"
        if re.search(r"\b(where|which room|location|located|sitting|find)\b", t):
            return "PROFESSOR_SCHEDULED_LOCATION"
        if re.search(r"\b(which|what)\b.*\b(courses?|subjects?|papers?)\b|\bteach(es|ing)?\b(?!.*\b(batch|division|class)\b)|\bcourses? (of|by|taught)\b", t) \
                and not has_batch:
            return "PROFESSOR_COURSE"
        return "PROFESSOR_SCHEDULE"
    teachers_q = re.search(r"\b(who|which|list|show|what)\b.*\b(professors?|faculty|faculties|teachers?|staff|profs?|lecturers?)\b|\bwho teach(es)?\b", t)
    if teachers_q and (has_batch or re.search(r"\b(my|our) (batch|class|division|group)\b|\bteach(es)? (me|us)\b", t)):
        return "PROFESSORS_FOR_BATCH"
    if has_floor:
        if rooms_word and free_word:
            return "FIND_FREE_ROOMS"
        if rooms_word and p.after:
            return "ROOMS_WITH_CLASSES_AFTER_TIME"
        return "FLOOR_ACTIVITY"
    if rooms_word and free_word:
        return "FIND_FREE_ROOMS"
    if rooms_word and (p.after or re.search(r"\b(have|with) (classes|lectures)\b", t)):
        return "ROOMS_WITH_CLASSES_AFTER_TIME"
    if has_room:
        if free_word:
            return "ROOM_FREE_NOW"
        if p.weekday or p.dates:
            return "ROOM_SCHEDULE_FOR_DAY"
        return "ROOM_SCHEDULE"
    if re.search(r"\b(when am i free|when (are|am) (we|i) free|my free (time|periods?|slots?))\b", t):
        return "PROFESSOR_FREE_TIME"
    if free_word and (p.times or p.self_ref):
        return "CHECK_SCHEDULE_FREE"
    if re.search(r"\b(do|have)\b.*\b(class|classes|lecture|lectures)\b.*\bat\b", t) and p.times and not p.time_is_range:
        return "CHECK_SCHEDULE_FREE"
    if re.search(r"\bnext\s+(class|lecture|lab|period|session|practical)\b|\bnext one\b|\bwhat'?s next\b|\bupcoming class\b", t):
        return "NEXT_CLASS"
    if re.search(r"\b(remaining|left|rest of|still have|any more|anymore|more classes)\b", t) and not p.after:
        return "REMAINING_CLASSES_TODAY"
    if p.after_lunch or (p.after and p.times and re.search(r"\b(class|classes|lectures?|anything|scheduled)\b", t)):
        return "CLASSES_AFTER_TIME"
    if p.detail_request and re.search(r"\b(class|lecture|lab|entry|session)\b", t):
        return "SHOW_CLASS_DETAILS"
    if p.now and re.search(r"\b(class|lecture|lab|period|session|happening|going on)\b", t) and not p.times:
        return "CURRENT_CLASS"
    if p.time_is_range:
        return "FILTER_CLASSES_BY_TIME"
    if has_course:
        return "FIND_COURSE_CLASSES"
    if has_batch:
        return "SHOW_BATCH_TIMETABLE"
    if p.week_ref:
        return "SHOW_WEEK_TIMETABLE"
    if p.dates or p.date_ambiguous_raw:
        return "SHOW_TIMETABLE_FOR_DATE"
    if p.weekday:
        return "SHOW_DAY_TIMETABLE"
    if re.search(r"\b(timetable|time table|schedule|classes|lectures|routine|agenda)\b", t):
        return "SHOW_MY_TIMETABLE"
    if p.archive_modifier:
        return "SHOW_MY_TIMETABLE"
    return None


EXAMPLES = [
    "What is my next class?", "What classes do I have tomorrow?", "Show my timetable for this week", "Find all DBMS classes",
    "Is room 508 free at 2 PM today?", "Which professors teach SE-A?", "What is happening on the 5th floor?",
    "When is Prof. Desai free tomorrow?", "How long until my next class?", "Do I have classes after lunch?",
]
