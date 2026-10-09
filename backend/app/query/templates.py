"""Approved query templates QT01–QT22 (API Contract §9).

Rules applied by every template:
* `timetable_id == ctx.timetable_id` (server-resolved) and only the active domain's entry table.
* Role scope (institutional) is ANDed in unless the intent is facility-only (rooms).
* All values are bound parameters — user text never becomes SQL.
* Interval convention: start inclusive, end exclusive (D-02).
* Time-sensitive templates exclude entries whose time is missing/uncertain and report how many.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.orm import Session

from app.enums import Domain, EntryKind, RoleCode, VerificationStatus
from app.models import InstitutionConfig, Room
from app.security.policy import institutional_scope
from app.services.context import SearchContext
from app.services.domains import models_for
from app.services.entries import scope_condition, serialize_entry
from app.services.matching import Candidate

DOW = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}


@dataclass
class Filters:
    course: list[Candidate] = field(default_factory=list)
    professor: list[Candidate] = field(default_factory=list)
    batch: list[Candidate] = field(default_factory=list)
    room: list[Candidate] = field(default_factory=list)
    self_only: bool = False


@dataclass
class Result:
    items: list[dict]
    result_type: str = "ENTRIES"
    warnings: list[dict] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


def _norm_sql(col):
    return func.regexp_replace(func.lower(col), "[^0-9a-z]", "", "g")


class Q:
    def __init__(self, db: Session, ctx: SearchContext, *, scope_free: bool = False):
        self.db, self.ctx = db, ctx
        self.m = models_for(ctx.domain)
        self.scope_free = scope_free

    # ---------------------------------------------------------------- building blocks
    def base(self, *, classes_only: bool = True):
        e = self.m.entry
        q = select(e).where(e.timetable_id == self.ctx.timetable_id, e.verification_status != VerificationStatus.REJECTED)
        if classes_only:
            q = q.where(e.entry_kind == EntryKind.CLASS)
        if self.ctx.domain == Domain.INSTITUTIONAL and not self.scope_free:
            cond = scope_condition(institutional_scope(self.ctx.principal), self.ctx.timetable, e)
            if cond is not None:
                q = q.where(cond)
        return q

    def on_date(self, d: date):
        e = self.m.entry
        return or_(e.class_date == d, and_(e.class_date.is_(None), e.day_of_week == d.isoweekday()))

    def on_dow(self, dow: int):
        return self.m.entry.day_of_week == dow

    def time_ok(self):
        e = self.m.entry
        return and_(e.time_uncertain.is_(False), e.start_time.is_not(None), e.end_time.is_not(None), e.day_of_week.is_not(None))

    def _cand_cond(self, kind: str, c: Candidate):
        e = self.m.entry
        typ, key = c.key.split(":", 1)
        label_col = {"course": self.m.course_label, "professor": self.m.staff_label, "batch": self.m.batch_label, "room": self.m.room_label}[kind]
        if typ == "id":
            id_col = {"course": "course_id", "professor": "staff_id", "batch": "batch_id", "room": "room_id"}[kind]
            conds = [getattr(e, id_col) == (key if kind == "professor" else int(key))]
        else:
            conds = [_norm_sql(label_col) == key]
        if kind == "professor":  # co-taught cells ("KKD+AVN") are not mapped to a single staff id
            for code in c.extra.get("codes", []):
                up = code.upper()
                conds += [func.upper(label_col).like(f"{up}+%"), func.upper(label_col).like(f"%+{up}"),
                          func.upper(label_col).like(f"%+{up}+%")]
        if kind == "batch" and typ == "id":
            from app.models import Batch

            child_ids = select(Batch.batch_id).where(Batch.parent_batch_id == int(key))
            conds.append(e.batch_id.in_(child_ids))  # a division includes its lab sub-groups
        return or_(*conds)

    def apply(self, q, f: Filters):
        for kind in ("course", "professor", "batch", "room"):
            cands = getattr(f, kind)
            if cands:
                q = q.where(or_(*[self._cand_cond(kind, c) for c in cands]))
        if f.self_only:
            q = self._self(q)
        return q

    def _self(self, q):
        """'my' in the institutional view: a professor's own classes; a student's batch (already the scope)."""
        p = self.ctx.principal
        if self.ctx.domain == Domain.PERSONAL or RoleCode.STUDENT in p.roles:
            return q
        if RoleCode.PROFESSOR in p.roles and p.staff_id:
            e = self.m.entry
            return q.where(e.staff_id == p.staff_id)
        return q

    def fetch(self, q) -> list:
        e = self.m.entry
        return list(self.db.scalars(q.order_by(e.day_of_week.nulls_last(), e.class_date.nulls_last(), e.start_time.nulls_last(),
                                               e.source_page)).unique())

    def excluded_count(self, q) -> int:
        e = self.m.entry
        sub = q.where(or_(e.time_uncertain.is_(True), e.start_time.is_(None), e.end_time.is_(None)))
        return self.db.scalar(select(func.count()).select_from(sub.subquery())) or 0

    # ---------------------------------------------------------------- serialisation helpers
    def items(self, rows, d: date | None = None) -> list[dict]:
        out = []
        now = self.ctx.now
        for e in rows:
            it = serialize_entry(e)
            if d is not None:
                it["date"] = d.isoformat()
                if d == now.date() and e.start_time and e.end_time:
                    t = now.time().replace(tzinfo=None)
                    it["status"] = "IN_PROGRESS" if e.start_time <= t < e.end_time else ("ENDED" if e.end_time <= t else "UPCOMING")
            out.append(it)
        return out


def uncertain_overlapping(q: "Q", d: date, t: time, f: Filters) -> int:
    """Entries that day whose time is missing, or whose *candidate* interval (uncertain) contains t."""
    e = q.m.entry
    base = q.apply(q.base().where(q.on_date(d)), f)
    rows = q.fetch(base.where(or_(e.start_time.is_(None), e.end_time.is_(None), e.time_uncertain.is_(True))))
    return sum(1 for x in rows if x.start_time is None or x.end_time is None or x.start_time <= t < x.end_time)


def _excluded_warning(n: int) -> list[dict]:
    if not n:
        return []
    return [{"code": "UNCERTAIN_TIME_EXCLUDED",
             "message": f"{n} entr{'y' if n == 1 else 'ies'} with missing or unverified times "
                        f"{'was' if n == 1 else 'were'} excluded from this time-based answer."}]


def _effective_warning(ctx: SearchContext, d: date) -> list[dict]:
    tt = ctx.timetable
    if tt.effective_from and d < tt.effective_from:
        return [{"code": "BEFORE_EFFECTIVE_DATE",
                 "message": f"This timetable takes effect from {tt.effective_from:%d %b %Y}; {d:%d %b %Y} is before that."}]
    if tt.effective_to and d > tt.effective_to:
        return [{"code": "AFTER_EFFECTIVE_END", "message": f"This timetable ended on {tt.effective_to:%d %b %Y}."}]
    return []


# ======================================================================== QT01–QT05


def qt01_entries_for_date(q: Q, d: date, f: Filters) -> Result:
    rows = q.fetch(q.apply(q.base().where(q.on_date(d)), f))
    return Result(q.items(rows, d), warnings=_effective_warning(q.ctx, d), meta={"date": d.isoformat(), "day_name": DOW[d.isoweekday()]})


def qt02_entries_for_range(q: Q, start: date, end: date, f: Filters) -> Result:
    dows = {(start + timedelta(days=i)).isoweekday() for i in range((end - start).days + 1)}
    e = q.m.entry
    base = q.apply(q.base().where(or_(e.class_date.between(start, end),
                                      and_(e.class_date.is_(None), e.day_of_week.in_(sorted(dows))))), f)
    rows = q.fetch(base)
    items: list[dict] = []
    d = start
    while d <= end:
        for e_ in rows:
            if e_.class_date == d or (e_.class_date is None and e_.day_of_week == d.isoweekday()):
                items += q.items([e_], d)
        d += timedelta(days=1)
    return Result(items, warnings=_effective_warning(q.ctx, start),
                  meta={"start_date": start.isoformat(), "end_date": end.isoformat()})


def qt03_entries_for_weekday(q: Q, dow: int, f: Filters) -> Result:
    rows = q.fetch(q.apply(q.base().where(q.on_dow(dow)), f))
    return Result(q.items(rows), meta={"day_of_week": dow, "day_name": DOW[dow], "recurring_view": True})


def qt04_filter_by_time(q: Q, d: date, start: time, end: time, f: Filters, *, starts_within: bool = False) -> Result:
    """Overlap (default): entry.start < window_end AND entry.end > window_start.
    starts_within=True: entries starting in [start, end) — used for 'after <time>'."""
    e = q.m.entry
    base = q.apply(q.base().where(q.on_date(d)), f)
    excluded = q.excluded_count(base)
    cond = and_(e.start_time >= start, e.start_time < end) if starts_within else and_(e.start_time < end, e.end_time > start)
    rows = q.fetch(base.where(q.time_ok(), cond))
    return Result(q.items(rows, d), warnings=_excluded_warning(excluded) + _effective_warning(q.ctx, d),
                  meta={"date": d.isoformat(), "start_time": start.strftime("%H:%M"), "end_time": end.strftime("%H:%M")})


def qt05_find_by_course(q: Q, f: Filters, d: date | None = None, dow: int | None = None) -> Result:
    base = q.apply(q.base(), f)
    if d:
        base = base.where(q.on_date(d))
    elif dow:
        base = base.where(q.on_dow(dow))
    rows = q.fetch(base)
    return Result(q.items(rows, d), meta={"date": d.isoformat() if d else None, "day_of_week": dow})


# ======================================================================== QT06–QT09


def qt06_entry_details(q: Q, entry_id) -> Result:
    e = q.m.entry
    rows = q.fetch(q.base(classes_only=False).where(e.entry_id == entry_id))
    items = [serialize_entry(x, include_review=False) | {"raw_text": x.raw_extracted_text,
                                                         "section": x.section.title if x.section else None}
             for x in rows]
    return Result(items, result_type="ENTRY_DETAILS")


def qt07_current(q: Q, f: Filters) -> Result:
    now = q.ctx.now
    d, t = now.date(), now.time().replace(tzinfo=None)
    e = q.m.entry
    base = q.apply(q.base().where(q.on_date(d)), f)
    excluded = q.excluded_count(base)
    rows = q.fetch(base.where(q.time_ok(), e.start_time <= t, e.end_time > t))
    return Result(q.items(rows, d), warnings=_excluded_warning(excluded), meta={"date": d.isoformat(), "time": t.strftime("%H:%M")})


def _lookahead(db: Session) -> int:
    cfg = db.get(InstitutionConfig, 1)
    return cfg.next_class_lookahead_days if cfg else 7


def qt08_next(q: Q, f: Filters) -> Result:
    """Earliest entry starting after now: today first, then following days up to the configured look-ahead (D-05)."""
    now = q.ctx.now
    t = now.time().replace(tzinfo=None)
    e = q.m.entry
    excluded_total = 0
    days = _lookahead(q.db)
    for offset in range(0, days + 1):
        d = now.date() + timedelta(days=offset)
        base = q.apply(q.base().where(q.on_date(d)), f)
        excluded_total += q.excluded_count(base) if offset == 0 else 0
        qq = base.where(q.time_ok())
        if offset == 0:
            qq = qq.where(e.start_time > t)
        rows = q.fetch(qq)
        if rows:
            first = rows[0].start_time
            same = [r for r in rows if r.start_time == first]  # parallel entries (e.g. lab groups)
            items = q.items(same, d)
            start_dt = datetime.combine(d, first, tzinfo=now.tzinfo)
            minutes = int((start_dt - now).total_seconds() // 60)
            for it in items:
                it["minutes_until"] = minutes
            return Result(items, warnings=_excluded_warning(excluded_total) + _effective_warning(q.ctx, d),
                          meta={"date": d.isoformat(), "minutes_until": minutes, "lookahead_days": days})
    return Result([], warnings=_excluded_warning(excluded_total), meta={"lookahead_days": days})


def qt09_remaining_today(q: Q, f: Filters) -> Result:
    """Classes today that have not yet ended (in-progress ones are marked IN_PROGRESS)."""
    now = q.ctx.now
    d, t = now.date(), now.time().replace(tzinfo=None)
    e = q.m.entry
    base = q.apply(q.base().where(q.on_date(d)), f)
    excluded = q.excluded_count(base)
    rows = q.fetch(base.where(q.time_ok(), e.end_time > t))
    return Result(q.items(rows, d), warnings=_excluded_warning(excluded), meta={"date": d.isoformat(), "time": t.strftime("%H:%M")})


# ======================================================================== QT10–QT14 (professors)


def qt10_professor_schedule(q: Q, f: Filters, d: date | None = None, dow: int | None = None,
                            rng: tuple[date, date] | None = None) -> Result:
    if rng:
        return qt02_entries_for_range(q, rng[0], rng[1], f)
    base = q.apply(q.base(), f)
    if d:
        base = base.where(q.on_date(d))
    elif dow:
        base = base.where(q.on_dow(dow))
    return Result(q.items(q.fetch(base), d), meta={"date": d.isoformat() if d else None, "day_of_week": dow})


def qt11_professor_location(q: Q, f: Filters, at: datetime) -> Result:
    d, t = at.date(), at.time().replace(tzinfo=None)
    e = q.m.entry
    base = q.apply(q.base().where(q.on_date(d)), f)
    excluded = q.excluded_count(base)
    rows = q.fetch(base.where(q.time_ok(), e.start_time <= t, e.end_time > t))
    return Result(q.items(rows, d), result_type="SCHEDULED_LOCATION", warnings=_excluded_warning(excluded),
                  meta={"date": d.isoformat(), "time": t.strftime("%H:%M"),
                        "disclaimer": "Scheduled location from the timetable — not real-time tracking."})


def qt12_professor_courses(q: Q, f: Filters) -> Result:
    rows = q.fetch(q.apply(q.base(), f))
    agg: dict[str, dict] = {}
    for x in rows:
        it = serialize_entry(x)
        key = it["course"] or "(unnamed)"
        a = agg.setdefault(key, {"course": it["course"], "course_code": it["course_code"], "evidence_count": 0,
                                 "batches": set(), "unverified": False})
        a["evidence_count"] += 1
        if it["batch"]:
            a["batches"].add(it["batch"])
        a["unverified"] |= it["verification_status"] != VerificationStatus.VERIFIED
    items = [{**a, "batches": sorted(a["batches"])} for a in agg.values()]
    items.sort(key=lambda a: -a["evidence_count"])
    return Result(items, result_type="COURSES")


def qt13_professor_free(q: Q, f: Filters, d: date) -> Result:
    cfg = q.db.get(InstitutionConfig, 1)
    ws, we = cfg.working_hours_start, cfg.working_hours_end
    e = q.m.entry
    base = q.apply(q.base().where(q.on_date(d)), f)
    rows = q.fetch(base.where(e.start_time.is_not(None), e.end_time.is_not(None)))
    busy = sorted((max(r.start_time, ws), min(r.end_time, we)) for r in rows if r.end_time > ws and r.start_time < we)
    uncertain = sum(1 for r in rows if r.time_uncertain)
    free: list[dict] = []
    cur = ws
    for s, en in busy:
        if s > cur:
            free.append((cur, s))
        cur = max(cur, en)
    if cur < we:
        free.append((cur, we))
    items = [{"start_time": a.strftime("%H:%M"), "end_time": b.strftime("%H:%M"),
              "duration_minutes": int((datetime.combine(d, b) - datetime.combine(d, a)).total_seconds() // 60)} for a, b in free]
    warnings = [{"code": "FREE_MEANS_UNSCHEDULED",
                 "message": "Free means no class in this timetable within configured working hours — not confirmed availability."}]
    if uncertain:
        warnings.append({"code": "UNCERTAIN_TIMES_TREATED_BUSY",
                         "message": f"{uncertain} class(es) with unverified times were treated as busy, so free time may be understated."})
    nulls = q.db.scalar(select(func.count()).select_from(base.where(or_(e.start_time.is_(None), e.end_time.is_(None))).subquery())) or 0
    if nulls:
        warnings.append({"code": "SCHEDULE_INCOMPLETE",
                         "message": f"{nulls} class(es) for this professor on that day have no usable time; free time may be wrong."})
    return Result(items, result_type="FREE_INTERVALS", warnings=warnings + _effective_warning(q.ctx, d),
                  meta={"date": d.isoformat(), "working_hours": f"{ws:%H:%M}–{we:%H:%M}", "busy_classes": len(rows)})


def qt14_professors_for_batch(q: Q, f: Filters) -> Result:
    rows = q.fetch(q.apply(q.base(), f))
    agg: dict[str, dict] = {}
    unknown = 0
    for x in rows:
        it = serialize_entry(x)
        if not it["professor"]:
            unknown += 1
            continue
        a = agg.setdefault(it["professor"], {"professor": it["professor"], "professor_code": it["professor_code"],
                                             "courses": set(), "evidence_count": 0, "unverified": False})
        a["evidence_count"] += 1
        if it["course"]:
            a["courses"].add(it["course"])
        a["unverified"] |= it["verification_status"] != VerificationStatus.VERIFIED
    items = sorted(({**a, "courses": sorted(a["courses"])} for a in agg.values()), key=lambda a: a["professor"])
    warnings = []
    if unknown:
        warnings.append({"code": "FACULTY_UNKNOWN_FOR_SOME", "message": f"{unknown} class(es) for this batch list no professor."})
    return Result(items, result_type="PROFESSORS", warnings=warnings)


# ======================================================================== QT15–QT19 (rooms)


def qt15_room_schedule(q: Q, f: Filters, d: date | None = None, dow: int | None = None) -> Result:
    base = q.apply(q.base(), f)
    if d:
        base = base.where(q.on_date(d))
    elif dow:
        base = base.where(q.on_dow(dow))
    return Result(q.items(q.fetch(base), d), meta={"date": d.isoformat() if d else None, "day_of_week": dow,
                                                    "disclaimer": "Scheduled use only — not verified physical occupancy."})


def qt16_room_free(q: Q, f: Filters, at: datetime) -> Result:
    d, t = at.date(), at.time().replace(tzinfo=None)
    e = q.m.entry
    base = q.apply(q.base().where(q.on_date(d)), f)
    uncertain_rows = q.fetch(base.where(or_(e.time_uncertain.is_(True), e.start_time.is_(None))))
    rows = q.fetch(base.where(q.time_ok(), e.start_time <= t, e.end_time > t))
    unverified_room = any(r.verification_status != VerificationStatus.VERIFIED for r in rows)
    status = "SCHEDULED" if rows else ("UNCERTAIN" if uncertain_rows else "NO_SCHEDULED_CLASS")
    warnings = []
    if uncertain_rows and not rows:
        warnings.append({"code": "ROOM_HAS_UNCERTAIN_ENTRIES",
                         "message": f"{len(uncertain_rows)} class(es) in this room that day have unverified times, so it cannot be "
                                    "confirmed free."})
    item = {"room": f.room[0].display if f.room else None, "date": d.isoformat(), "time": t.strftime("%H:%M"),
            "scheduled_status": status, "scheduled_free": status == "NO_SCHEDULED_CLASS", "entries": q.items(rows, d),
            "unverified": unverified_room}
    return Result([item], result_type="ROOM_STATUS", warnings=warnings,
                  meta={"disclaimer": "“Free” means no class scheduled in this timetable — not verified physical occupancy."})


def _floor_rooms(db: Session, floor: int | None):
    rooms = list(db.scalars(select(Room).where(Room.is_active.is_(True)).order_by(Room.room_code)))
    if floor is None:
        return rooms, []
    matched, unmapped = [], []
    for r in rooms:
        if r.floor_label is None:
            unmapped.append(r)
            continue
        lab = r.floor_label.strip().lower()
        num = 0 if lab in ("g", "ground", "gf", "0") else (int("".join(ch for ch in lab if ch.isdigit())) if any(ch.isdigit() for ch in lab) else None)
        if num == floor:
            matched.append(r)
    return matched, unmapped


def qt17_free_rooms(q: Q, at: datetime, floor: int | None) -> Result:
    d, t = at.date(), at.time().replace(tzinfo=None)
    e = q.m.entry
    rooms, unmapped_floor = _floor_rooms(q.db, floor)
    base = q.base().where(q.on_date(d))
    occupied = {r.room_id for r in q.fetch(base.where(q.time_ok(), e.start_time <= t, e.end_time > t, e.room_id.is_not(None)))}
    uncertain = {r.room_id for r in q.fetch(base.where(e.room_id.is_not(None), or_(e.time_uncertain.is_(True), e.start_time.is_(None))))}
    unmapped_now = [r for r in q.fetch(base.where(q.time_ok(), e.start_time <= t, e.end_time > t, e.room_id.is_(None),
                                                  q.m.room_label.is_not(None)))]
    items, not_confirmed = [], []
    for r in rooms:
        if r.room_id in occupied:
            continue
        if r.room_id in uncertain:
            not_confirmed.append(r.room_code)
            continue
        items.append({"room": r.room_code, "room_id": r.room_id, "floor": r.floor_label, "building": r.building,
                      "capacity": r.capacity, "room_type": r.room_type})
    warnings = [{"code": "FREE_MEANS_UNSCHEDULED",
                 "message": "Rooms listed have no class scheduled in this timetable at that time — not verified physical availability."}]
    if not rooms:
        warnings.append({"code": "ROOM_INVENTORY_MISSING", "message": "No rooms are in the inventory" + (f" for floor {floor}" if floor is not None else "") + "."})
    if not_confirmed:
        warnings.append({"code": "ROOMS_NOT_CONFIRMED",
                         "message": f"Not listed because their schedule that day has unverified times: {', '.join(sorted(not_confirmed))}."})
    if unmapped_now:
        labels = sorted({x.room_label_raw for x in unmapped_now if x.room_label_raw})
        warnings.append({"code": "UNMAPPED_ROOMS_IN_USE",
                         "message": f"Classes at that time use rooms not in the inventory ({', '.join(labels)}); the list may be incomplete."})
    if floor is not None and unmapped_floor:
        warnings.append({"code": "FLOOR_MAPPING_INCOMPLETE",
                         "message": f"{len(unmapped_floor)} room(s) have no floor recorded and were not considered."})
    return Result(items, result_type="ROOMS", warnings=warnings,
                  meta={"date": d.isoformat(), "time": t.strftime("%H:%M"), "floor": floor, "rooms_checked": len(rooms)})


def qt18_floor_entries(q: Q, floor: int, at: datetime | None, d: date | None) -> Result:
    e = q.m.entry
    rooms, unmapped = _floor_rooms(q.db, floor)
    ids = [r.room_id for r in rooms]
    when_d = (at.date() if at else d) or q.ctx.now.date()
    base = q.base().where(q.on_date(when_d), e.room_id.in_(ids) if ids else false())
    warnings = []
    if at:
        t = at.time().replace(tzinfo=None)
        excluded = q.excluded_count(base)
        base = base.where(q.time_ok(), e.start_time <= t, e.end_time > t)
        warnings += _excluded_warning(excluded)
    rows = q.fetch(base)
    if not rooms:
        warnings.append({"code": "FLOOR_MAPPING_MISSING", "message": f"No rooms are mapped to floor {floor}."})
    if unmapped:
        warnings.append({"code": "FLOOR_MAPPING_INCOMPLETE", "message": f"{len(unmapped)} room(s) have no floor recorded."})
    unmapped_entries = q.db.scalar(select(func.count()).select_from(
        q.base().where(q.on_date(when_d), e.room_id.is_(None), q.m.room_label.is_not(None)).subquery())) or 0
    if unmapped_entries:
        warnings.append({"code": "UNMAPPED_ROOM_LABELS",
                         "message": f"{unmapped_entries} class(es) that day use room labels not in the inventory and cannot be placed on a floor."})
    return Result(q.items(rows, when_d), warnings=warnings,
                  meta={"floor": floor, "date": when_d.isoformat(), "time": at.strftime("%H:%M") if at else None,
                        "rooms_on_floor": [r.room_code for r in rooms]})


def qt19_rooms_after(q: Q, d: date, t: time, floor: int | None) -> Result:
    e = q.m.entry
    base = q.base().where(q.on_date(d))
    excluded = q.excluded_count(base)
    base = base.where(q.time_ok(), e.start_time >= t)
    if floor is not None:
        rooms, _ = _floor_rooms(q.db, floor)
        base = base.where(e.room_id.in_([r.room_id for r in rooms]))
    rows = q.fetch(base)
    agg: dict[str, dict] = {}
    for x in rows:
        it = serialize_entry(x)
        if not it["room"]:
            continue
        a = agg.setdefault(it["room"], {"room": it["room"], "floor": it["floor"], "first_start": it["start_time"], "classes": 0,
                                        "mapped": x.room_id is not None if hasattr(x, "room_id") else False})
        a["classes"] += 1
        a["first_start"] = min(a["first_start"], it["start_time"])
    return Result(sorted(agg.values(), key=lambda a: (a["first_start"], a["room"])), result_type="ROOMS",
                  warnings=_excluded_warning(excluded), meta={"date": d.isoformat(), "after": t.strftime("%H:%M"), "floor": floor})
