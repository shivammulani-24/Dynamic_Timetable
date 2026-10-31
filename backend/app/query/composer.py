"""Composed executor (template QT23): compiles a `QueryPlan` into the shared building blocks of
`templates.Q` and computes the requested operation.

Security is unchanged: every query starts from `Q.base()`, which fixes the selected timetable and
domain and ANDs in the caller's role scope; filters are typed values resolved against this
timetable's vocabulary; all values are bound parameters. Aggregation (count, hours, first/last,
per-day summaries) is done in Python over those already-scoped rows.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from sqlalchemy import and_

from app.query import engine as E
from app.query import templates as T
from app.query.planner import QueryPlan

_LAB_RX = re.compile(r"\b(lab|labs|laboratory|practicals?)\b|\(lab\)", re.I)


def is_lab(it: dict) -> bool:
    return bool(_LAB_RX.search(f"{it.get('course') or ''} {it.get('course_code') or ''}"))


def _kind_ok(it: dict, kind: str | None) -> bool:
    if kind is None:
        return True
    return is_lab(it) if kind == "LAB" else not is_lab(it)


def _noun(plan: QueryPlan, n: int | None = None) -> str:
    base = {"LAB": ("lab", "labs"), "LECTURE": ("lecture", "lectures")}.get(plan.kind, ("class", "classes"))
    return base[0] if n == 1 else base[1]


def _hm(t: str | None) -> str:
    return E._fmt(datetime.strptime(t, "%H:%M").time()) if t else "?"


def _minutes(a: str, b: str) -> int:
    ta, tb = datetime.strptime(a, "%H:%M"), datetime.strptime(b, "%H:%M")
    return int((tb - ta).total_seconds() // 60)


# ------------------------------------------------------------------ which days

class _Day:
    __slots__ = ("date", "dow")

    def __init__(self, d: date | None, dow: int):
        self.date, self.dow = d, dow

    @property
    def label(self) -> str:
        return f"{self.date:%a %d %b}" if self.date else T.DOW[self.dow]


def _days(r: "E.Run", plan: QueryPlan) -> tuple[list[_Day], str]:
    """Days the plan covers and a phrase for messages ("today", "on Mondays", "this week" …)."""
    p, pr, today = r.parsed, r.req.parameters, r.ctx.now.date()
    if ("start_date" in pr and "end_date" in pr) or p.week_ref or len(p.dates) >= 2:
        start, end = E._week_range(r)
        days = [_Day(start + timedelta(days=i), (start + timedelta(days=i)).isoweekday()) for i in range((end - start).days + 1)]
        phrase = "next week" if p.week_ref == "next" else ("this week" if p.week_ref else f"from {start:%d %b} to {end:%d %b}")
        return days, phrase
    if p.dates or "date" in pr or p.date_ambiguous_raw:
        d = E.need_date(r, allow_weekday=False)
        return [_Day(d, d.isoweekday())], _date_phrase(d, today)
    dow = pr.get("day_of_week") or p.weekday
    if dow:
        return [_Day(None, dow)], f"on {T.DOW[dow]}s"
    if p.now or plan.operation in ("FIRST", "LAST") or (plan.window and plan.operation in ("LIST", "EXISTS", "COUNT")):
        return [_Day(today, today.isoweekday())], "today"
    return [_Day(None, d) for d in range(1, 8)], "in the weekly timetable"


def _with_window(when: str, plan: QueryPlan, wmeta: dict) -> str:
    if plan.window == "AFTER_LUNCH" and wmeta.get("boundary"):
        return f"after lunch ({_hm(wmeta['boundary'])}) {when}"
    if plan.window in ("AFTER", "BEFORE", "AT") and wmeta.get("time"):
        return f"{plan.window.lower()} {_hm(wmeta['time'])} {when}"
    if plan.window == "BETWEEN" and wmeta.get("start_time"):
        return f"between {_hm(wmeta['start_time'])} and {_hm(wmeta['end_time'])} {when}"
    return when


def _about(f: T.Filters) -> str:
    """What the answer is about, besides the person: "of DBMS", "for TE-B4", "in room 508"."""
    if f.course:
        return f"of {f.course[0].display}"
    if f.batch:
        return f"for {f.batch[0].display}"
    if f.room:
        return f"in room {f.room[0].display}"
    return ""


def _date_phrase(d: date, today: date) -> str:
    if d == today:
        return "today"
    if d == today + timedelta(days=1):
        return "tomorrow"
    return f"on {d:%A %d %b}"


# ------------------------------------------------------------------ time window

def _window(r: "E.Run", plan: QueryPlan):
    """Returns (condition builder per day, meta) for the plan's time window, or (None, {})."""
    if plan.window is None:
        return None, {}
    e = T.models_for(r.ctx.domain).entry
    if plan.window == "BETWEEN":
        s, en = E._time_range(r)
        return (lambda d, lunch=None: and_(e.start_time < en, e.end_time > s)), {"start_time": s.strftime("%H:%M"), "end_time": en.strftime("%H:%M")}
    if plan.window == "AFTER_LUNCH":
        return "AFTER_LUNCH", {}
    t = E.need_time(r)
    meta = {"time": t.strftime("%H:%M")}
    if plan.window == "AFTER":
        return (lambda d, lunch=None: e.start_time >= t), meta
    if plan.window == "BEFORE":
        return (lambda d, lunch=None: e.start_time < t), meta
    return (lambda d, lunch=None: and_(e.start_time <= t, e.end_time > t)), meta


def _lunch_date(day: _Day, today: date) -> date:
    return day.date or E._next_occurrence(today, day.dow)


# ------------------------------------------------------------------ executor

def run(r: "E.Run", plan: QueryPlan) -> T.Result:
    f = E._filters(r, "batch", "course", "professor", "room", self_default=True)
    q = E._q(r)
    if plan.operation == "NEXT":
        return _next(r, q, f, plan)
    days, when = _days(r, plan)
    cond, wmeta = _window(r, plan)
    e = q.m.entry
    timed = bool(plan.window) or plan.operation in ("FIRST", "LAST", "TOTAL_HOURS", "PER_DAY")
    excluded = 0
    per_day: list[tuple[_Day, list[dict]]] = []
    for day in days:
        base = q.apply(q.base().where(q.on_date(day.date) if day.date else q.on_dow(day.dow)), f)
        if timed:
            excluded += q.excluded_count(base)
            base = base.where(q.time_ok())
        if cond == "AFTER_LUNCH":
            boundary, source = E._lunch_boundary(r, _lunch_date(day, r.ctx.now.date()))
            wmeta = {"boundary": boundary.strftime("%H:%M"), "boundary_source": source}
            base = base.where(e.start_time >= boundary)
        elif cond is not None:
            base = base.where(cond(day))
        items = [it for it in q.items(q.fetch(base), day.date) if _kind_ok(it, plan.kind)]
        per_day.append((day, items))

    warnings = T._excluded_warning(excluded)
    if len(days) == 1 and days[0].date:
        warnings += T._effective_warning(r.ctx, days[0].date)
    meta = {"plan": plan.as_dict(), "when": when, **wmeta}
    when = _with_window(when, plan, wmeta)
    who = f.professor[0].display if f.professor else "you"
    about = _about(f)
    if about and plan.unit != "BATCHES":
        when = f"{about} {when}"
    op = plan.operation
    if op in ("FIRST", "LAST") and len(days) > 1:
        op, plan.metric = "PER_DAY", plan.metric or ("FIRST_START" if op == "FIRST" else "LAST_END")
    if op in ("LIST", "EXISTS"):
        return _list(plan, per_day, who, when, meta, warnings, op)
    if op == "COUNT":
        return _count(plan, per_day, who, when, meta, warnings)
    if op == "TOTAL_HOURS":
        return _hours(plan, per_day, who, when, meta, warnings)
    if op in ("FIRST", "LAST"):
        return _first_last(plan, per_day[0][1], who, when, meta, warnings, op)
    return _per_day(plan, per_day, who, when, meta, warnings)


# ------------------------------------------------------------------ operations

def _slots(items: list[dict]) -> dict[tuple, list[dict]]:
    """Parallel entries in the same period (lab groups, elective options) form one time slot."""
    out: dict[tuple, list[dict]] = {}
    for it in items:
        out.setdefault((it.get("date") or it.get("day_of_week"), it["start_time"], it["end_time"]), []).append(it)
    return out


def _busy_minutes(items: list[dict]) -> int:
    spans = sorted((it["start_time"], it["end_time"]) for it in items if it.get("start_time") and it.get("end_time"))
    total, cur_s, cur_e = 0, None, None
    for s, e in spans:
        if cur_e is None or s >= cur_e:
            if cur_e is not None:
                total += _minutes(cur_s, cur_e)
            cur_s, cur_e = s, e
        elif e > cur_e:
            cur_e = e
    if cur_e is not None:
        total += _minutes(cur_s, cur_e)
    return total


def _has(who: str) -> str:
    return "You have" if who == "you" else f"{who} has"


def _parallel_warning(items: list[dict]) -> list[dict]:
    extra = len(items) - len(_slots(items))
    if extra <= 0:
        return []
    return [{"code": "PARALLEL_COUNTED_ONCE",
             "message": f"{extra} parallel option(s) in the same period (lab groups or electives) were counted once."}]


def _list(plan, per_day, who, when, meta, warnings, op) -> T.Result:
    items = [it for _, its in per_day for it in its]
    n = len(_slots(items))
    noun = _noun(plan, n)
    if op == "EXISTS":
        msg = (f"Yes — {_has(who).lower()} {n} {noun} {when}." if n
               else f"No — {'you have' if who == 'you' else who + ' has'} no {_noun(plan, 2)} {when} in the selected timetable.")
    else:
        msg = f"{n} {noun} {when}." if n else f"No {_noun(plan, 2)} found {when} in the selected timetable."
    meta["message"] = msg
    return T.Result(items, warnings=warnings, meta=meta)


def _breakdown(per_day) -> list[dict]:
    return [{"day": d.label, "date": d.date.isoformat() if d.date else None, "value": len(_slots(its))}
            for d, its in per_day if its]


_COURSE_SUFFIX = re.compile(r"\s*\((lab|batch\s*\d+|batch\d+)\)\s*$", re.I)


def _course_name(it: dict) -> str:
    name = it.get("course") or it.get("course_code") or "?"
    while _COURSE_SUFFIX.search(name):
        name = _COURSE_SUFFIX.sub("", name)
    return name.strip()


def _count(plan, per_day, who, when, meta, warnings) -> T.Result:
    items = [it for _, its in per_day for it in its]
    if plan.unit == "BATCHES":
        names = sorted({it.get("batch") for it in items if it.get("batch")})
        n = len(names)
        verb = "You teach" if who == "you" else f"{who} teaches"
        meta["message"] = f"{verb} {n} batch(es) {when}" + (f": {', '.join(names[:10])}." if names else ".")
        item = {"metric": "COUNT", "value": n, "unit": "batches", "label": f"Batches {when}", "breakdown": [],
                "labels": names, "entries": []}
        return T.Result([item], result_type="AGGREGATE", warnings=warnings, meta=meta)
    if plan.unit == "COURSES":
        names = sorted({_course_name(it) for it in items})
        n = len(names)
        meta["message"] = f"{_has(who)} {n} subject(s) {when}."
        item = {"metric": "COUNT", "value": n, "unit": "subjects", "label": f"Subjects {when}", "breakdown": [],
                "labels": names, "entries": []}
        return T.Result([item], result_type="AGGREGATE", warnings=warnings, meta=meta)
    n = len(_slots(items))
    meta["message"] = f"{_has(who)} {n} {_noun(plan, n)} {when}."
    item = {"metric": "COUNT", "value": n, "unit": _noun(plan, n), "label": f"{_noun(plan, 2).capitalize()} {when}",
            "breakdown": _breakdown(per_day) if len(per_day) > 1 else [], "entries": items}
    return T.Result([item], result_type="AGGREGATE", warnings=warnings + _parallel_warning(items), meta=meta)


def _hours(plan, per_day, who, when, meta, warnings) -> T.Result:
    items = [it for _, its in per_day for it in its]
    minutes = sum(_busy_minutes(its) for _, its in per_day)
    hours = round(minutes / 60, 1)
    shown = int(hours) if hours == int(hours) else hours
    meta["message"] = f"{_has(who)} {shown} hour(s) of {_noun(plan, 2)} {when}."
    breakdown = [{"day": d.label, "date": d.date.isoformat() if d.date else None, "value": round(_busy_minutes(its) / 60, 1)}
                 for d, its in per_day if its] if len(per_day) > 1 else []
    item = {"metric": "HOURS", "value": shown, "unit": "hours", "label": f"Hours of {_noun(plan, 2)} {when}",
            "breakdown": breakdown, "entries": items}
    return T.Result([item], result_type="AGGREGATE", warnings=warnings, meta=meta)


def _first_last(plan, items, who, when, meta, warnings, op) -> T.Result:
    if not items:
        meta["message"] = f"No {_noun(plan, 2)} {when} in the selected timetable."
        return T.Result([], warnings=warnings, meta=meta)
    if op == "FIRST":
        key = min(it["start_time"] for it in items)
        chosen = [it for it in items if it["start_time"] == key]
        it = chosen[0]
        msg = (f"{'Your' if who == 'you' else who + chr(39) + 's'} first {_noun(plan, 1)} {when} starts at {_hm(it['start_time'])}: "
               f"{it['course'] or 'a class'}" + (f" in {it['room']}" if it.get("room") else "") + ".")
    else:
        key = max(it["end_time"] for it in items)
        chosen = [it for it in items if it["end_time"] == key]
        it = chosen[0]
        msg = (f"{'Your' if who == 'you' else who + chr(39) + 's'} last {_noun(plan, 1)} {when} is {it['course'] or 'a class'} "
               f"({_hm(it['start_time'])}–{_hm(it['end_time'])})" + (f" in {it['room']}" if it.get("room") else "")
               + f" — done at {_hm(it['end_time'])}.")
    meta["message"] = msg
    return T.Result(chosen, warnings=warnings, meta=meta)


def _per_day(plan, per_day, who, when, meta, warnings) -> T.Result:
    rows = []
    for d, its in per_day:
        if not its:
            continue
        rows.append({"day": d.label, "day_of_week": d.dow, "date": d.date.isoformat() if d.date else None,
                     "classes": len(_slots(its)), "labs": len(_slots([i for i in its if is_lab(i)])),
                     "hours": round(_busy_minutes(its) / 60, 1),
                     "first_start": min(i["start_time"] for i in its if i.get("start_time")) if any(i.get("start_time") for i in its) else None,
                     "last_end": max(i["end_time"] for i in its if i.get("end_time")) if any(i.get("end_time") for i in its) else None})
    free_days = [d.label for d, its in per_day if not its and d.dow <= 6]
    metric = plan.metric or "CLASSES"
    field = {"CLASSES": "classes", "HOURS": "hours", "FIRST_START": "first_start", "LAST_END": "last_end"}[metric]
    sort = plan.sort
    if sort:
        desc = sort in ("MOST", "LATEST")
        present = [x for x in rows if x[field] is not None]
        missing = [x for x in rows if x[field] is None]
        present.sort(key=lambda x: (x[field], -x["day_of_week"] if desc else x["day_of_week"]), reverse=desc)
        rows = present + missing
    for row in rows:
        row["metric"] = metric
    if not rows:
        meta["message"] = f"No {_noun(plan, 2)} {when} in the selected timetable."
        return T.Result([], warnings=warnings, meta=meta)
    top = rows[0]
    if sort:
        what = {"CLASSES": f"{top['classes']} {_noun(plan, top['classes'])}", "HOURS": f"{top['hours']} hour(s)",
                "FIRST_START": f"starts at {_hm(top['first_start'])}", "LAST_END": f"done at {_hm(top['last_end'])}"}[metric]
        label = {("CLASSES", "MOST"): "Busiest day", ("CLASSES", "LEAST"): "Lightest day", ("HOURS", "MOST"): "Longest day",
                 ("HOURS", "LEAST"): "Shortest day", ("FIRST_START", "EARLIEST"): "Earliest start",
                 ("FIRST_START", "LATEST"): "Latest start", ("LAST_END", "EARLIEST"): "Earliest finish",
                 ("LAST_END", "LATEST"): "Latest finish"}.get((metric, sort), "Top day")
        msg = f"{label}: {top['day']} ({what})."
    else:
        msg = f"Day-wise summary {when} ({len(rows)} day(s) with {_noun(plan, 2)})."
    if free_days and metric == "CLASSES":
        msg += f" No {_noun(plan, 2)} on {', '.join(free_days)}."
    meta["message"] = msg
    return T.Result(rows, result_type="DAY_SUMMARY", warnings=warnings, meta=meta)


def _next(r, q, f, plan) -> T.Result:
    """Next class of the requested kind: today after now, then following days (same look-ahead as QT08)."""
    now = r.ctx.now
    t = now.time().replace(tzinfo=None)
    e = q.m.entry
    days = T._lookahead(r.db)
    meta = {"plan": plan.as_dict(), "lookahead_days": days}
    for offset in range(0, days + 1):
        d = now.date() + timedelta(days=offset)
        qq = q.apply(q.base().where(q.on_date(d)), f).where(q.time_ok())
        if offset == 0:
            qq = qq.where(e.start_time > t)
        items = [it for it in q.items(q.fetch(qq), d) if _kind_ok(it, plan.kind)]
        if items:
            first = min(it["start_time"] for it in items)
            same = [it for it in items if it["start_time"] == first]
            start_dt = datetime.combine(d, datetime.strptime(first, "%H:%M").time(), tzinfo=now.tzinfo)
            minutes = int((start_dt - now).total_seconds() // 60)
            for it in same:
                it["minutes_until"] = minutes
            hm = f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"
            it = same[0]
            meta.update({"date": d.isoformat(), "minutes_until": minutes,
                         "message": f"Your next {_noun(plan, 1)} is {it['course'] or 'a class'} {_date_phrase(d, now.date())} at "
                                    f"{_hm(first)}" + (f" in {it['room']}" if it.get("room") else "") + f" — starts in {hm}."})
            return T.Result(same, warnings=T._effective_warning(r.ctx, d), meta=meta)
    meta["message"] = f"No upcoming {_noun(plan, 1)} in the selected timetable within the next {days} days."
    return T.Result([], meta=meta)


def count_of(res: T.Result, specialised: str, plan: QueryPlan) -> T.Result:
    """COUNT over what a specialised operation returned (rooms, professors, courses, free slots)."""
    unit = {"FIND_FREE_ROOMS": "free room(s)", "ROOMS_WITH_CLASSES_AFTER_TIME": "room(s)", "PROFESSORS_FOR_BATCH": "professor(s)",
            "PROFESSOR_COURSE": "course(s)", "FLOOR_ACTIVITY": "class(es)", "PROFESSOR_FREE_TIME": "free period(s)"}[specialised]
    labels = [it.get("room") or it.get("professor") or it.get("course")
              or (f"{_hm(it['start_time'])}–{_hm(it['end_time'])}" if it.get("start_time") and it.get("end_time") else None)
              for it in res.items]
    n = len(res.items)
    item = {"metric": "COUNT", "value": n, "unit": unit, "label": unit.capitalize(), "breakdown": [],
            "labels": [x for x in labels if x], "entries": res.items if res.result_type == "ENTRIES" else []}
    meta = {**res.meta, "plan": plan.as_dict(), "message": f"{n} {unit}."}
    return T.Result([item], result_type="AGGREGATE", warnings=res.warnings, meta=meta)
