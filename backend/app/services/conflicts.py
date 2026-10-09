"""Conflict detection on structured entries (prompt §9).

Two entries conflict only when they share a *resource identity* (professor / room / batch), the
same day (or date), and their intervals truly overlap: a.start < b.end AND b.start < a.end
(end-exclusive, so back-to-back classes do not conflict).

Confidence of a conflict:
* CONFIRMED — both entries are VERIFIED, times confirmed, and the resource is a mapped master id.
* POSSIBLE  — anything weaker (label-only resource, unverified entry or uncertain time).
Entries with missing times/days are never used.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import EntryKind, VerificationStatus
from app.models import InstitutionalTimetableEntry as E
from app.services.domains import entry_labels
from app.services.matching import normalize_label


def _resource_keys(e: E) -> dict[str, tuple[str, bool]]:
    keys: dict[str, tuple[str, bool]] = {}
    if e.staff_id:
        keys["PROFESSOR"] = (f"id:{e.staff_id}", True)
    elif e.staff_label_raw and "+" not in e.staff_label_raw:
        keys["PROFESSOR"] = (f"label:{normalize_label(e.staff_label_raw)}", False)
    if e.room_id:
        keys["ROOM"] = (f"id:{e.room_id}", True)
    elif e.room_label_raw:
        keys["ROOM"] = (f"label:{normalize_label(e.room_label_raw)}", False)
    if e.batch_id:
        keys["BATCH"] = (f"id:{e.batch_id}", True)
    elif e.batch_label_raw:
        keys["BATCH"] = (f"label:{normalize_label(e.batch_label_raw)}", False)
    return keys


def _is_division_pair(a: E, b: E) -> bool:
    """Same division theory class vs. one of its lab sub-groups counts as a batch clash;
    two different sub-groups (A1 vs A2) do not."""
    la, lb = normalize_label(a.batch_label_raw), normalize_label(b.batch_label_raw)
    return la != lb and (lb.startswith(la) or la.startswith(lb))


def _short(e: E) -> dict[str, Any]:
    lab = entry_labels(e)
    return {"entry_id": str(e.entry_id), "day_of_week": e.day_of_week, "start_time": e.start_time.strftime("%H:%M"),
            "end_time": e.end_time.strftime("%H:%M"), "course": lab["course"], "professor": lab["professor"],
            "batch": lab["batch"], "room": lab["room"], "verification_status": e.verification_status,
            "source_page": e.source_page}


def detect(db: Session, timetable_id, department_ids: set[int] | None = None) -> dict:
    rows = db.scalars(select(E).where(
        E.timetable_id == timetable_id, E.entry_kind == EntryKind.CLASS,
        E.verification_status != VerificationStatus.REJECTED,
        E.day_of_week.is_not(None), E.start_time.is_not(None), E.end_time.is_not(None),
    )).unique().all()
    if department_ids is not None:
        rows = [e for e in rows if (e.batch and e.batch.department_id in department_ids)
                or (e.staff and e.staff.department_id in department_ids)]
    groups: dict[tuple, list[E]] = defaultdict(list)
    for e in rows:
        for kind, (key, _) in _resource_keys(e).items():
            groups[(kind, key, e.day_of_week, e.class_date)].append(e)
    # batch hierarchy: compare division-level classes with their sub-groups too
    by_day: dict[tuple, list[E]] = defaultdict(list)
    for e in rows:
        if e.batch_label_raw:
            by_day[(e.day_of_week, e.class_date)].append(e)

    conflicts: list[dict] = []
    seen: set[tuple] = set()

    def add(kind: str, a: E, b: E, mapped: bool) -> None:
        pair = tuple(sorted((str(a.entry_id), str(b.entry_id)))) + (kind,)
        if pair in seen:
            return
        seen.add(pair)
        certain = (mapped and a.verification_status == VerificationStatus.VERIFIED and b.verification_status == VerificationStatus.VERIFIED
                   and not a.time_uncertain and not b.time_uncertain)
        resource = entry_labels(a)[{"PROFESSOR": "professor", "ROOM": "room", "BATCH": "batch"}[kind]]
        conflicts.append({
            "type": f"{kind}_OVERLAP", "resource": resource, "confidence": "CONFIRMED" if certain else "POSSIBLE",
            "reason": None if certain else "Based on unverified/unmapped data or uncertain times — confirm before acting.",
            "entries": [_short(a), _short(b)],
        })

    def overlaps(a: E, b: E) -> bool:
        return a.start_time < b.end_time and b.start_time < a.end_time

    for (kind, key, _, _), es in groups.items():
        es.sort(key=lambda e: e.start_time)
        for i, a in enumerate(es):
            for b in es[i + 1:]:
                if b.start_time >= a.end_time:
                    break
                if overlaps(a, b) and a.entry_id != b.entry_id:
                    if kind == "BATCH" and "batch" in (a.course_label_raw or "").lower() and "batch" in (b.course_label_raw or "").lower():
                        continue  # parallel elective groups
                    add(kind, a, b, key.startswith("id:"))
    for es in by_day.values():
        for i, a in enumerate(es):
            for b in es[i + 1:]:
                if overlaps(a, b) and _is_division_pair(a, b):
                    add("BATCH", a, b, False)

    conflicts.sort(key=lambda c: (c["confidence"] != "CONFIRMED", c["type"], c["entries"][0]["day_of_week"], c["entries"][0]["start_time"]))
    counts: dict[str, int] = defaultdict(int)
    for c in conflicts:
        counts[f"{c['type']}:{c['confidence']}"] += 1
    return {"timetable_id": str(timetable_id), "total": len(conflicts), "counts": dict(counts), "conflicts": conflicts,
            "entries_considered": len(rows),
            "note": "Only entries with a day and confirmed-or-candidate times are compared; intervals are end-exclusive."}
