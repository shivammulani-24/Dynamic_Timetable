"""Approved intent registry (Intent & Entity Schema V1 §3) and query-template catalogue (API Contract §9).

Nothing outside these registries can be executed. Each template is implemented as a fixed,
parameterised SQLAlchemy query in `templates.py`; values are always bound parameters.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.enums import Domain

BOTH = frozenset({Domain.INSTITUTIONAL, Domain.PERSONAL})
INST = frozenset({Domain.INSTITUTIONAL})


@dataclass(frozen=True)
class IntentSpec:
    qid: str
    name: str
    templates: tuple[str, ...]
    domains: frozenset[Domain]
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    example: str = ""
    state_changing: bool = False
    personal_unsupported_reason: str | None = None
    notes: str = ""


INTENTS: dict[str, IntentSpec] = {s.name: s for s in [
    IntentSpec("Q01", "SHOW_MY_TIMETABLE", ("QT01",), BOTH, (), ("date",), "Show my timetable",
               notes="No date → today (confirmed decision)."),
    IntentSpec("Q02", "SHOW_DAY_TIMETABLE", ("QT03", "QT01"), BOTH, ("day_of_week|date",), ("batch", "course", "professor", "room"),
               "Show Monday's timetable"),
    IntentSpec("Q03", "SHOW_TIMETABLE_FOR_DATE", ("QT01",), BOTH, ("date",), ("batch", "course", "professor", "room"),
               "What classes do I have tomorrow?"),
    IntentSpec("Q04", "SHOW_WEEK_TIMETABLE", ("QT02",), BOTH, ("date_range",), ("batch",), "Show my timetable for this week",
               notes="Week start must be configured; otherwise ask for a range."),
    IntentSpec("Q05", "SHOW_BATCH_TIMETABLE", ("QT03", "QT01"), BOTH, ("batch",), ("day_of_week", "date"), "Show SE-A timetable"),
    IntentSpec("Q06", "FIND_COURSE_CLASSES", ("QT05",), BOTH, ("course",), ("day_of_week", "date"), "Find all DBMS classes"),
    IntentSpec("Q07", "FILTER_CLASSES_BY_TIME", ("QT04",), BOTH, ("time_range", "date|day_of_week"), (),
               "Show my classes between 10 am and 12 pm"),
    IntentSpec("Q08", "SHOW_CLASS_DETAILS", ("QT06",), BOTH, ("entry_id|identifying_fields",), (), "Show details of the 10 am DBMS class"),
    IntentSpec("Q09", "CURRENT_CLASS", ("QT07",), BOTH, (), (), "What class is happening now?"),
    IntentSpec("Q10", "NEXT_CLASS", ("QT08",), BOTH, (), (), "What is my next class?"),
    IntentSpec("Q11", "CLASSES_AFTER_TIME", ("QT04",), BOTH, ("lunch_boundary|time",), ("date",), "Do I have classes after lunch?"),
    IntentSpec("Q12", "TIME_UNTIL_NEXT_CLASS", ("QT08",), BOTH, (), (), "How long until my next class?"),
    IntentSpec("Q13", "CHECK_SCHEDULE_FREE", ("QT04",), BOTH, ("time", "date"), ("professor",), "Am I free at 2 PM tomorrow?"),
    IntentSpec("Q14", "REMAINING_CLASSES_TODAY", ("QT09",), BOTH, (), (), "Do I have any classes left today?"),
    IntentSpec("Q15", "PROFESSOR_SCHEDULE", ("QT10",), BOTH, ("professor",), ("date", "day_of_week", "date_range"),
               "Show Professor Desai's schedule"),
    IntentSpec("Q16", "PROFESSOR_SCHEDULED_LOCATION", ("QT11",), BOTH, ("professor",), ("time", "date"),
               "Where is Professor Desai scheduled now?"),
    IntentSpec("Q17", "PROFESSOR_COURSE", ("QT12", "QT05"), BOTH, ("professor",), (), "Which course does Professor Desai teach?"),
    IntentSpec("Q18", "PROFESSOR_FREE_TIME", ("QT13",), INST, ("professor", "date"), (), "When is Professor Desai free tomorrow?",
               personal_unsupported_reason="Professor free time needs institutional working hours and a complete staff schedule; "
                                           "a personal upload cannot provide that."),
    IntentSpec("Q19", "PROFESSORS_FOR_BATCH", ("QT14",), BOTH, ("batch",), (), "Which professors teach SE-A?"),
    IntentSpec("Q20", "ROOM_SCHEDULE", ("QT15",), BOTH, ("room",), ("date", "day_of_week"), "Show room 508's schedule"),
    IntentSpec("Q21", "ROOM_FREE_NOW", ("QT16",), BOTH, ("room",), ("time", "date"), "Is room 508 free now?"),
    IntentSpec("Q22", "FIND_FREE_ROOMS", ("QT17",), INST, ("time", "date"), ("floor",), "Which rooms are free at 2 PM today?",
               personal_unsupported_reason="Finding free rooms needs the college room inventory, which only the institutional view has."),
    IntentSpec("Q23", "FLOOR_ACTIVITY", ("QT18",), INST, ("floor",), ("time", "date"), "What is happening on the 5th floor?",
               personal_unsupported_reason="Floor activity needs the college room-to-floor mapping, available only in the institutional view."),
    IntentSpec("Q24", "ROOM_SCHEDULE_FOR_DAY", ("QT15", "QT03"), BOTH, ("room", "day_of_week|date"), (),
               "Show room 508's schedule for Friday"),
    IntentSpec("Q25", "ROOMS_WITH_CLASSES_AFTER_TIME", ("QT19",), INST, ("time", "date"), ("floor",),
               "Which rooms have classes after 1 PM today?",
               personal_unsupported_reason="Room-wide monitoring uses the college room inventory, available only in the institutional view."),
    IntentSpec("Q26", "SEARCH_SELECTED_ARCHIVE", ("QT20",), BOTH, ("explicit_archive",), (), "Search this archived timetable for DBMS"),
    IntentSpec("Q27", "SHOW_PRIMARY_TIMETABLE", ("QT20",), BOTH, (), (), "Which timetable is currently primary?"),
    IntentSpec("Q28", "MAKE_TIMETABLE_PRIMARY", ("QT22",), BOTH, ("timetable_id",), (), "Make this timetable my primary",
               state_changing=True),
    IntentSpec("Q29", "LIST_TIMETABLE_ARCHIVES", ("QT21",), BOTH, (), (), "Show my old timetable archives"),
    IntentSpec("Q30", "CROSS_DOMAIN_COMPARE", (), frozenset(), (), (), "Compare my personal and college timetable",
               notes="Unsupported in V1; always rejected without querying either domain."),
]}

BY_QID = {s.qid: s for s in INTENTS.values()}


@dataclass(frozen=True)
class TemplateSpec:
    qt: str
    operation: str
    intents: tuple[str, ...]
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    domains: frozenset[Domain] = BOTH
    result_fields: tuple[str, ...] = ()
    empty_result: str = "NO_MATCH scoped to the selected timetable; never broadened."
    uncertain_handling: str = "Unverified entries returned with warnings (DATA_UNVERIFIED)."
    extra: dict = field(default_factory=dict)


ENTRY_FIELDS = ("entry_id", "kind", "day_of_week", "date", "start_time", "end_time", "duration_minutes", "course", "course_code",
                "professor", "batch", "room", "floor", "verification_status", "time_uncertain", "is_tentative", "warnings")
TIME_SENSITIVE = "Entries with uncertain/missing times are EXCLUDED and the exclusion is reported as a warning."

TEMPLATES: dict[str, TemplateSpec] = {t.qt: t for t in [
    TemplateSpec("QT01", "LIST_ENTRIES_FOR_DATE", ("Q01", "Q02", "Q03", "Q14"), ("timetable_id", "date"),
                 ("course", "batch", "professor", "room"), result_fields=ENTRY_FIELDS),
    TemplateSpec("QT02", "LIST_ENTRIES_FOR_DATE_RANGE", ("Q04",), ("timetable_id", "start_date", "end_date"), ("batch",),
                 result_fields=ENTRY_FIELDS, extra={"max_span_days": "MAX_DATE_RANGE_DAYS (31)"}),
    TemplateSpec("QT03", "LIST_ENTRIES_FOR_WEEKDAY", ("Q02", "Q24", "Q05"), ("timetable_id", "day_of_week"), ("batch", "room"),
                 result_fields=ENTRY_FIELDS),
    TemplateSpec("QT04", "FILTER_ENTRIES_BY_TIME", ("Q07", "Q25", "Q11", "Q13"), ("timetable_id", "date", "start_time", "end_time"),
                 result_fields=ENTRY_FIELDS, uncertain_handling=TIME_SENSITIVE),
    TemplateSpec("QT05", "FIND_BY_COURSE", ("Q06", "Q17"), ("timetable_id", "course"), ("date", "day_of_week"), result_fields=ENTRY_FIELDS),
    TemplateSpec("QT06", "GET_ENTRY_DETAILS", ("Q08",), ("timetable_id", "entry_id"), result_fields=ENTRY_FIELDS + ("raw_text",)),
    TemplateSpec("QT07", "GET_CURRENT_ENTRY", ("Q09",), ("timetable_id", "now"), result_fields=ENTRY_FIELDS,
                 uncertain_handling=TIME_SENSITIVE),
    TemplateSpec("QT08", "GET_NEXT_ENTRY", ("Q10", "Q12"), ("timetable_id", "now"), result_fields=ENTRY_FIELDS + ("minutes_until",),
                 uncertain_handling=TIME_SENSITIVE, extra={"date_scope": "today, then following days up to next_class_lookahead_days"}),
    TemplateSpec("QT09", "GET_REMAINING_TODAY", ("Q14",), ("timetable_id", "now"), result_fields=ENTRY_FIELDS,
                 uncertain_handling=TIME_SENSITIVE),
    TemplateSpec("QT10", "GET_PROFESSOR_SCHEDULE", ("Q15",), ("timetable_id", "professor"), ("date", "day_of_week", "date_range"),
                 result_fields=ENTRY_FIELDS),
    TemplateSpec("QT11", "GET_PROFESSOR_SCHEDULED_LOCATION", ("Q16",), ("timetable_id", "professor", "now"),
                 result_fields=ENTRY_FIELDS, uncertain_handling=TIME_SENSITIVE),
    TemplateSpec("QT12", "GET_PROFESSOR_COURSES", ("Q17",), ("timetable_id", "professor"), result_fields=("course", "course_code", "evidence_count")),
    TemplateSpec("QT13", "GET_PROFESSOR_FREE_INTERVALS", ("Q18",), ("timetable_id", "professor", "date", "working_hours"),
                 domains=INST, result_fields=("start_time", "end_time", "duration_minutes"),
                 uncertain_handling="Uncertain-time entries are treated as busy (conservative) and reported."),
    TemplateSpec("QT14", "GET_PROFESSORS_FOR_BATCH", ("Q19",), ("timetable_id", "batch"), result_fields=("professor", "professor_code", "courses", "evidence_count")),
    TemplateSpec("QT15", "GET_ROOM_SCHEDULE", ("Q20", "Q24"), ("timetable_id", "room"), ("date", "day_of_week"), result_fields=ENTRY_FIELDS),
    TemplateSpec("QT16", "CHECK_ROOM_SCHEDULED_FREE", ("Q21",), ("timetable_id", "room", "date", "time"),
                 result_fields=("room", "scheduled_free", "entries"), uncertain_handling=TIME_SENSITIVE),
    TemplateSpec("QT17", "FIND_SCHEDULED_FREE_ROOMS", ("Q22",), ("timetable_id", "date", "time"), ("floor",), domains=INST,
                 result_fields=("room", "floor", "building", "capacity"),
                 uncertain_handling="Rooms with uncertain/unmapped entries at that time are not claimed free."),
    TemplateSpec("QT18", "GET_FLOOR_ENTRIES", ("Q23",), ("timetable_id", "floor", "date", "time"), domains=INST, result_fields=ENTRY_FIELDS),
    TemplateSpec("QT19", "GET_ROOMS_WITH_ENTRIES_AFTER_TIME", ("Q25",), ("timetable_id", "date", "time"), ("floor",), domains=INST,
                 result_fields=("room", "floor", "first_start", "classes")),
    TemplateSpec("QT20", "GET_SELECTED_TIMETABLE_METADATA", ("Q26", "Q27"), ("timetable_id",), result_fields=("timetable",)),
    TemplateSpec("QT21", "LIST_ARCHIVES_IN_DOMAIN", ("Q29",), ("domain",), result_fields=("timetable",)),
    TemplateSpec("QT22", "SET_DOMAIN_PRIMARY", ("Q28",), ("domain", "timetable_id"), result_fields=("primary_timetable_id",),
                 empty_result="n/a (action)", uncertain_handling="Only READY/NEEDS_REVIEW timetables are eligible."),
]}


def registry_document() -> dict:
    """Machine-readable registry (served at /api/v1/search/registry for transparency and docs)."""
    return {
        "intents": [{"id": s.qid, "intent": s.name, "templates": list(s.templates), "domains": sorted(d.value for d in s.domains),
                     "required": list(s.required), "optional": list(s.optional), "example": s.example,
                     "state_changing": s.state_changing, "notes": s.notes} for s in INTENTS.values()],
        "templates": [{"id": t.qt, "operation": t.operation, "intents": list(t.intents), "required": list(t.required),
                       "optional": list(t.optional), "domains": sorted(d.value for d in t.domains),
                       "result_fields": list(t.result_fields), "empty_result": t.empty_result,
                       "uncertain_handling": t.uncertain_handling, **t.extra} for t in TEMPLATES.values()],
    }
