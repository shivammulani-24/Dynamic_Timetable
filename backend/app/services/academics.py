"""Admin-confirmed academic transitions (promotion, repeat, pause, resume, withdraw, graduate, re-entry).

History intervals are half-open: a closed record has effective_to = the next record's effective_from.
Every transition closes the open record (if any) and optionally opens a new one *in one transaction*,
with the student row locked (SELECT … FOR UPDATE) to serialise concurrent confirmations.
A partial unique index (uq_sah_one_open) guarantees at most one open placement per student.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import HistoryStatus, StudentStatus
from app.errors import AppError, Code
from app.models import Student, StudentAcademicHistory
from app.security.principal import Principal
from app.security.tokens import utcnow
from app.services.audit import audit
from app.services.users import _admin_staff_id, _validate_placement


class Outcome(StrEnum):
    PROMOTE = "PROMOTE"
    REPEAT = "REPEAT"
    PAUSE = "PAUSE"
    RESUME = "RESUME"
    WITHDRAW = "WITHDRAW"
    GRADUATE = "GRADUATE"
    RE_ENTER = "RE_ENTER"


# outcome -> (allowed current open statuses (None = no open record), closing status, new status or None, student status)
_RULES: dict[Outcome, tuple[set, str | None, str | None, StudentStatus]] = {
    Outcome.PROMOTE: ({HistoryStatus.ACTIVE, HistoryStatus.REPEATING}, HistoryStatus.PROMOTED, HistoryStatus.ACTIVE, StudentStatus.ACTIVE),
    Outcome.REPEAT: ({HistoryStatus.ACTIVE, HistoryStatus.REPEATING}, HistoryStatus.CLOSED, HistoryStatus.REPEATING, StudentStatus.ACTIVE),
    Outcome.PAUSE: ({HistoryStatus.ACTIVE, HistoryStatus.REPEATING}, HistoryStatus.CLOSED, HistoryStatus.PAUSED, StudentStatus.PAUSED),
    Outcome.RESUME: ({HistoryStatus.PAUSED}, HistoryStatus.CLOSED, HistoryStatus.ACTIVE, StudentStatus.ACTIVE),
    Outcome.WITHDRAW: ({HistoryStatus.ACTIVE, HistoryStatus.REPEATING, HistoryStatus.PAUSED}, HistoryStatus.WITHDRAWN, None, StudentStatus.WITHDRAWN),
    Outcome.GRADUATE: ({HistoryStatus.ACTIVE, HistoryStatus.REPEATING}, HistoryStatus.GRADUATED, None, StudentStatus.GRADUATED),
    Outcome.RE_ENTER: ({None}, None, HistoryStatus.ACTIVE, StudentStatus.ACTIVE),
}


@dataclass
class TransitionRequest:
    student_id: uuid.UUID
    outcome: Outcome
    effective_date: date
    academic_year_id: int | None = None
    year_of_study: int | None = None
    semester: int | None = None
    department_id: int | None = None
    batch_id: int | None = None
    note: str | None = None


def current_placement(db: Session, student_id: uuid.UUID) -> StudentAcademicHistory | None:
    return db.scalar(
        select(StudentAcademicHistory).where(
            StudentAcademicHistory.student_id == student_id, StudentAcademicHistory.effective_to.is_(None)
        )
    )


def _plan(db: Session, req: TransitionRequest) -> dict:
    """Validate one transition and return a preview (no writes)."""
    student = db.get(Student, req.student_id)
    if student is None:
        raise AppError(Code.INVALID_REQUEST, "Unknown student.", {"student_id": str(req.student_id)})
    cur = current_placement(db, req.student_id)
    allowed, close_as, new_status, _ = _RULES[req.outcome]
    cur_status = HistoryStatus(cur.status) if cur else None
    if cur_status not in allowed:
        raise AppError(
            Code.CONFLICT,
            f"Cannot apply {req.outcome.value} to a student whose current placement is "
            f"{cur_status.value if cur_status else 'closed'}.",
            {"student_id": str(req.student_id)},
        )
    if req.outcome == Outcome.RE_ENTER and student.student_status != StudentStatus.WITHDRAWN:
        raise AppError(Code.CONFLICT, "Only withdrawn students can re-enter.", {"student_id": str(req.student_id)})
    if cur is not None and req.effective_date < cur.effective_from:
        raise AppError(Code.INVALID_REQUEST, "Effective date is before the current placement started.",
                       {"student_id": str(req.student_id)})

    new: dict | None = None
    if new_status is not None:
        # Defaults: keep current placement values unless the Admin provides new ones.
        ay = req.academic_year_id or (cur.academic_year_id if cur else None)
        yos = req.year_of_study or (cur.year_of_study if cur else None)
        dept = req.department_id or (cur.department_id if cur else student.department_id)
        batch = req.batch_id if req.batch_id is not None else (cur.batch_id if cur and req.outcome != Outcome.PROMOTE else None)
        sem = req.semester if req.semester is not None else (cur.semester if cur and req.outcome != Outcome.PROMOTE else None)
        if ay is None or yos is None or dept is None:
            raise AppError(Code.INVALID_REQUEST, "academic_year_id, year_of_study and department_id are required.",
                           {"student_id": str(req.student_id)})
        if req.outcome == Outcome.PROMOTE:
            if req.academic_year_id is None or req.year_of_study is None:
                raise AppError(Code.INVALID_REQUEST, "Promotion needs the new academic year and year of study.",
                               {"student_id": str(req.student_id)})
            if cur and req.academic_year_id == cur.academic_year_id and req.year_of_study <= cur.year_of_study:
                raise AppError(Code.INVALID_REQUEST, "Promotion must move the student forward.",
                               {"student_id": str(req.student_id)})
        _validate_placement(db, dept, ay, batch, yos)
        new = {"academic_year_id": ay, "year_of_study": yos, "semester": sem, "department_id": dept,
               "batch_id": batch, "status": new_status.value if hasattr(new_status, "value") else new_status}
    return {
        "student_id": str(req.student_id),
        "uid": student.uid,
        "name": student.user.display_name,
        "outcome": req.outcome.value,
        "effective_date": req.effective_date.isoformat(),
        "current": _hist_dict(cur) if cur else None,
        "close_current_as": close_as.value if close_as else None,
        "new_placement": new,
    }


def preview(db: Session, requests: list[TransitionRequest]) -> dict:
    items, errors = [], []
    seen: set[uuid.UUID] = set()
    for r in requests:
        if r.student_id in seen:
            errors.append({"student_id": str(r.student_id), "message": "Student appears more than once."})
            continue
        seen.add(r.student_id)
        try:
            items.append(_plan(db, r))
        except AppError as e:
            errors.append({"student_id": str(r.student_id), "message": e.message})
    return {"items": items, "errors": errors, "can_confirm": not errors and bool(items)}


def confirm(db: Session, admin: Principal, requests: list[TransitionRequest]) -> dict:
    """All-or-nothing: any invalid item aborts the whole batch."""
    staff_id = _admin_staff_id(db, admin)
    ids = sorted({r.student_id for r in requests})
    if len(ids) != len(requests):
        raise AppError(Code.INVALID_REQUEST, "Each student may appear only once per confirmation.")
    # Lock students in a stable order to avoid deadlocks between concurrent confirmations.
    db.scalars(select(Student).where(Student.student_id.in_(ids)).order_by(Student.student_id).with_for_update()).all()
    results = []
    now = utcnow()
    for r in requests:
        plan = _plan(db, r)
        cur = current_placement(db, r.student_id)
        _, close_as, _, student_status = _RULES[r.outcome]
        if cur is not None and close_as is not None:
            cur.effective_to = r.effective_date
            cur.status = close_as
            db.flush()
        new_id = None
        if plan["new_placement"]:
            n = plan["new_placement"]
            row = StudentAcademicHistory(
                student_id=r.student_id, academic_year_id=n["academic_year_id"], year_of_study=n["year_of_study"],
                semester=n["semester"], department_id=n["department_id"], batch_id=n["batch_id"], status=n["status"],
                effective_from=r.effective_date, confirmed_by_staff_id=staff_id, confirmed_at=now, note=r.note,
            )
            db.add(row)
            db.flush()
            new_id = row.history_id
        student = db.get(Student, r.student_id)
        student.student_status = student_status
        if plan["new_placement"]:
            student.department_id = plan["new_placement"]["department_id"]
        audit(db, "ACADEMIC_TRANSITION_CONFIRMED", admin.user_id, "STUDENT", r.student_id,
              outcome=r.outcome.value, closed=str(cur.history_id) if cur else None,
              opened=str(new_id) if new_id else None)
        results.append({**plan, "new_history_id": str(new_id) if new_id else None})
    db.commit()
    return {"confirmed": len(results), "items": results}


def _hist_dict(h: StudentAcademicHistory) -> dict:
    return {
        "history_id": str(h.history_id),
        "academic_year": h.academic_year.label if h.academic_year else None,
        "academic_year_id": h.academic_year_id,
        "year_of_study": h.year_of_study,
        "semester": h.semester,
        "department_id": h.department_id,
        "department": h.department.name if h.department else None,
        "batch_id": h.batch_id,
        "batch": h.batch.code if h.batch else None,
        "status": h.status,
        "effective_from": h.effective_from.isoformat(),
        "effective_to": h.effective_to.isoformat() if h.effective_to else None,
        "confirmed_at": h.confirmed_at.isoformat() if h.confirmed_at else None,
        "note": h.note,
    }


def history(db: Session, student_id: uuid.UUID) -> list[dict]:
    rows = db.scalars(
        select(StudentAcademicHistory)
        .where(StudentAcademicHistory.student_id == student_id)
        .order_by(StudentAcademicHistory.effective_from.desc(), StudentAcademicHistory.created_at.desc())
    ).all()
    return [_hist_dict(h) for h in rows]
