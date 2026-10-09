"""Map institutional extracted labels to master records — only when the match is unique and exact
(normalised code/name or an approved alias). Personal entries are never mapped (SRS §3.4)."""
from __future__ import annotations

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

    @property
    def room_keys(self) -> set[str]:
        return set(self.room)


def load_index(db: Session) -> MasterIndex:
    ix = MasterIndex()
    for c in db.scalars(select(Course).where(Course.is_active.is_(True))):
        if c.course_code:
            ix.course[normalize_label(c.course_code)].add(c.course_id)
        ix.course[normalize_label(c.name)].add(c.course_id)
    for s, u in db.execute(select(Staff, UserAccount).join(UserAccount, UserAccount.user_id == Staff.user_id)):
        if s.short_code:
            ix.staff[normalize_label(s.short_code)].add(s.staff_id)
        ix.staff_names[normalize_person(u.display_name)].add(s.staff_id)
    for r in db.scalars(select(Room).where(Room.is_active.is_(True))):
        ix.room[normalize_label(r.room_code)].add(r.room_id)
    for b in db.scalars(select(Batch).where(Batch.is_active.is_(True))):
        ix.batch[normalize_label(b.code)].add(b.batch_id)
    for a in db.scalars(select(EntityAlias)):
        target = {"COURSE": ix.course, "STAFF": ix.staff, "ROOM": ix.room, "BATCH": ix.batch}[a.entity_type]
        try:
            ent = int(a.entity_id) if a.entity_type != "STAFF" else uuid.UUID(a.entity_id)
        except ValueError:
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


def map_entry(ix: MasterIndex, e) -> dict:
    """Returns {course_id, staff_id, room_id, batch_id} and appends warnings to e.messages."""
    out = {"course_id": None, "staff_id": None, "room_id": None, "batch_id": None}
    if e.entry_kind != "CLASS":
        return out

    def warn(code, msg):
        e.messages.append({"severity": "WARNING", "code": code, "message": msg})

    if e.course_label:
        cid, amb = _one(ix.course, normalize_label(e.course_label))
        if cid is None and e.course_name:
            cid, amb2 = _one(ix.course, normalize_label(e.course_name))
            amb = amb or amb2
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
    if e.batch_label:
        bid, amb = _one(ix.batch, normalize_label(e.batch_label))
        out["batch_id"] = bid
        if bid is None and not any(m["code"] == "DIVISION_SCOPE_COMBINED" for m in e.messages):
            warn("BATCH_NOT_MAPPED", f"Batch '{e.batch_label}' is not linked to a batch record"
                 + (" (several batches match)." if amb else "."))
    return out
