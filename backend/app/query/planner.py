"""Compositional query planner: a question becomes a structured *query plan*.

Instead of matching a whole question to one fixed question type, the planner recognises
independent pieces and combines them freely:

* operation — what to compute: LIST, COUNT, EXISTS, TOTAL_HOURS, FIRST, LAST, NEXT, PER_DAY
  (or one of the specialised operations below);
* filters  — who / what: me, batch, professor, room, course; kind = lab or lecture;
* when     — date, weekday, this/next week, or the whole weekly timetable;
* window   — at / after / before / between a time, after lunch;
* sort     — MOST / LEAST / EARLIEST / LATEST (for PER_DAY).

Questions that need specialised logic (free rooms, a professor's free time or location, room
status, current class, archives …) keep their proven operations; the plan then names that
operation and `composed` is False. Everything else is answered by the composed executor
(`app/query/composer.py`). Like the rest of the engine this is deterministic and rule-based:
the plan holds only typed values from a closed vocabulary — never SQL — and the server adds the
caller's role scope when the plan is compiled.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from app.query.nlp import Parsed

# ------------------------------------------------------------------ closed vocabularies

OPERATIONS = ("LIST", "COUNT", "EXISTS", "TOTAL_HOURS", "FIRST", "LAST", "NEXT", "PER_DAY", "SPAN", "FREE_SLOTS",
              "BREAKS", "AFTER_COURSE", "BEFORE_COURSE", "TEACHERS", "PER_ROOM", "ROOM_INFO", "CONFLICTS")
KINDS = ("LAB", "LECTURE")
SORTS = ("MOST", "LEAST", "EARLIEST", "LATEST")
WINDOWS = ("AT", "AFTER", "BEFORE", "BETWEEN", "AFTER_LUNCH", "NOW")
COMPOSED_INTENT = "COMPOSED_QUERY"

# Whole-question rules that always keep their own operation (archives, primary, "how long until").
PINNED = {"CROSS_DOMAIN_COMPARE", "MAKE_TIMETABLE_PRIMARY", "SHOW_PRIMARY_TIMETABLE", "LIST_TIMETABLE_ARCHIVES",
          "TIME_UNTIL_NEXT_CLASS", "SEARCH_SELECTED_ARCHIVE", "SHOW_CLASS_DETAILS"}
# Specialised operations whose results can be counted ("how many free rooms …").
COUNTABLE_SPECIALISED = {"FIND_FREE_ROOMS", "PROFESSORS_FOR_BATCH", "PROFESSOR_COURSE",
                         "ROOMS_WITH_CLASSES_AFTER_TIME", "FLOOR_ACTIVITY", "PROFESSOR_FREE_TIME"}
ROOM_SPECIALISED = {"FIND_FREE_ROOMS", "ROOMS_WITH_CLASSES_AFTER_TIME"}
# Specialised operations that are plain class listings: a lab/lecture filter or a "before"
# window turns them into a composed plan with the same filters.
LISTING_SPECIALISED = {"SHOW_MY_TIMETABLE", "SHOW_DAY_TIMETABLE", "SHOW_TIMETABLE_FOR_DATE", "SHOW_WEEK_TIMETABLE",
                       "SHOW_BATCH_TIMETABLE", "FIND_COURSE_CLASSES", "FILTER_CLASSES_BY_TIME", "CLASSES_AFTER_TIME",
                       "PROFESSOR_SCHEDULE", "REMAINING_CLASSES_TODAY", "NEXT_CLASS", "TIME_UNTIL_NEXT_CLASS",
                       "CURRENT_CLASS", "CHECK_SCHEDULE_FREE", "ROOM_SCHEDULE", "ROOM_SCHEDULE_FOR_DAY"}

# ------------------------------------------------------------------ phrase rules (one piece each)

_COUNT = re.compile(r"\bhow many\b|\bnumber of\b|\bno\.? of\b|\bcount\b")
_HOURS = re.compile(r"\b(how many|total|number of|no\.? of)\s+(hours|hrs|hour)\b|\btotal\s+(time|duration|teaching time)\b"
                    r"|\bhours of (class|classes|lectures?|labs?|teaching)\b")
_FIRST = re.compile(r"\b(first|earliest)\b(?!\s+(floor|year|sem|semester|half|week))|\bwhen (do|does|will) (i|we|my|our|college|the day|the college)\b.*\b(start|begin)s?\b"
                    r"|\bwhat time (do|does|will) .*\b(start|begin)s?\b|\b(start|begin)s? (my|our|the) day\b"
                    r"|\bwhat time (do|should|must|will) (i|we) (reach|arrive|come|get to|leave for)\b"
                    r"|\bwhen (do|should|must) (i|we) (reach|arrive|come to)\b")
_LAST = re.compile(r"\b(last|latest|final)\b(?!\s+(week|weekend|year|month|semester|sem|timetables?|archives?|version|uploads?|floor))"
                   r"|\b(finish|finishes|finished|done for the day|wrap up|go home|leave college|leave for home|get out)\b"
                   r"|\b(day|college|classes|lectures)\s+(ends?|over|get over|gets over|finish(es)?)\b"
                   r"|\bwhen (do|does|will) .*\bend\b|\bwhat time (do|does|will) .*\bend\b"
                   r"|\bwhen (do|will|can|would) (i|we) (get|be) free\b(?!.*\b(at|after|before|between)\b)"
                   r"|\bwhen can (i|we) (go|leave)\b")
_PER_DAY = re.compile(r"\bwhich day\b|\bwhat day\b|\bwhich days\b|\bbusiest\b|\blightest\b|\bfreest\b|\bleast busy\b|\bmost busy\b"
                      r"|\bper day\b|\beach day\b|\bevery day\b|\bday[- ]?wise\b|\bdaily (count|summary|load)\b"
                      r"|\b(longest|shortest|heaviest|easiest|hardest)\s+day\b")
_MOST = re.compile(r"\b(most|maximum|max|busiest|heaviest|longest|most busy)\b")
_LEAST = re.compile(r"\b(least|fewest|minimum|min|lightest|freest|shortest|least busy)\b")
_EXISTS = re.compile(r"\b(do|does|will) (i|we|he|she|they|prof\w*|dr\w*|\w+) (have|has|get|take|takes)\b.*\bany\b|\bis there any\b|\bare there any\b"
                     r"|\bany (labs?|practicals?|lectures?)\b")
_LAB = re.compile(r"\b(labs?|laborator(y|ies)|practicals?|practical sessions?)\b(?!\s*(no\.?|number|#)?\s*[a-z]?-?\d)")
_LECTURE = re.compile(r"\b(lectures?|theory|theories|theory classes)\b")
_BEFORE = re.compile(r"\b(before|earlier than|till|until|upto|up to|by)\s+(\d|noon)")
_END_WORDS = re.compile(r"\b(finish|finishes|end|ends|done|over|leave|go home|get out|wrap up|last class|last lecture|last lab)\b")
_START_WORDS = re.compile(r"\b(start|starts|begin|begins|first class|first lecture|first lab|reach|arrive|come in)\b")
_SUBJ_PROF = re.compile(r"\b(professors?|teachers?|faculty|faculties|staff|profs?|lecturers)\b")
_SUBJ_COURSE = re.compile(r"\b(subjects?|courses?|papers?)\b")
_SUBJ_ROOM = re.compile(r"\b(rooms|classrooms|halls)\b")
_SUBJ_BATCH = re.compile(r"\b(batches|divisions|groups) (do|does|will|did) (i|we|he|she|they|prof\w*|dr\w*|\w+) (teach|take|handle)\b"
                         r"|\b(which|what|how many) (batches|divisions)\b|\bwho do (i|we) teach\b|\bwhom do (i|we) teach\b")
_CONFLICTS = re.compile(r"\b(clash|clashes|clashing|conflicts?|double[- ]?booked)\b")
_ROOM_INFO = re.compile(r"\b(which|what) floor\b|\bwhere is\b|\bwhere's\b|\blocation of\b|\bcapacity\b|\bhow (big|many seats)\b")
_PER_ROOM = re.compile(r"\b(busiest|most used|least used|most busy|least busy|emptiest|freest)\s+(room|rooms|classroom|classrooms|lab|labs)\b"
                       r"|\bwhich (room|rooms|classroom|lab)\b.*\b(used|occupied|booked|busy)\b.*\b(most|least)\b|\broom usage\b"
                       r"|\b(rooms|labs) (used|occupied) (the )?(most|least)\b")
_BREAKS = re.compile(r"\b(lunch|break|breaks|recess|short break|long break)\b")
_NOT_BREAK_Q = re.compile(r"\b(after|post|before)[- ]?(the )?(lunch|break)\b")
_FREE_SLOTS = re.compile(r"\bfree (period|periods|slot|slots|lecture|lectures|hour|hours|time|lectures)\b|\bwhen (am|are) (i|we) free\b"
                         r"|\b(gap|gaps)\b|\bno class\b.*\bwhen\b|\bwhen\b.*\bno class\b")
_SPAN = re.compile(r"\bhow long is (my|the|our) (day|college|schedule)\b|\bhow (long|many hours) (am i|do i stay|do we stay|do i spend|do we spend|will i be|are we)\b"
                   r"|\bcollege timings?\b|\b(day|college) (timings?|span|hours)\b|\bfrom what time to what time\b|\bmy day\b.*\bstart.*\bend\b")
_AFTER_COURSE = re.compile(r"\b(after|following)\s+(?!lunch\b|break\b|\d|noon\b)")
_BEFORE_COURSE = re.compile(r"\bbefore\s+(?!lunch\b|break\b|\d|noon\b)")
_SEQ_Q = re.compile(r"\b(what|which|whats|what's)\b|\bcomes?\b|\bnext\b")
_TEACHERS = re.compile(r"\bwho\b.*\b(teach|teaches|teaching|takes|take|taking|handles|handle|conducts?)\b|\bteachers? (of|for)\b"
                       r"|\bwho is the (teacher|professor|faculty|prof)\b|\b(teacher|professor|faculty) (of|for)\b")
_UNIT_ROOMS = re.compile(r"\b(which|what|list|my|how many) (rooms|classrooms)\b.*\b(do|does|will) (i|we)\b|\brooms (i|we) (teach|have|use|go)\b")
_UNIT_SUBJECTS = re.compile(r"\b(which|what|list|show|all|my) (subjects|courses|papers)\b")
_ELECTIVES = re.compile(r"\b(electives?|optional subjects?|minors?|honou?rs)\b")
_TEACH_SELF = re.compile(r"\b(teach|teaching|take|taking|handle|handling)\b")
_NEXT = re.compile(r"\bnext\s+(lab|labs|practical|lecture|theory)\b|\bupcoming\s+(lab|practical|lecture)\b")


@dataclass
class QueryPlan:
    operation: str                      # one of OPERATIONS, or a specialised operation name
    composed: bool                      # True → answered by the composed executor
    kind: str | None = None             # LAB | LECTURE | None
    window: str | None = None           # AT | AFTER | BEFORE | BETWEEN | AFTER_LUNCH | None
    sort: str | None = None             # MOST | LEAST | EARLIEST | LATEST
    metric: str | None = None           # for PER_DAY: CLASSES | FIRST_START | LAST_END | HOURS
    count_of: str | None = None         # COUNT over a specialised operation's results
    unit: str | None = None             # what COUNT counts: CLASSES (default), COURSES, BATCHES or ROOMS
    electives: bool = False             # COURSES restricted to electives / MDM / PE / OE
    self_also: bool = False             # "when do I teach SE-A": my own classes AND the named filter
    room_type: str | None = None        # free-room questions about labs / classrooms only
    filters: dict = field(default_factory=dict)   # names mentioned (typed later against the timetable)
    when: dict = field(default_factory=dict)      # date / weekday / week as understood from the text

    def as_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v not in (None, {}, [], False) or k == "composed"}


def _when(p: Parsed) -> dict:
    out: dict = {}
    if p.dates:
        out["date"] = p.dates[0].isoformat()
    elif p.date_ambiguous_raw:
        out["date_text"] = p.date_ambiguous_raw
    elif p.week_ref:
        out["week"] = p.week_ref
    elif p.weekday:
        out["weekday"] = p.weekday
    if p.now:
        out["now"] = True
    return out


def _filters(p: Parsed) -> dict:
    out = {k: getattr(p, k) for k in ("professor", "course", "batch", "room") if getattr(p, k)}
    if p.floor is not None:
        out["floor"] = p.floor
    if p.self_ref and not out:
        out["self"] = True
    return out


def _window(p: Parsed, t: str) -> str | None:
    if p.after_lunch:
        return "AFTER_LUNCH"
    if not p.times:
        return "NOW" if p.now else None
    if p.time_is_range:
        return "BETWEEN"
    if _BEFORE.search(t):
        return "BEFORE"
    if p.after:
        return "AFTER"
    return "AT"


def build_plan(p: Parsed, specialised: str | None) -> QueryPlan:
    """Combine the recognised pieces into a plan.

    `specialised` is the operation the rule cascade (`nlp.classify`) recognised for the whole
    question; it is kept when no composable piece (aggregate, ordering, lab/lecture, "before")
    changes the question.
    """
    t = p.norm
    if specialised in PINNED:
        return QueryPlan(operation=specialised, composed=False, filters=_filters(p), when=_when(p))
    kind = "LAB" if _LAB.search(t) else ("LECTURE" if _LECTURE.search(t) else None)
    window = _window(p, t)
    base = dict(kind=kind, window=window, filters=_filters(p), when=_when(p))
    base["self_also"] = bool(p.self_ref and _TEACH_SELF.search(t) and (p.batch or p.course) and not p.professor)
    if _SUBJ_BATCH.search(t) and (p.self_ref or p.professor):
        return QueryPlan(operation="COUNT", composed=True, unit="BATCHES", **base)
    shaped = _shape(p, t, specialised, base)
    if shaped is not None:
        return shaped

    op: str | None = None
    sort = metric = None
    if _HOURS.search(t):
        op = "TOTAL_HOURS"
    elif _COUNT.search(t):
        op = "COUNT"
    if _PER_DAY.search(t):
        first, last = bool(_FIRST.search(t)), bool(_LAST.search(t))
        ends, starts = bool(_END_WORDS.search(t)), bool(_START_WORDS.search(t))
        if first or last or ends or starts:
            # "finish/end/leave" → when the day ends; "start/begin" → when it starts; else first/last.
            if ends != starts:
                metric = "LAST_END" if ends else "FIRST_START"
            else:
                metric = "FIRST_START" if first and not last else "LAST_END"
            early = re.search(r"\b(earliest|early|earlier|soonest|first)\b", t)
            late = re.search(r"\b(latest|late|later|last)\b", t)
            if early and not late:
                sort = "EARLIEST"
            elif late and not early:
                sort = "LATEST"
            else:
                sort = "EARLIEST" if metric == "FIRST_START" else "LATEST"
        else:
            metric = "HOURS" if op == "TOTAL_HOURS" or re.search(r"\b(longest|shortest)\b", t) else "CLASSES"
            sort = "LEAST" if _LEAST.search(t) else ("MOST" if _MOST.search(t) else None)
        op = "PER_DAY"
    elif op is None:
        if _NEXT.search(t):
            op = "NEXT"
        elif _FIRST.search(t):
            op = "FIRST"
        elif _LAST.search(t):
            op = "LAST"
        elif kind and _EXISTS.search(t):
            op = "EXISTS"

    # "How many professors / subjects / rooms …": count the right thing.
    if op == "COUNT" and not kind and specialised not in COUNTABLE_SPECIALISED:
        if _SUBJ_PROF.search(t) and not p.professor:
            specialised = "PROFESSORS_FOR_BATCH"
            if re.search(r"\b(we|us|our)\b", t):
                p.self_ref = True          # "how many teachers do we have" = my own batch
        elif _SUBJ_COURSE.search(t) and p.professor:
            specialised = "PROFESSOR_COURSE"
        elif _SUBJ_COURSE.search(t):
            return QueryPlan(operation="COUNT", composed=True, unit="COURSES", **base)
        elif _SUBJ_ROOM.search(t) and re.search(r"\b(free|available|empty|vacant)\b", t):
            specialised = "FIND_FREE_ROOMS"
    if specialised in ROOM_SPECIALISED:
        if re.search(r"\b(labs?|laborator(y|ies))\b", t):
            base["room_type"] = "LAB"
        elif re.search(r"\bclassrooms?\b", t):
            base["room_type"] = "CLASSROOM"
        base["kind"] = None                 # "free labs" is about rooms, not lab sessions
    # Counting what a specialised operation returns (rooms, professors, courses, free slots).
    if op == "COUNT" and specialised in COUNTABLE_SPECIALISED and (not kind or specialised in ROOM_SPECIALISED):
        return QueryPlan(operation="COUNT", composed=False, count_of=specialised, **base)
    if op is None and base["self_also"] and specialised in ("SHOW_BATCH_TIMETABLE", "FIND_COURSE_CLASSES"):
        op = "LIST"                          # "when do I teach SE-A": my classes for that batch
    if op is None:
        if kind is None and window != "BEFORE":
            return QueryPlan(operation=specialised or "UNKNOWN", composed=False, **base)
        if specialised is not None and specialised not in LISTING_SPECIALISED:
            return QueryPlan(operation=specialised, composed=False, **base)
        op = "NEXT" if specialised in ("NEXT_CLASS", "TIME_UNTIL_NEXT_CLASS") else "LIST"
    return QueryPlan(operation=op, composed=True, sort=sort, metric=metric, **base)


def _shape(p: Parsed, t: str, specialised: str | None, base: dict) -> QueryPlan | None:
    """Question shapes with their own operation (conflicts, room details, breaks, free periods …)."""
    timeless = not (p.times or p.weekday or p.dates or p.week_ref or p.now)
    if _CONFLICTS.search(t):
        return QueryPlan(operation="CONFLICTS", composed=True, **base)
    if p.room and not p.times and timeless and _ROOM_INFO.search(t):
        return QueryPlan(operation="ROOM_INFO", composed=True, **base)
    if _PER_ROOM.search(t):
        least = re.search(r"\b(least|emptiest|freest)\b", t)
        return QueryPlan(operation="PER_ROOM", composed=True, sort="LEAST" if least else "MOST", **{**base, "kind": None})
    if _BREAKS.search(t) and not _NOT_BREAK_Q.search(t) and not p.after_lunch:
        return QueryPlan(operation="BREAKS", composed=True, **{**base, "kind": None})
    if (_FREE_SLOTS.search(t) and not p.professor and not p.times and not _SUBJ_ROOM.search(t)
            and not re.search(r"\b(labs|rooms)\b", t)):
        return QueryPlan(operation="FREE_SLOTS", composed=True, **base)
    if _SPAN.search(t):
        return QueryPlan(operation="SPAN", composed=True, **base)
    if p.course and _SEQ_Q.search(t):
        if _AFTER_COURSE.search(t):
            return QueryPlan(operation="AFTER_COURSE", composed=True, **base)
        if _BEFORE_COURSE.search(t):
            return QueryPlan(operation="BEFORE_COURSE", composed=True, **base)
    if p.course and _TEACHERS.search(t) and not p.batch and not p.professor:
        return QueryPlan(operation="TEACHERS", composed=True, **base)
    if _UNIT_ROOMS.search(t):
        return QueryPlan(operation="COUNT", composed=True, unit="ROOMS", **base)
    if _ELECTIVES.search(t) and not p.course and re.search(r"\b(which|what|list|show|my|how many|do i|all)\b", t):
        return QueryPlan(operation="COUNT", composed=True, unit="COURSES", electives=True, **base)
    if _UNIT_SUBJECTS.search(t) and not p.professor and not _COUNT.search(t):
        return QueryPlan(operation="COUNT", composed=True, unit="COURSES", **base)
    return None
