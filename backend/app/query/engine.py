"""Query engine: natural-language or structured request → approved intent → approved template.

Security boundary: identity, roles, domain, timetable and timezone come from the server
(`SearchContext`). Text can only *select among* registered intents and supply typed parameters,
which are validated and bound. No template accepts raw SQL, table or column names.
"""
from __future__ import annotations

import logging
import re
import time as _time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import Domain, RoleCode, SelectionType, VerificationStatus
from app.errors import HTTP_STATUS, AppError, Code
from app.models import InstitutionConfig, SearchHistory
from app.query import nlp, templates as T
from app.query.registry import INTENTS
from app.query.vocab import Resolution, Vocab, load_vocab, resolve, scan
from app.security.policy import SCOPE_FREE_INTENTS, institutional_scope, intent_allowed
from app.security.principal import Principal
from app.services.audit import request_id_var
from app.services.context import Clock, SearchContext, parse_domain, resolve_context
from app.services.matching import Candidate
from app.services.preferences import get_or_create_preferences
from app.services.timetables import (
    get_timetable,
    list_timetables,
    primary_id,
    serialize_timetable,
    set_primary,
)

log = logging.getLogger("search")

ALLOWED_PARAMS = {"date", "time", "start_time", "end_time", "start_date", "end_date", "day_of_week", "course", "professor",
                  "batch", "room", "floor", "entry_id", "timetable_id", "confirm", "lunch_time"}
SELF_INTENTS = {"SHOW_MY_TIMETABLE", "SHOW_DAY_TIMETABLE", "SHOW_TIMETABLE_FOR_DATE", "SHOW_WEEK_TIMETABLE",
                "FILTER_CLASSES_BY_TIME", "CURRENT_CLASS", "NEXT_CLASS", "CLASSES_AFTER_TIME", "TIME_UNTIL_NEXT_CLASS",
                "CHECK_SCHEDULE_FREE", "REMAINING_CLASSES_TODAY"}
META_INTENTS = {"SHOW_PRIMARY_TIMETABLE", "LIST_TIMETABLE_ARCHIVES", "MAKE_TIMETABLE_PRIMARY"}


class Clarify(Exception):
    def __init__(self, kind: str, question: str, parameter: str | None = None, choices: list[dict] | None = None, **extra):
        super().__init__(question)
        self.payload = {"kind": kind, "question": question, "parameter": parameter, "choices": choices or [], **extra}


class Halt(Exception):
    def __init__(self, code: Code, message: str, **details):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


@dataclass
class Request:
    query: str | None = None
    intent: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    domain: str | None = None
    selection: dict | None = None
    limit: int = 100
    cursor: int = 0


@dataclass
class Run:
    db: Session
    ctx: SearchContext
    req: Request
    parsed: nlp.Parsed
    vocab: Vocab | None = None
    intent: str | None = None
    warnings: list[dict] = field(default_factory=list)


# ======================================================================== envelope


def envelope(status: Code | str, *, intent: str | None = None, ctx: SearchContext | None = None, message: str = "",
             clarification: dict | None = None, warnings: list | None = None, results: list | None = None,
             result_type: str | None = None, meta: dict | None = None, pagination: dict | None = None,
             details: dict | None = None, context: dict | None = None) -> dict:
    spec = INTENTS.get(intent) if intent else None
    return {
        "status": str(status),
        "intent": intent,
        "intent_id": spec.qid if spec else None,
        "context": ctx.as_dict() if ctx else context,
        "message": message,
        "clarification": clarification,
        "warnings": warnings or [],
        "result_type": result_type,
        "results": results or [],
        "pagination": pagination,
        "meta": meta or {},
        "details": details or {},
        "request_id": request_id_var.get(),
    }


# ======================================================================== parameter validation


def _validate_params(params: dict) -> dict:
    unknown = set(params) - ALLOWED_PARAMS
    if unknown:
        raise Halt(Code.INVALID_REQUEST, f"Unsupported parameter(s): {', '.join(sorted(unknown))}.", fields=sorted(unknown))
    out: dict[str, Any] = {}
    for k, v in params.items():
        if v is None:
            continue
        try:
            if k in ("date", "start_date", "end_date"):
                out[k] = date.fromisoformat(str(v))
            elif k in ("time", "start_time", "end_time", "lunch_time"):
                if not re.fullmatch(r"\d{2}:\d{2}", str(v)):
                    raise ValueError
                out[k] = datetime.strptime(str(v), "%H:%M").time()
            elif k == "day_of_week":
                out[k] = int(v)
                if not 1 <= out[k] <= 7:
                    raise ValueError
            elif k == "floor":
                out[k] = int(v)
                if not -2 <= out[k] <= 60:
                    raise ValueError
            elif k in ("entry_id", "timetable_id"):
                out[k] = uuid.UUID(str(v))
            elif k == "confirm":
                out[k] = bool(v) if isinstance(v, bool) else str(v).lower() in ("true", "1", "yes")
            else:  # entity choice keys "id:…" / "label:…" or free text
                s = str(v).strip()
                if not s or len(s) > 120:
                    raise ValueError
                out[k] = s
        except (ValueError, TypeError):
            raise Halt(Code.INVALID_REQUEST, f"Invalid value for '{k}'.", field=k)
    return out


# ======================================================================== helpers used by handlers


def _fmt(t: time) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


def _date_choices(today: date) -> list[dict]:
    return [{"label": f"Today ({today:%a %d %b})", "value": {"date": today.isoformat()}},
            {"label": f"Tomorrow ({today + timedelta(days=1):%a %d %b})", "value": {"date": (today + timedelta(days=1)).isoformat()}}]


def _next_occurrence(today: date, dow: int, strictly_next: bool = False) -> date:
    delta = (dow - today.isoweekday()) % 7
    if strictly_next and delta == 0:
        delta = 7
    return today + timedelta(days=delta)


def need_date(r: Run, *, allow_weekday: bool = True, default_today: bool = False, now_ok: bool = False, purpose: str = "") -> date:
    pr = r.req.parameters
    if "date" in pr:
        return pr["date"]
    p = r.parsed
    if p.dates:
        return p.dates[0]
    if p.date_ambiguous_raw:
        raise Clarify("DATE", f"Is “{p.date_ambiguous_raw}” day/month or month/day? Please pick the date.", "date",
                      _date_choices(r.ctx.now.date()))
    if p.weekday and allow_weekday:
        d = _next_occurrence(r.ctx.now.date(), p.weekday, p.weekday_next)
        r.warnings.append({"code": "WEEKDAY_RESOLVED",
                           "message": f"Interpreted “{T.DOW[p.weekday]}” as {d:%A %d %b %Y} (next occurrence)."})
        return d
    if (now_ok and p.now) or default_today:
        return r.ctx.now.date()
    raise Clarify("DATE", f"Which date do you mean{(' ' + purpose) if purpose else ''}?", "date", _date_choices(r.ctx.now.date()))


def need_time(r: Run, idx: int = 0, *, key: str = "time", label: str = "time") -> time:
    pr = r.req.parameters
    if key in pr:
        return pr[key]
    if len(r.parsed.times) <= idx:
        raise Clarify("MISSING_PARAMETER", f"What {label}? (for example 2:00 PM)", key)
    tm = r.parsed.times[idx]
    readings = tm.readings()
    if len(readings) > 1:
        a, b = readings[0], readings[1]
        ta, tb = time(*a), time(*b)
        raise Clarify("AMPM", f"Did you mean {_fmt(ta)} or {_fmt(tb)}?", key,
                      [{"label": _fmt(tb), "value": {key: tb.strftime("%H:%M")}},
                       {"label": _fmt(ta), "value": {key: ta.strftime("%H:%M")}}])
    return time(*readings[0])


def need_entity(r: Run, kind: str, *, required: bool = True) -> list[Candidate]:
    """Resolve a professor/course/batch/room mention against the selected timetable only."""
    pr = r.req.parameters
    mention = pr.get(kind) if kind in pr else getattr(r.parsed, kind, None)
    if mention is None:
        if required:
            raise Clarify("MISSING_PARAMETER", f"Which {kind}?", kind)
        return []
    choice_key = mention if isinstance(mention, str) and mention.startswith(("id:", "label:")) else None
    res: Resolution = resolve(kind, mention, r.vocab, choice_key=choice_key)
    if res.resolved:
        return res.resolved
    if res.choices:
        raise Clarify("ENTITY_CHOICE", f"Which {kind} do you mean?", kind,
                      [{"label": c.display + (f" ({c.detail})" if c.detail else ""), "value": {kind: c.key}} for c in res.choices])
    raise Halt(Code.NO_MATCH, f"No {kind} matching “{mention}” was found in the selected timetable.", entity=kind)


def _filters(r: Run, *kinds: str, self_default: bool = False) -> T.Filters:
    f = T.Filters()
    for k in kinds:
        setattr(f, k, need_entity(r, k, required=False))
    f.self_only = self_default and not (f.course or f.professor or f.batch or f.room)
    if f.self_only and r.ctx.domain == Domain.INSTITUTIONAL:
        p = r.ctx.principal
        if RoleCode.PROFESSOR in p.roles and RoleCode.STUDENT not in p.roles and p.staff_id:
            from sqlalchemy import func, select

            m = T.models_for(Domain.INSTITUTIONAL)
            linked = r.db.scalar(select(func.count()).where(m.entry.timetable_id == r.ctx.timetable_id,
                                                            m.entry.staff_id == p.staff_id)) or 0
            if not linked:
                r.warnings.append({"code": "SELF_NOT_LINKED",
                                   "message": "No classes in this timetable are linked to your staff profile yet; "
                                              "ask the Admin to map your faculty code."})
    return f


def _q(r: Run, *, scope_free: bool = False) -> T.Q:
    return T.Q(r.db, r.ctx, scope_free=scope_free)


def _at(r: Run) -> datetime:
    """'now' unless the request gives a time (then a date is required)."""
    p, pr = r.parsed, r.req.parameters
    if p.times or "time" in pr:
        t = need_time(r)
        d = need_date(r, now_ok=False, purpose="for that time")
        return datetime.combine(d, t, tzinfo=r.ctx.now.tzinfo)
    if p.dates or "date" in pr:
        d = need_date(r)
        if d != r.ctx.now.date():
            raise Clarify("MISSING_PARAMETER", "At what time on that date?", "time")
    return r.ctx.now


def _subject(f: T.Filters, default: str = "you") -> str:
    for kind in ("professor", "batch", "room", "course"):
        c = getattr(f, kind)
        if c:
            return c[0].display
    return default


# ======================================================================== intent handlers


def h_my_timetable(r: Run) -> T.Result:
    d = need_date(r, default_today=True)
    return T.qt01_entries_for_date(_q(r), d, _filters(r, "batch", "course", "professor", "room", self_default=True))


def h_day(r: Run) -> T.Result:
    if r.parsed.dates or "date" in r.req.parameters or r.parsed.date_ambiguous_raw:
        return h_date(r)
    dow = r.req.parameters.get("day_of_week") or r.parsed.weekday
    if not dow:
        raise Clarify("MISSING_PARAMETER", "Which day of the week?", "day_of_week",
                      [{"label": T.DOW[i], "value": {"day_of_week": i}} for i in range(1, 7)])
    return T.qt03_entries_for_weekday(_q(r), dow, _filters(r, "batch", "course", "professor", "room", self_default=True))


def h_date(r: Run) -> T.Result:
    d = need_date(r, allow_weekday=False)
    return T.qt01_entries_for_date(_q(r), d, _filters(r, "batch", "course", "professor", "room", self_default=True))


def h_week(r: Run) -> T.Result:
    pr = r.req.parameters
    if "start_date" in pr and "end_date" in pr:
        start, end = pr["start_date"], pr["end_date"]
    elif len(r.parsed.dates) >= 2:
        start, end = sorted(r.parsed.dates[:2])
    else:
        cfg = r.db.get(InstitutionConfig, 1)
        today = r.ctx.now.date()
        if not cfg or cfg.week_start_day is None:
            choices = []
            for ws, name in ((1, "Monday"), (7, "Sunday")):
                s = today - timedelta(days=(today.isoweekday() - ws) % 7)
                if r.parsed.week_ref == "next":
                    s += timedelta(days=7)
                choices.append({"label": f"{s:%a %d %b} – {s + timedelta(days=6):%a %d %b} (week starting {name})",
                                "value": {"start_date": s.isoformat(), "end_date": (s + timedelta(days=6)).isoformat()}})
            raise Clarify("DATE_RANGE", "The college has not configured which day a week starts on. Which dates do you mean?",
                          "start_date", choices)
        start = today - timedelta(days=(today.isoweekday() - cfg.week_start_day) % 7)
        if r.parsed.week_ref == "next":
            start += timedelta(days=7)
        end = start + timedelta(days=6)
    if end < start:
        raise Halt(Code.INVALID_REQUEST, "The end date must not be before the start date.")
    if (end - start).days + 1 > get_settings().max_date_range_days:
        raise Halt(Code.INVALID_REQUEST, f"Please choose a range of at most {get_settings().max_date_range_days} days.")
    return T.qt02_entries_for_range(_q(r), start, end, _filters(r, "batch", self_default=True))


def h_batch(r: Run) -> T.Result:
    f = _filters(r, "batch")
    if not f.batch:
        need_entity(r, "batch")
    q = _q(r)
    if r.parsed.dates or "date" in r.req.parameters:
        return T.qt01_entries_for_date(q, need_date(r, allow_weekday=False), f)
    dow = r.req.parameters.get("day_of_week") or r.parsed.weekday
    if dow:
        return T.qt03_entries_for_weekday(q, dow, f)
    items: list[dict] = []
    for d in range(1, 8):
        items += T.qt03_entries_for_weekday(q, d, f).items
    return T.Result(items, meta={"weekly_view": True})


def h_course(r: Run) -> T.Result:
    f = _filters(r, "course", "batch", "professor")
    if not f.course:
        need_entity(r, "course")
    d = need_date(r, allow_weekday=False) if (r.parsed.dates or "date" in r.req.parameters) else None
    dow = None if d else (r.req.parameters.get("day_of_week") or r.parsed.weekday)
    return T.qt05_find_by_course(_q(r), f, d, dow)


def h_filter_time(r: Run) -> T.Result:
    pr = r.req.parameters
    if "start_time" not in pr and len(r.parsed.times) >= 2:
        s_m, e_m = r.parsed.times[0], r.parsed.times[1]
        rs, re_ = s_m.readings(), e_m.readings()
        valid = [(a, b) for a in rs for b in re_ if a < b]
        if len(valid) != 1:
            raise Clarify("AMPM", f"Which time range do you mean for “{s_m.raw}” to “{e_m.raw}”?", "start_time",
                          [{"label": f"{_fmt(time(*a))} – {_fmt(time(*b))}",
                            "value": {"start_time": time(*a).strftime("%H:%M"), "end_time": time(*b).strftime("%H:%M")}}
                           for a, b in valid[:4]])
        start, end = time(*valid[0][0]), time(*valid[0][1])
    else:
        start = need_time(r, 0, key="start_time", label="start time")
        end = need_time(r, 1, key="end_time", label="end time")
    if end <= start:
        raise Halt(Code.INVALID_REQUEST, "The end time must be after the start time.")
    d = need_date(r, purpose="for that time range")
    return T.qt04_filter_by_time(_q(r), d, start, end, _filters(r, "batch", "course", "professor", "room", self_default=True))


def h_details(r: Run) -> T.Result:
    pr = r.req.parameters
    q = _q(r)
    if "entry_id" in pr:
        res = T.qt06_entry_details(q, pr["entry_id"])
        if not res.items:
            raise Halt(Code.NO_MATCH, "That class was not found in the selected timetable.")
        return res
    f = _filters(r, "course", "batch", "professor", "room", self_default=True)
    has_id = f.course or f.professor or f.room or r.parsed.times or r.parsed.weekday or r.parsed.dates
    if not has_id:
        today = r.ctx.now.date()
        todays = T.qt01_entries_for_date(q, today, f).items
        raise Clarify("ENTITY_CHOICE", "Which class do you mean?", "entry_id",
                      [{"label": f"{i['start_time'] or '?'} {i['course'] or ''} {i['room'] or ''}".strip(),
                        "value": {"entry_id": i["entry_id"]}} for i in todays[:10]])
    rows = q.fetch(q.apply(q.base(), f))
    d = None
    if r.parsed.dates or r.parsed.weekday:
        d = need_date(r)
        rows = [x for x in rows if x.class_date == d or (x.class_date is None and x.day_of_week == d.isoweekday())]
    if r.parsed.times:
        t = need_time(r)
        rows = [x for x in rows if x.start_time and x.end_time and x.start_time <= t < x.end_time]
    if not rows:
        raise Halt(Code.NO_MATCH, "No matching class was found in the selected timetable.")
    if len(rows) > 1:
        def label(x) -> str:
            it = T.serialize_entry(x)
            return " ".join(str(v) for v in (T.DOW.get(x.day_of_week, ""), it["start_time"], it["course"], it["batch"]) if v)

        raise Clarify("ENTITY_CHOICE", "Several classes match. Which one?", "entry_id",
                      [{"label": label(x), "value": {"entry_id": str(x.entry_id)}} for x in rows[:10]])
    return T.qt06_entry_details(q, rows[0].entry_id)


def h_current(r: Run) -> T.Result:
    return T.qt07_current(_q(r), _filters(r, "batch", "professor", "room", self_default=True))


def h_next(r: Run) -> T.Result:
    return T.qt08_next(_q(r), _filters(r, "batch", "course", "professor", "room", self_default=True))


def _section_lunch_end(r: Run, d: date) -> time | None:
    """End of the LONG BREAK / LUNCH printed in the caller's own section(s) of the selected timetable
    that day. Lunch differs between years (e.g. 12:15 for some, 1:15 for others), so the timetable
    itself is preferred over the single institution-wide setting. None when absent or not unique."""
    from sqlalchemy import select

    q = _q(r)
    e = q.m.entry
    sections = select(e.section_id).where(q.base().whereclause, q.on_date(d), e.section_id.is_not(None)).distinct()
    ends = set(r.db.scalars(select(e.end_time).where(
        e.timetable_id == r.ctx.timetable_id, e.entry_kind == "BREAK", e.section_id.in_(sections), q.on_date(d),
        e.time_uncertain.is_(False), e.end_time.is_not(None),
        q.m.course_label.op("~*")(r"(long\s*break|lunch)"),
    )))
    return next(iter(ends)) if len(ends) == 1 else None


def h_after(r: Run) -> T.Result:
    pr = r.req.parameters
    if r.parsed.after_lunch and "time" not in pr:
        cfg = r.db.get(InstitutionConfig, 1)
        section_lunch = None if pr.get("lunch_time") else _section_lunch_end(r, need_date(r, default_today=True))
        boundary = pr.get("lunch_time") or section_lunch or (cfg.lunch_boundary if cfg else None)
        source = "ASKED" if pr.get("lunch_time") else ("TIMETABLE" if section_lunch else "SETTING")
        if boundary is None:
            raise Clarify("CONFIGURATION", "The college has not configured when lunch ends. After what time?", "lunch_time",
                          [{"label": _fmt(time(h, m)), "value": {"lunch_time": f"{h:02d}:{m:02d}"}} for h, m in ((13, 0), (13, 30), (14, 0))])
    else:
        boundary = need_time(r)
    d = need_date(r, default_today=True)
    res = T.qt04_filter_by_time(_q(r), d, boundary, time(23, 59), _filters(r, "batch", "course", "professor", "room", self_default=True),
                                starts_within=True)
    res.meta["boundary"] = boundary.strftime("%H:%M")
    if r.parsed.after_lunch and "time" not in pr:
        res.meta["boundary_source"] = source
    return res


def h_free_check(r: Run) -> T.Result:
    t = need_time(r)
    d = need_date(r, now_ok=True, purpose="for that time")
    f = _filters(r, "professor", "batch", "room", self_default=True)
    end = (datetime.combine(d, t) + timedelta(minutes=1)).time()
    # A professor's free/busy status needs their complete schedule (see policy.SCOPE_FREE_INTENTS);
    # class details outside the caller's own scope are withheld.
    other_prof = bool(f.professor) and r.ctx.domain == Domain.INSTITUTIONAL
    res = T.qt04_filter_by_time(_q(r, scope_free=other_prof), d, t, end, f)
    if other_prof and not institutional_scope(r.ctx.principal).college:
        visible = {i["entry_id"] for i in T.qt04_filter_by_time(_q(r), d, t, end, f).items}
        res.items = [i if i["entry_id"] in visible else {**_busy_only(i)} for i in res.items]
    uncertain = T.uncertain_overlapping(_q(r, scope_free=other_prof), d, t, f)
    status = "SCHEDULED" if res.items else ("UNCERTAIN" if uncertain else "FREE")
    if uncertain and not res.items:
        res.warnings.append({"code": "UNCERTAIN_ENTRY_MAY_OVERLAP",
                             "message": f"{uncertain} class(es) with unverified times might overlap this time."})
    who = _subject(f, "you")
    return T.Result([{"subject": who, "date": d.isoformat(), "time": t.strftime("%H:%M"), "schedule_status": status,
                      "free": status == "FREE", "entries": res.items,
                      "unverified": any(i["verification_status"] != VerificationStatus.VERIFIED for i in res.items)}],
                    result_type="SCHEDULE_STATUS", warnings=res.warnings + [{
                        "code": "FREE_MEANS_UNSCHEDULED",
                        "message": "“Free” means nothing is scheduled in the selected timetable — not confirmed availability."}],
                    meta=res.meta)


def _busy_only(it: dict) -> dict:
    keep = ("entry_id", "kind", "day_of_week", "day_name", "date", "start_time", "end_time", "duration_minutes",
            "verification_status", "time_uncertain", "professor")
    return {k: (it.get(k) if k in keep else None) for k in it} | {"details_withheld": True, "warnings": []}


def h_remaining(r: Run) -> T.Result:
    return T.qt09_remaining_today(_q(r), _filters(r, "batch", "course", "professor", "room", self_default=True))


def h_prof_schedule(r: Run) -> T.Result:
    f = _filters(r, "professor")
    if not f.professor:
        need_entity(r, "professor")
    d = need_date(r, allow_weekday=False) if (r.parsed.dates or "date" in r.req.parameters) else None
    dow = None if d else (r.req.parameters.get("day_of_week") or r.parsed.weekday)
    return T.qt10_professor_schedule(_q(r), f, d, dow)


def h_prof_location(r: Run) -> T.Result:
    f = T.Filters(professor=need_entity(r, "professor"))
    return T.qt11_professor_location(_q(r, scope_free=True), f, _at(r))


def h_prof_courses(r: Run) -> T.Result:
    return T.qt12_professor_courses(_q(r), T.Filters(professor=need_entity(r, "professor")))


def h_prof_free(r: Run) -> T.Result:
    p = r.ctx.principal
    mention = r.req.parameters.get("professor") or r.parsed.professor
    if mention:
        f = T.Filters(professor=need_entity(r, "professor"))
    elif RoleCode.PROFESSOR in p.roles and p.staff_id:
        f = T.Filters(professor=[Candidate(key=f"id:{p.staff_id}", display="you", kind="id")])
    else:
        raise Clarify("MISSING_PARAMETER", "Which professor?", "professor")
    cfg = r.db.get(InstitutionConfig, 1)
    if not cfg or cfg.working_hours_start is None or cfg.working_hours_end is None:
        raise Halt(Code.UNSUPPORTED_INTENT,
                   "Professor free time can't be calculated because the college has not configured working hours.",
                   reason="WORKING_HOURS_NOT_CONFIGURED")
    d = need_date(r, purpose="to check free time")
    return T.qt13_professor_free(_q(r, scope_free=True), f, d)


def h_prof_for_batch(r: Run) -> T.Result:
    f = _filters(r, "batch")
    if not f.batch:
        p = r.ctx.principal
        if r.parsed.self_ref and (r.ctx.domain == Domain.PERSONAL or RoleCode.STUDENT in p.roles):
            f.self_only = True
        else:
            need_entity(r, "batch")
    return T.qt14_professors_for_batch(_q(r), f)


def h_room_schedule(r: Run) -> T.Result:
    f = T.Filters(room=need_entity(r, "room"))
    q = _q(r, scope_free=True)
    if r.parsed.dates or "date" in r.req.parameters:
        return T.qt15_room_schedule(q, f, need_date(r, allow_weekday=False))
    dow = r.req.parameters.get("day_of_week") or r.parsed.weekday
    return T.qt15_room_schedule(q, f, None, dow)


def h_room_day(r: Run) -> T.Result:
    if not (r.parsed.dates or r.parsed.weekday or "date" in r.req.parameters or "day_of_week" in r.req.parameters):
        raise Clarify("MISSING_PARAMETER", "Which day?", "day_of_week",
                      [{"label": T.DOW[i], "value": {"day_of_week": i}} for i in range(1, 7)])
    return h_room_schedule(r)


def h_room_free(r: Run) -> T.Result:
    f = T.Filters(room=need_entity(r, "room"))
    return T.qt16_room_free(_q(r, scope_free=True), f, _at(r))


def _floor(r: Run, required: bool) -> int | None:
    if "floor" in r.req.parameters:
        return r.req.parameters["floor"]
    if r.parsed.floor is not None:
        return r.parsed.floor
    if required:
        raise Clarify("MISSING_PARAMETER", "Which floor?", "floor", [{"label": f"Floor {i}", "value": {"floor": i}} for i in range(0, 8)])
    return None


def h_free_rooms(r: Run) -> T.Result:
    return T.qt17_free_rooms(_q(r, scope_free=True), _at_required(r), _floor(r, False))


def _at_required(r: Run) -> datetime:
    if r.parsed.now and not r.parsed.times and "time" not in r.req.parameters:
        return r.ctx.now
    t = need_time(r)
    d = need_date(r, now_ok=False, purpose="for that time")
    return datetime.combine(d, t, tzinfo=r.ctx.now.tzinfo)


def h_floor(r: Run) -> T.Result:
    floor = _floor(r, True)
    if r.parsed.times or "time" in r.req.parameters:
        return T.qt18_floor_entries(_q(r, scope_free=True), floor, _at_required(r), None)
    if r.parsed.dates or r.parsed.weekday or "date" in r.req.parameters:
        return T.qt18_floor_entries(_q(r, scope_free=True), floor, None, need_date(r))
    return T.qt18_floor_entries(_q(r, scope_free=True), floor, r.ctx.now, None)


def h_rooms_after(r: Run) -> T.Result:
    t = need_time(r)
    d = need_date(r, purpose="for that time")
    return T.qt19_rooms_after(_q(r, scope_free=True), d, t, _floor(r, False))


HANDLERS = {
    "SHOW_MY_TIMETABLE": h_my_timetable, "SHOW_DAY_TIMETABLE": h_day, "SHOW_TIMETABLE_FOR_DATE": h_date,
    "SHOW_WEEK_TIMETABLE": h_week, "SHOW_BATCH_TIMETABLE": h_batch, "FIND_COURSE_CLASSES": h_course,
    "FILTER_CLASSES_BY_TIME": h_filter_time, "SHOW_CLASS_DETAILS": h_details, "CURRENT_CLASS": h_current,
    "NEXT_CLASS": h_next, "CLASSES_AFTER_TIME": h_after, "TIME_UNTIL_NEXT_CLASS": h_next,
    "CHECK_SCHEDULE_FREE": h_free_check, "REMAINING_CLASSES_TODAY": h_remaining, "PROFESSOR_SCHEDULE": h_prof_schedule,
    "PROFESSOR_SCHEDULED_LOCATION": h_prof_location, "PROFESSOR_COURSE": h_prof_courses, "PROFESSOR_FREE_TIME": h_prof_free,
    "PROFESSORS_FOR_BATCH": h_prof_for_batch, "ROOM_SCHEDULE": h_room_schedule, "ROOM_FREE_NOW": h_room_free,
    "FIND_FREE_ROOMS": h_free_rooms, "FLOOR_ACTIVITY": h_floor, "ROOM_SCHEDULE_FOR_DAY": h_room_day,
    "ROOMS_WITH_CLASSES_AFTER_TIME": h_rooms_after,
}


# ======================================================================== messages


def _message(intent: str, res: T.Result, r: Run) -> str:
    n = len(res.items)
    m = res.meta
    when = ""
    if m.get("date"):
        d = date.fromisoformat(m["date"])
        when = "today" if d == r.ctx.now.date() else ("tomorrow" if d == r.ctx.now.date() + timedelta(days=1) else f"on {d:%A %d %b}")
    elif m.get("day_name"):
        when = f"on {m['day_name']}s"
    if intent in ("NEXT_CLASS", "TIME_UNTIL_NEXT_CLASS"):
        if not n:
            return f"No upcoming class in the selected timetable within the next {m.get('lookahead_days', 7)} days."
        it = res.items[0]
        mins = m["minutes_until"]
        hm = f"{mins // 60} h {mins % 60} min" if mins >= 60 else f"{mins} min"
        pr = r.ctx.principal
        if r.ctx.domain == Domain.INSTITUTIONAL and not pr.has(RoleCode.STUDENT, RoleCode.PROFESSOR):
            return f"Next scheduled class{'es' if n > 1 else ''} {when} at {it['start_time']} — starts in {hm}."
        return f"Your next class is {it['course'] or 'a class'} {when} at {it['start_time']}" + (f" in {it['room']}" if it["room"] else "") + f" — starts in {hm}."
    if intent == "CURRENT_CLASS":
        return f"Scheduled now: {res.items[0]['course']}" + (f" in {res.items[0]['room']}" if res.items[0]["room"] else "") + "." if n \
            else "Nothing is scheduled right now in the selected timetable."
    if intent == "PROFESSOR_SCHEDULED_LOCATION":
        if not n:
            return "No class is scheduled for this professor at that time (scheduled location only — not real-time tracking)."
        it = res.items[0]
        return f"{it['professor']} is scheduled in {it['room'] or 'an unrecorded room'} for {it['course']} ({it['start_time']}–{it['end_time']}). This is the scheduled location, not real-time tracking."
    if intent == "CHECK_SCHEDULE_FREE":
        it = res.items[0]
        return {"FREE": f"Nothing scheduled for {it['subject']} at {it['time']} on {it['date']} in the selected timetable.",
                "SCHEDULED": f"{'You have' if it['subject'] == 'you' else it['subject'] + ' has'} a scheduled class at {it['time']} on {it['date']}.",
                "UNCERTAIN": "Can't confirm: some classes that day have unverified times."}[it["schedule_status"]]
    if intent == "ROOM_FREE_NOW":
        it = res.items[0]
        return {"NO_SCHEDULED_CLASS": f"Room {it['room']} has no class scheduled at {it['time']} (scheduled use only, not physical occupancy).",
                "SCHEDULED": f"Room {it['room']} has a class scheduled at {it['time']}.",
                "UNCERTAIN": f"Room {it['room']} can't be confirmed free — some classes there have unverified times."}[it["scheduled_status"]]
    if intent == "FIND_FREE_ROOMS":
        return f"{n} room(s) have no class scheduled at {m['time']} on {m['date']}." if n else "No rooms are confirmed free at that time."
    if intent == "PROFESSOR_FREE_TIME":
        return f"{n} free interval(s) within working hours {m['working_hours']} on {m['date']}." if n else "No free time within working hours that day."
    if intent == "PROFESSORS_FOR_BATCH":
        return f"{n} professor(s) teach this batch in the selected timetable." if n else "No professors found for this batch in the selected timetable."
    if intent == "PROFESSOR_COURSE":
        return f"{n} course(s) found for this professor." if n else "No courses found for this professor in the selected timetable."
    if intent == "ROOMS_WITH_CLASSES_AFTER_TIME":
        return f"{n} room(s) have classes after {m['after']} on {m['date']}." if n else "No rooms have classes after that time."
    if intent == "REMAINING_CLASSES_TODAY":
        return f"You have {n} class(es) remaining today." if n else "No more classes today in the selected timetable."
    if intent == "FLOOR_ACTIVITY":
        at = f" at {m['time']}" if m.get("time") else ""
        return f"{n} class(es) scheduled on floor {m['floor']} {when}{at}." if n else f"Nothing scheduled on floor {m['floor']} {when}{at}."
    if intent == "SHOW_CLASS_DETAILS":
        return "Class details."
    if not n:
        return f"No classes found {when}".strip() + " in the selected timetable."
    return f"{n} class(es) {when}".strip() + "."


# ======================================================================== main entry point


def _is_unverified(items: list[dict]) -> bool:
    for it in items:
        if it.get("unverified") or it.get("time_uncertain") or it.get("verification_status") not in (None, VerificationStatus.VERIFIED):
            return True
        if any(_is_unverified([e]) for e in it.get("entries", [])):
            return True
    return False


def _paginate(items: list, req: Request) -> tuple[list, dict | None]:
    if len(items) <= req.limit and req.cursor == 0:
        return items, None
    page = items[req.cursor: req.cursor + req.limit]
    nxt = req.cursor + req.limit
    return page, {"limit": req.limit, "total": len(items), "next_cursor": str(nxt) if nxt < len(items) else None}


def search(db: Session, p: Principal, req: Request) -> tuple[int, dict]:
    started = _time.perf_counter()
    status_code, env = _search(db, p, req)
    elapsed = int((_time.perf_counter() - started) * 1000)
    env["meta"]["duration_ms"] = elapsed
    try:
        _record(db, p, req, env, elapsed)
    except Exception:  # noqa: BLE001 — history must never break search
        db.rollback()
        log.exception("search history write failed")
    log.info("search", extra={"user_id": str(p.user_id), "intent": env["intent"], "result_status": env["status"],
                              "domain": (env.get("context") or {}).get("domain"),
                              "timetable_id": (env.get("context") or {}).get("timetable_id"), "duration_ms": elapsed})
    return status_code, env


def _record(db: Session, p: Principal, req: Request, env: dict, elapsed: int) -> None:
    if not req.query:
        return
    pref = get_or_create_preferences(db, p.user_id)
    if pref.search_history_enabled:
        db.add(SearchHistory(user_id=p.user_id, query_text=req.query[:300], intent=env["intent"], status=env["status"],
                             domain=(env.get("context") or {}).get("domain") or (req.domain or "INSTITUTIONAL").upper()[:20],
                             duration_ms=elapsed))
    db.commit()


def _search(db: Session, p: Principal, req: Request) -> tuple[int, dict]:
    try:
        req.parameters = _validate_params(req.parameters or {})
    except Halt as h:
        return HTTP_STATUS[h.code], envelope(h.code, message=h.message, details=h.details)
    if req.intent and req.intent not in INTENTS:
        return 422, envelope(Code.UNSUPPORTED_INTENT, message="That operation is not in the approved intent catalogue.")
    if not req.query and not req.intent:
        return 400, envelope(Code.INVALID_REQUEST, message="Provide a query or a registered intent.")
    if req.query and len(req.query) > 300:
        return 400, envelope(Code.INVALID_REQUEST, message="Queries are limited to 300 characters.")

    tz_today = Clock.now(p.timezone_id).date()
    parsed = nlp.parse(req.query or "", tz_today)

    # Q30 is rejected before *any* timetable is resolved or queried.
    pre = req.intent or next((name for name, rx in nlp._RULES if rx.search(parsed.norm)), None)
    if pre == "CROSS_DOMAIN_COMPARE":
        return 422, envelope(Code.UNSUPPORTED_INTENT, intent="CROSS_DOMAIN_COMPARE",
                             message="Comparing your personal and college timetables isn't supported in this version. "
                                     "Switch views to look at each one separately.")
    try:
        domain = parse_domain(req.domain) if req.domain else None
    except AppError as e:
        return e.http_status, envelope(e.code, message=e.message)

    if pre in META_INTENTS:
        return _meta(db, p, req, parsed, pre, domain)

    try:
        ctx = resolve_context(db, p, domain, req.selection)
        db.commit()
    except AppError as e:
        return e.http_status, envelope(e.code, intent=req.intent, message=e.message, details=e.details,
                                       context={"domain": (domain or Domain.INSTITUTIONAL).value})

    r = Run(db, ctx, req, parsed, warnings=list(ctx.warnings))
    try:
        r.vocab = load_vocab(db, ctx)
        found = scan(parsed.norm, r.vocab)
        for kind in ("professor", "course", "batch", "room"):
            if getattr(parsed, kind) is None and kind in found:
                setattr(parsed, kind, found[kind])
        archive_wrapped = parsed.archive_modifier
        intent = req.intent or nlp.classify(
            parsed, has_professor=bool(parsed.professor or "professor" in req.parameters),
            has_room=bool(parsed.room or "room" in req.parameters), has_batch=bool(parsed.batch or "batch" in req.parameters),
            has_course=bool(parsed.course or "course" in req.parameters),
            has_floor=parsed.floor is not None or "floor" in req.parameters)
        if intent == "SEARCH_SELECTED_ARCHIVE":
            archive_wrapped, intent = True, None
        if archive_wrapped and ctx.selection_type != SelectionType.EXPLICIT_ARCHIVE:
            rows, _ = list_timetables(db, p, ctx.domain, 20, 0)
            raise Clarify("SELECT_ARCHIVE", "Which archived timetable should I search? Select one first.", "selection",
                          [{"label": t.title, "value": {"selection": {"type": "EXPLICIT_ARCHIVE", "timetable_id": str(t.timetable_id)}}}
                           for t in rows if t.processing_status in ("READY", "NEEDS_REVIEW")
                          and t.timetable_id != primary_id(db, p, ctx.domain)])
        if intent is None:
            if archive_wrapped:
                tt = serialize_timetable(ctx.timetable, ctx.domain, primary_id(db, p, ctx.domain))
                return 200, envelope(Code.OK, intent="SEARCH_SELECTED_ARCHIVE", ctx=ctx, result_type="TIMETABLE", results=[tt],
                                     message=f"Searching the archived timetable “{ctx.timetable.title}”. Ask about classes, days, rooms or professors.",
                                     warnings=r.warnings)
            return 422, envelope(Code.UNSUPPORTED_INTENT, ctx=ctx,
                                 message="I couldn't match that to a supported timetable question. Try one of the examples.",
                                 details={"examples": nlp.EXAMPLES})
        r.intent = intent
        spec = INTENTS[intent]
        if ctx.domain not in spec.domains:
            raise Halt(Code.UNSUPPORTED_INTENT, spec.personal_unsupported_reason or "This question isn't supported in this view.",
                       reason="DOMAIN_NOT_SUPPORTED")
        if ctx.domain == Domain.INSTITUTIONAL:
            if not intent_allowed(p, intent):
                raise Halt(Code.ACCESS_DENIED, "Your role does not have access to this kind of monitoring query.")
            scope = institutional_scope(p)
            if scope.is_empty and intent not in SCOPE_FREE_INTENTS:
                raise Clarify("SETUP_REQUIRED", scope.reason_if_empty or "Your account setup is incomplete.")
        res = HANDLERS[intent](r)
        warnings = r.warnings + res.warnings
        items, pagination = _paginate(res.items, req)
        if not res.items and res.result_type not in ("ROOM_STATUS", "SCHEDULE_STATUS"):
            status = Code.NO_MATCH
        elif _is_unverified(res.items):
            status = Code.DATA_UNVERIFIED
            warnings.append({"code": "CONTAINS_UNVERIFIED",
                             "message": "Some results come from unverified or uncertain extraction; check marked fields."})
        else:
            status = Code.OK
        result_intent = "SEARCH_SELECTED_ARCHIVE" if archive_wrapped else intent
        meta = {**res.meta, **({"inner_intent": intent} if archive_wrapped else {})}
        return 200, envelope(status, intent=result_intent, ctx=ctx, message=_message(intent, res, r), warnings=warnings,
                             results=items, result_type=res.result_type, meta=meta, pagination=pagination)
    except Clarify as c:
        return 422, envelope(Code.CLARIFICATION_REQUIRED, intent=r.intent, ctx=ctx, message=c.payload["question"],
                             clarification=c.payload, warnings=r.warnings)
    except Halt as h:
        status = HTTP_STATUS[h.code]
        return status, envelope(h.code, intent=r.intent, ctx=ctx, message=h.message, details=h.details, warnings=r.warnings,
                                result_type="ENTRIES" if h.code == Code.NO_MATCH else None)
    except AppError as e:
        return e.http_status, envelope(e.code, intent=r.intent, ctx=ctx, message=e.message, details=e.details)


def _meta(db: Session, p: Principal, req: Request, parsed: nlp.Parsed, intent: str, domain: Domain | None) -> tuple[int, dict]:
    """Q27 / Q28 / Q29 operate on archive metadata; they must work even with no usable primary."""
    pref = get_or_create_preferences(db, p.user_id)
    d = domain or (Domain(pref.last_active_domain) if pref.last_active_domain else Domain.INSTITUTIONAL)
    context = {"domain": d.value, "timezone": p.timezone_id}
    pid = primary_id(db, p, d)
    try:
        if intent == "LIST_TIMETABLE_ARCHIVES":
            rows, total = list_timetables(db, p, d, req.limit, req.cursor)
            items = [serialize_timetable(t, d, pid, include_summary=False) for t in rows]
            nxt = req.cursor + req.limit
            return 200, envelope(Code.OK if items else Code.NO_MATCH, intent=intent, context=context, result_type="TIMETABLES",
                                 results=items, message=f"{total} timetable(s) in the {d.value.lower()} view.",
                                 pagination={"limit": req.limit, "total": total, "next_cursor": str(nxt) if nxt < total else None})
        if intent == "SHOW_PRIMARY_TIMETABLE":
            if pid is None:
                return 422, envelope(Code.NO_TIMETABLE_SELECTED, intent=intent, context=context,
                                     message="No primary timetable is set in this view." + (
                                         " Upload one or choose from your archive." if d == Domain.PERSONAL else ""))
            tt = get_timetable(db, p, d, pid)
            return 200, envelope(Code.OK, intent=intent, context=context, result_type="TIMETABLE",
                                 results=[serialize_timetable(tt, d, pid)], message=f"The primary {d.value.lower()} timetable is “{tt.title}”.")
        # MAKE_TIMETABLE_PRIMARY (QT22) — state-changing: explicit confirmation required.
        if d == Domain.INSTITUTIONAL and not p.is_admin:
            return 403, envelope(Code.ACCESS_DENIED, intent=intent, context=context,
                                 message="Only an Admin can change the official institutional timetable.")
        target = req.parameters.get("timetable_id") or ((req.selection or {}).get("timetable_id"))
        if not target:
            rows, _ = list_timetables(db, p, d, 20, 0)
            eligible = [t for t in rows if t.processing_status in ("READY", "NEEDS_REVIEW") and t.timetable_id != pid]
            raise Clarify("ENTITY_CHOICE", "Which timetable should become primary?", "timetable_id",
                          [{"label": t.title, "value": {"timetable_id": str(t.timetable_id)}} for t in eligible])
        tt = get_timetable(db, p, d, target)
        if not req.parameters.get("confirm"):
            raise Clarify("CONFIRMATION", f"Make “{tt.title}” the primary {d.value.lower()} timetable? This changes only the "
                          f"{d.value.lower()} view.", "confirm",
                          [{"label": "Yes, make it primary", "value": {"confirm": True, "timetable_id": str(tt.timetable_id)}},
                           {"label": "Cancel", "value": None}])
        out = set_primary(db, p, d, tt.timetable_id)
        return 200, envelope(Code.OK, intent=intent, context=context, result_type="ACTION", results=[out],
                             message=f"“{tt.title}” is now the primary {d.value.lower()} timetable.")
    except Clarify as c:
        return 422, envelope(Code.CLARIFICATION_REQUIRED, intent=intent, context=context, message=c.payload["question"],
                             clarification=c.payload)
    except AppError as e:
        return e.http_status, envelope(e.code, intent=intent, context=context, message=e.message, details=e.details)
