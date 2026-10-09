"""Map institutional extracted labels to master records — only when the match is unique and exact
(normalised code/name or an approved alias). Personal entries are never mapped (SRS §3.4)."""
from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Batch, Course, EntityAlias, Room, Staff, UserAccount
from app.services.matching import normalize_label, normalize_person


@dataclass
class MasterIndex:
    course: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    staff: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    staff_names: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    room: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    batch: dict[str, set] = field(default_factory=lambda: defaultdict(set))
    batch_parent: dict[int, int | None] = field(default_factory=dict)

    @property
    def room_keys(self) -> set[str]:
        return set(self.room)


def load_index(db: Session, department_id: int | None = None) -> MasterIndex:
    """When the timetable belongs to a department, batches/courses of *other* departments are not
    candidates (a CE timetable's "SE-A" is CE's SE-A). Department-less courses stay eligible."""
    ix = MasterIndex()
    cq = select(Course).where(Course.is_active.is_(True))
    bq = select(Batch).where(Batch.is_active.is_(True))
    if department_id is not None:
        cq = cq.where((Course.department_id == department_id) | Course.department_id.is_(None))
        bq = bq.where(Batch.department_id == department_id)
    for c in db.scalars(cq):
        if c.course_code:
            ix.course[normalize_label(c.course_code)].add(c.course_id)
        ix.course[normalize_label(c.name)].add(c.course_id)
    for s, u in db.execute(select(Staff, UserAccount).join(UserAccount, UserAccount.user_id == Staff.user_id)):
        if s.short_code:
            ix.staff[normalize_label(s.short_code)].add(s.staff_id)
        ix.staff_names[normalize_person(u.display_name)].add(s.staff_id)
    for r in db.scalars(select(Room).where(Room.is_active.is_(True))):
        ix.room[normalize_label(r.room_code)].add(r.room_id)
    allowed_batches = set(db.scalars(select(Batch.batch_id).where(bq.whereclause))) if department_id is not None else None
    allowed_courses = set(db.scalars(select(Course.course_id).where(cq.whereclause))) if department_id is not None else None
    for b in db.scalars(bq):
        ix.batch[normalize_label(b.code)].add(b.batch_id)
        ix.batch_parent[b.batch_id] = b.parent_batch_id
    for a in db.scalars(select(EntityAlias)):
        target = {"COURSE": ix.course, "STAFF": ix.staff, "ROOM": ix.room, "BATCH": ix.batch}[a.entity_type]
        try:
            ent = int(a.entity_id) if a.entity_type != "STAFF" else uuid.UUID(a.entity_id)
        except ValueError:
            continue
        if a.entity_type == "BATCH" and allowed_batches is not None and ent not in allowed_batches:
            continue
        if a.entity_type == "COURSE" and allowed_courses is not None and ent not in allowed_courses:
            continue
        target[a.alias_normalized].add(ent)
    return ix


def _one(index: dict[str, set], *keys: str):
    """Unique id across the given keys, or (None, ambiguous?)."""
    found: set = set()
    for k in keys:
        if k:
            found |= index.get(k, set())
    if len(found) == 1:
        return next(iter(found)), False
    return None, len(found) > 1


GROUP_SUFFIX = re.compile(r"\s*\((?:batch|s\.?\s*n)[^)]*\)\s*$", re.I)   # "(Batch1)", "(S.N. 1 to 60)"
LAB_SUFFIX = re.compile(r"\b(lab|laboratory|practical|tut|tutorial)\b", re.I)


def course_keys(e) -> list[str]:
    """Lookup keys for an entry's course, most specific first: the label as printed, the subject
    code the extractor recognised inside it ("DS Lab" → DS, "PE III-TSDA -A" → TSDA), the label
    without lab/tutorial words, then the expanded name (with "(Lab)"/"(Open Elective)" removed)."""
    keys = [normalize_label(e.course_label), normalize_label(GROUP_SUFFIX.sub("", e.course_label or ""))]
    for m in e.messages:
        if m.get("code") in ("COURSE_CODE_BASE", "COURSE_CODE_WITHIN_LABEL") and (m.get("details") or {}).get("code"):
            keys.append(normalize_label(m["details"]["code"]))
    keys.append(normalize_label(LAB_SUFFIX.sub(" ", re.sub(r"\(.*?\)", " ", e.course_label or ""))))
    if e.course_name:
        keys.append(normalize_label(e.course_name))
        keys.append(normalize_label(re.sub(r"\s*\([^)]*\)", "", e.course_name)))
    out: list[str] = []
    for k in keys:
        if k and k not in out:
            out.append(k)
    return out


def map_entry(ix: MasterIndex, e) -> dict:
    """Returns {course_id, staff_id, room_id, batch_id} and appends warnings to e.messages."""
    out = {"course_id": None, "staff_id": None, "room_id": None, "batch_id": None}
    if e.entry_kind != "CLASS":
        return out

    def warn(code, msg):
        e.messages.append({"severity": "WARNING", "code": code, "message": msg})

    if e.course_label:
        cid, amb = None, False
        for key in course_keys(e):
            cid, a = _one(ix.course, key)
            amb = amb or a
            if cid is not None or a:
                break
        out["course_id"] = cid
        if cid is None:
            warn("COURSE_NOT_MAPPED", f"Course '{e.course_label}' is not linked to a course record"
                 + (" (several records match)." if amb else "."))
    if e.staff_label:
        if "+" in e.staff_label:
            e.messages.append({"severity": "INFO", "code": "MULTIPLE_FACULTY",
                               "message": f"Several faculty listed ({e.staff_label}); none linked individually."})
        else:
            sid, amb = _one(ix.staff, normalize_label(e.staff_label))
            if sid is None and e.staff_name:
                sid, amb2 = _one(ix.staff_names, normalize_person(e.staff_name))
                amb = amb or amb2
            out["staff_id"] = sid
            if sid is None:
                warn("FACULTY_NOT_MAPPED", f"Faculty '{e.staff_label}' is not linked to a staff record"
                     + (" (several staff match)." if amb else "."))
    if e.room_label:
        rid, amb = _one(ix.room, normalize_label(e.room_label))
        out["room_id"] = rid
        if rid is None:
            warn("ROOM_NOT_MAPPED", f"Room '{e.room_label}' is not in the room inventory"
                 + (" (several rooms match)." if amb else "."))
    combined = re.fullmatch(r"(.+?)-([A-Z](?:/[A-Z])+)", e.batch_label or "")
    if combined:
        # "BE-A/B/C/D": a class shared by several divisions maps to the batch that is the common
        # parent of exactly those divisions (students of each division inherit it). Never guessed.
        prefix, divs = combined.group(1), combined.group(2).split("/")
        ids = [_one(ix.batch, normalize_label(f"{prefix}-{d}"))[0] for d in divs]
        parents = {ix.batch_parent.get(i) for i in ids}
        if None not in ids and len(parents) == 1 and None not in parents:
            out["batch_id"] = next(iter(parents))
        else:
            warn("COMBINED_SCOPE_NOT_MAPPED",
                 f"'{e.batch_label}' is shared by several divisions. Create a batch that is the parent of "
                 f"{', '.join(f'{prefix}-{d}' for d in divs)} so all their students see these classes.")
    elif e.batch_label:
        bid, amb = _one(ix.batch, normalize_label(e.batch_label))
        out["batch_id"] = bid
        if bid is None:
            warn("BATCH_NOT_MAPPED", f"Batch '{e.batch_label}' is not linked to a batch record"
                 + (" (several batches match)." if amb else "."))
    return out
