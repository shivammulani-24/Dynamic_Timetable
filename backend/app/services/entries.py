"""Entry serialisation, role-scope SQL filters and the auditable review/correction workflow."""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, time
from typing import Any

from sqlalchemy import false, func, or_, select
from sqlalchemy.orm import Session

from app.enums import Domain, EntryKind, ProcessingStatus, VerificationStatus
from app.errors import AppError, Code
from app.extraction.timeparse import DAY_NAMES
from app.extraction.validate import USABLE_MIN_RATIO
from app.models import Batch, Course, EntryCorrection, Room, Staff
from app.security.policy import EntryScope
from app.security.principal import Principal
from app.services.audit import audit
from app.services.domains import models_for, entry_labels

_SHOWN_SEVERITIES = {"CRITICAL", "WARNING"}


def scope_condition(scope: EntryScope, tt, entry_model):
    """SQL condition restricting institutional entries to the principal's scope (None = unrestricted)."""
    if scope.college:
        return None
    if getattr(tt, "department_id", None) is not None and tt.department_id in scope.department_ids:
        return None  # a department timetable of the HOD's/professor's own department
    conds = []
    if scope.batch_ids:
        conds.append(entry_model.batch_id.in_(list(scope.batch_ids)))
    if scope.staff_ids:
        conds.append(entry_model.staff_id.in_(list(scope.staff_ids)))
    if scope.department_ids:
        depts = list(scope.department_ids)
        conds.append(entry_model.batch_id.in_(select(Batch.batch_id).where(Batch.department_id.in_(depts))))
        conds.append(entry_model.staff_id.in_(select(Staff.staff_id).where(Staff.department_id.in_(depts))))
    return or_(*conds) if conds else false()


def serialize_entry(e: Any, *, include_review: bool = False) -> dict:
    lab = entry_labels(e)
    duration = None
    if e.start_time and e.end_time:
        duration = int((datetime.combine(datetime.min, e.end_time) - datetime.combine(datetime.min, e.start_time)).total_seconds() // 60)
    out = {
        "entry_id": str(e.entry_id),
        "kind": e.entry_kind,
        "day_of_week": e.day_of_week,
        "day_name": DAY_NAMES.get(e.day_of_week) if e.day_of_week else None,
        "date": e.class_date.isoformat() if e.class_date else None,
        "start_time": e.start_time.strftime("%H:%M") if e.start_time else None,
        "end_time": e.end_time.strftime("%H:%M") if e.end_time else None,
        "duration_minutes": duration,
        **lab,
        "verification_status": e.verification_status,
        "time_uncertain": e.time_uncertain,
        "is_tentative": e.is_tentative,
        "confidence": float(e.confidence_score) if e.confidence_score is not None else None,
        "is_corrected": e.is_corrected,
        "warnings": [{"code": m["code"], "message": m["message"]} for m in (e.validation_messages or [])
                     if m.get("severity") in _SHOWN_SEVERITIES],
        "source_page": e.source_page,
    }
    if include_review:
        out.update({
            "raw_text": e.raw_extracted_text,
            "time_label_raw": e.time_label_raw,
            "source_region": e.source_region,
            "extraction_method": e.extraction_method,
            "all_messages": e.validation_messages,
            "section": ({"title": e.section.title, "program_level": e.section.program_level,
                         "divisions": e.section.divisions, "is_tentative": e.section.is_tentative} if e.section else None),
            "raw_labels": _raw_labels(e),
        })
        if hasattr(e, "course_id"):
            out["mapped"] = {"course_id": e.course_id, "staff_id": str(e.staff_id) if e.staff_id else None,
                             "room_id": e.room_id, "batch_id": e.batch_id}
    return out


def _raw_labels(e: Any) -> dict:
    if hasattr(e, "course_label_raw"):
        return {"course": e.course_label_raw, "professor": e.staff_label_raw, "batch": e.batch_label_raw, "room": e.room_label_raw}
    return {"course": e.course_label, "professor": e.professor_label, "batch": e.batch_label, "room": e.room_label}


def _snapshot(e: Any) -> dict:
    d = {"day_of_week": e.day_of_week, "start_time": e.start_time.strftime("%H:%M") if e.start_time else None,
         "end_time": e.end_time.strftime("%H:%M") if e.end_time else None, "entry_kind": e.entry_kind,
         "verification_status": e.verification_status, "time_uncertain": e.time_uncertain, **_raw_labels(e)}
    if hasattr(e, "course_id"):
        d.update(course_id=e.course_id, staff_id=str(e.staff_id) if e.staff_id else None, room_id=e.room_id, batch_id=e.batch_id)
    return d


_LABEL_FIELDS = {
    Domain.INSTITUTIONAL: {"course": "course_label_raw", "professor": "staff_label_raw", "batch": "batch_label_raw", "room": "room_label_raw"},
    Domain.PERSONAL: {"course": "course_label", "professor": "professor_label", "batch": "batch_label", "room": "room_label"},
}


def _parse_hhmm(v: str | None, field: str) -> time | None:
    if v is None:
        return None
    try:
        return datetime.strptime(v, "%H:%M").time()
    except ValueError:
        raise AppError(Code.INVALID_REQUEST, f"{field} must be HH:MM (24-hour).", {"field": field})


def correct_entry(db: Session, p: Principal, domain: Domain, tt, entry_id: Any, changes: dict, reason: str | None) -> dict:
    """Apply a reviewer correction. Originals are kept in ENTRY_CORRECTION; the entry is marked corrected."""
    if domain == Domain.INSTITUTIONAL and not p.is_admin:
        raise AppError(Code.ACCESS_DENIED, "Only an Admin can correct institutional entries.")
    m = models_for(domain)
    try:
        eid = uuid.UUID(str(entry_id))
    except ValueError:
        raise AppError(Code.NOT_FOUND, "Entry not found.")
    e = db.scalar(select(m.entry).where(m.entry.entry_id == eid, m.entry.timetable_id == tt.timetable_id).with_for_update(of=m.entry))
    if e is None:
        raise AppError(Code.NOT_FOUND, "Entry not found in this timetable.")
    before = _snapshot(e)

    if "day_of_week" in changes:
        d = changes["day_of_week"]
        if d is not None and not (1 <= int(d) <= 7):
            raise AppError(Code.INVALID_REQUEST, "day_of_week must be 1 (Monday) to 7 (Sunday).")
        e.day_of_week = d
    if "start_time" in changes:
        e.start_time = _parse_hhmm(changes["start_time"], "start_time")
    if "end_time" in changes:
        e.end_time = _parse_hhmm(changes["end_time"], "end_time")
    if e.start_time and e.end_time and e.end_time <= e.start_time:
        raise AppError(Code.INVALID_REQUEST, "End time must be after start time (overnight classes are not supported).")
    if "entry_kind" in changes:
        e.entry_kind = EntryKind(changes["entry_kind"]).value
    for key, col in _LABEL_FIELDS[domain].items():
        if key in changes:
            v = (changes[key] or "").strip() or None
            setattr(e, col, v[:200] if v else None)
            if key == "course":
                e.course_name_resolved = None
            if key == "professor":
                e.staff_name_resolved = None
    if domain == Domain.INSTITUTIONAL:
        for fld, model, conv in (("course_id", Course, int), ("room_id", Room, int), ("batch_id", Batch, int), ("staff_id", Staff, uuid.UUID)):
            if fld in changes:
                v = changes[fld]
                if v is None:
                    setattr(e, fld, None)
                    continue
                try:
                    target = db.get(model, conv(v))
                except (ValueError, TypeError):
                    target = None
                if target is None:
                    raise AppError(Code.INVALID_REQUEST, f"Unknown {fld.replace('_id', '')}.", {"field": fld})
                setattr(e, fld, target.__getattribute__(fld))

    new_status = changes.get("verification_status")
    if new_status:
        vs = VerificationStatus(new_status)
        if vs == VerificationStatus.VERIFIED and (e.day_of_week is None or e.start_time is None or e.end_time is None):
            raise AppError(Code.INVALID_REQUEST, "An entry needs a day, start and end time before it can be verified.")
        if vs == VerificationStatus.INCOMPLETE:
            raise AppError(Code.INVALID_REQUEST, "INCOMPLETE is set by validation, not by reviewers.")
        e.verification_status = vs.value
        if vs == VerificationStatus.VERIFIED:
            e.time_uncertain = False  # the reviewer confirmed the interval
    elif e.day_of_week is None or e.start_time is None or e.end_time is None:
        e.verification_status = VerificationStatus.INCOMPLETE
    elif e.verification_status == VerificationStatus.INCOMPLETE:
        e.verification_status = VerificationStatus.UNVERIFIED
    if ("start_time" in changes or "end_time" in changes) and not new_status:
        e.time_uncertain = False if e.verification_status == VerificationStatus.VERIFIED else e.time_uncertain

    e.is_corrected = True
    e.validation_messages = list(e.validation_messages or []) + [{
        "severity": "INFO", "code": "REVIEWER_CORRECTION", "message": f"Corrected by reviewer{': ' + reason if reason else ''}."}]
    after = _snapshot(e)
    db.add(EntryCorrection(
        domain=domain.value, corrected_by_user_id=p.user_id, before=before, after=after, reason=(reason or None),
        **({"institutional_entry_id": e.entry_id} if domain == Domain.INSTITUTIONAL else {"personal_entry_id": e.entry_id}),
    ))
    tt.data_version += 1
    recompute_summary(db, domain, tt)
    if domain == Domain.INSTITUTIONAL:
        audit(db, "INSTITUTIONAL_ENTRY_CORRECTED", p.user_id, "INSTITUTIONAL_ENTRY", e.entry_id,
              timetable_id=str(tt.timetable_id), changed=sorted(k for k in after if after[k] != before.get(k)))
    db.commit()
    return serialize_entry(e, include_review=True)


def recompute_summary(db: Session, domain: Domain, tt) -> None:
    m = models_for(domain)
    rows = db.execute(
        select(m.entry.verification_status, func.count())
        .where(m.entry.timetable_id == tt.timetable_id, m.entry.entry_kind == EntryKind.CLASS)
        .group_by(m.entry.verification_status)
    ).all()
    counts = defaultdict(int, {s: n for s, n in rows})
    total = sum(counts.values())
    usable = counts[VerificationStatus.VERIFIED] + counts[VerificationStatus.UNVERIFIED]
    summary = dict(tt.validation_summary or {})
    summary["by_status"] = dict(counts)
    summary["usable_class_entries"] = usable
    summary["class_entries"] = total
    if tt.processing_status in (ProcessingStatus.READY, ProcessingStatus.NEEDS_REVIEW, ProcessingStatus.UNUSABLE):
        if usable == 0 or (total and usable / total < USABLE_MIN_RATIO):
            tt.processing_status = ProcessingStatus.UNUSABLE
        elif counts[VerificationStatus.UNVERIFIED] or counts[VerificationStatus.INCOMPLETE]:
            tt.processing_status = ProcessingStatus.NEEDS_REVIEW
        else:
            tt.processing_status = ProcessingStatus.READY
        summary["status_reason"] = {
            ProcessingStatus.UNUSABLE: "Too few usable class entries.",
            ProcessingStatus.NEEDS_REVIEW: "Some entries are still unverified or incomplete.",
            ProcessingStatus.READY: "All class entries are verified or rejected after review.",
        }[ProcessingStatus(tt.processing_status)]
    tt.validation_summary = summary


def corrections_for(db: Session, domain: Domain, entry_id: uuid.UUID) -> list[dict]:
    col = EntryCorrection.institutional_entry_id if domain == Domain.INSTITUTIONAL else EntryCorrection.personal_entry_id
    rows = db.scalars(select(EntryCorrection).where(col == entry_id).order_by(EntryCorrection.corrected_at)).all()
    return [{"corrected_at": r.corrected_at.isoformat(), "before": r.before, "after": r.after, "reason": r.reason} for r in rows]
