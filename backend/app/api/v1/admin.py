"""Admin-only master data, user management, promotion and audit endpoints."""
from __future__ import annotations

import uuid
from datetime import date, time
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.common import Page
from app.db import get_db
from app.enums import AcademicYearStatus, AccountStatus, AliasEntity, RoleCode
from app.errors import AppError, Code, not_found
from app.models import (
    AcademicYear,
    AuditEvent,
    Batch,
    Course,
    Department,
    EntityAlias,
    InstitutionConfig,
    Room,
    Staff,
    Student,
    UserAccount,
)
from app.security.deps import require_admin
from app.security.principal import Principal
from app.services import academics, users
from app.services.audit import audit
from app.services.matching import normalize_label

router = APIRouter(prefix="/admin", tags=["admin"])


def _commit(db: Session, what: str) -> None:
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise AppError(Code.CONFLICT, f"This {what} conflicts with an existing record (duplicate or still referenced).",
                       {"constraint": getattr(getattr(e.orig, "diag", None), "constraint_name", None)})


# --------------------------------------------------------------------------- departments


class DepartmentIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=120)
    is_active: bool = True


def _dept(d: Department) -> dict:
    return {"department_id": d.department_id, "code": d.code, "name": d.name, "is_active": d.is_active}


@router.get("/departments")
def list_departments(_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return {"items": [_dept(d) for d in db.scalars(select(Department).order_by(Department.code))]}


@router.post("/departments", status_code=201)
def create_department(body: DepartmentIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    d = Department(code=body.code.strip().upper(), name=body.name.strip(), is_active=body.is_active)
    db.add(d)
    db.flush()
    audit(db, "DEPARTMENT_CREATED", a.user_id, "DEPARTMENT", d.department_id)
    _commit(db, "department")
    return _dept(d)


@router.put("/departments/{department_id}")
def update_department(department_id: int, body: DepartmentIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    d = db.get(Department, department_id) or _raise(not_found("Department"))
    d.code, d.name, d.is_active = body.code.strip().upper(), body.name.strip(), body.is_active
    audit(db, "DEPARTMENT_UPDATED", a.user_id, "DEPARTMENT", department_id)
    _commit(db, "department")
    return _dept(d)


def _raise(e: AppError):
    raise e


# --------------------------------------------------------------------------- academic years


class AcademicYearIn(BaseModel):
    label: str = Field(pattern=r"^\d{4}-\d{4}$")
    start_date: date
    end_date: date
    status: AcademicYearStatus = AcademicYearStatus.PLANNED


def _ay(y: AcademicYear) -> dict:
    return {"academic_year_id": y.academic_year_id, "label": y.label, "start_date": y.start_date.isoformat(),
            "end_date": y.end_date.isoformat(), "status": y.status}


@router.get("/academic-years")
def list_years(_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return {"items": [_ay(y) for y in db.scalars(select(AcademicYear).order_by(AcademicYear.start_date.desc()))]}


@router.post("/academic-years", status_code=201)
def create_year(body: AcademicYearIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    if body.end_date < body.start_date:
        raise AppError(Code.INVALID_REQUEST, "End date must be after start date.")
    if body.status == AcademicYearStatus.ACTIVE:
        _close_active(db)
    y = AcademicYear(**body.model_dump())
    db.add(y)
    db.flush()
    audit(db, "ACADEMIC_YEAR_CREATED", a.user_id, "ACADEMIC_YEAR", y.academic_year_id, label=y.label)
    _commit(db, "academic year")
    return _ay(y)


def _close_active(db: Session) -> None:
    # Single ACTIVE year: lock and demote the current one in the same transaction.
    db.execute(select(AcademicYear).where(AcademicYear.status == "ACTIVE").with_for_update())
    db.execute(update(AcademicYear).where(AcademicYear.status == "ACTIVE").values(status="CLOSED"))


@router.put("/academic-years/{year_id}")
def update_year(year_id: int, body: AcademicYearIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    y = db.get(AcademicYear, year_id) or _raise(not_found("Academic year"))
    if body.status == AcademicYearStatus.ACTIVE and y.status != "ACTIVE":
        _close_active(db)
    for k, v in body.model_dump().items():
        setattr(y, k, v)
    audit(db, "ACADEMIC_YEAR_UPDATED", a.user_id, "ACADEMIC_YEAR", year_id, status=body.status.value)
    _commit(db, "academic year")
    return _ay(y)


# --------------------------------------------------------------------------- batches


class BatchIn(BaseModel):
    department_id: int
    code: str = Field(min_length=1, max_length=40)
    cohort_label: str = Field(min_length=1, max_length=40)
    division_label: str = Field(min_length=1, max_length=20)
    program_year: int = Field(ge=1, le=6)
    parent_batch_id: int | None = None
    is_active: bool = True


def _batch(b: Batch) -> dict:
    return {"batch_id": b.batch_id, "department_id": b.department_id, "department": b.department.code if b.department else None,
            "code": b.code, "cohort_label": b.cohort_label, "division_label": b.division_label,
            "program_year": b.program_year, "parent_batch_id": b.parent_batch_id, "is_active": b.is_active}


@router.get("/batches")
def list_batches(department_id: int | None = None, _: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(Batch).order_by(Batch.code)
    if department_id:
        q = q.where(Batch.department_id == department_id)
    return {"items": [_batch(b) for b in db.scalars(q)]}


def _check_batch(db: Session, body: BatchIn, batch_id: int | None = None) -> None:
    if db.get(Department, body.department_id) is None:
        raise AppError(Code.INVALID_REQUEST, "Unknown department.", {"field": "department_id"})
    if body.parent_batch_id is not None:
        parent = db.get(Batch, body.parent_batch_id)
        if parent is None or parent.department_id != body.department_id or parent.batch_id == batch_id:
            raise AppError(Code.INVALID_REQUEST, "Parent batch must be another batch of the same department.")
        if parent.parent_batch_id is not None:
            raise AppError(Code.INVALID_REQUEST, "Only one level of sub-groups is supported.")


@router.post("/batches", status_code=201)
def create_batch(body: BatchIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    _check_batch(db, body)
    b = Batch(**{**body.model_dump(), "code": body.code.strip().upper()})
    db.add(b)
    db.flush()
    audit(db, "BATCH_CREATED", a.user_id, "BATCH", b.batch_id)
    _commit(db, "batch")
    return _batch(b)


@router.put("/batches/{batch_id}")
def update_batch(batch_id: int, body: BatchIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    b = db.get(Batch, batch_id) or _raise(not_found("Batch"))
    _check_batch(db, body, batch_id)
    for k, v in body.model_dump().items():
        setattr(b, k, v.strip().upper() if k == "code" else v)
    audit(db, "BATCH_UPDATED", a.user_id, "BATCH", batch_id)
    _commit(db, "batch")
    return _batch(b)


# --------------------------------------------------------------------------- courses


class CourseIn(BaseModel):
    department_id: int | None = None
    course_code: str | None = Field(None, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    is_active: bool = True


def _course(c: Course) -> dict:
    return {"course_id": c.course_id, "department_id": c.department_id, "course_code": c.course_code, "name": c.name,
            "is_active": c.is_active}


@router.get("/courses")
def list_courses(_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return {"items": [_course(c) for c in db.scalars(select(Course).order_by(Course.name))]}


@router.post("/courses", status_code=201)
def create_course(body: CourseIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    c = Course(**{**body.model_dump(), "course_code": (body.course_code or "").strip().upper() or None})
    db.add(c)
    db.flush()
    audit(db, "COURSE_CREATED", a.user_id, "COURSE", c.course_id)
    _commit(db, "course")
    return _course(c)


@router.put("/courses/{course_id}")
def update_course(course_id: int, body: CourseIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(Course, course_id) or _raise(not_found("Course"))
    c.department_id, c.name, c.is_active = body.department_id, body.name, body.is_active
    c.course_code = (body.course_code or "").strip().upper() or None
    audit(db, "COURSE_UPDATED", a.user_id, "COURSE", course_id)
    _commit(db, "course")
    return _course(c)


# --------------------------------------------------------------------------- rooms


class RoomIn(BaseModel):
    room_code: str = Field(min_length=1, max_length=40)
    building: str | None = Field(None, max_length=100)
    floor_label: str | None = Field(None, max_length=40)
    room_type: str | None = Field(None, max_length=40)
    capacity: int | None = Field(None, gt=0)
    is_active: bool = True


def _room(r: Room) -> dict:
    return {"room_id": r.room_id, "room_code": r.room_code, "building": r.building, "floor_label": r.floor_label,
            "room_type": r.room_type, "capacity": r.capacity, "is_active": r.is_active}


@router.get("/rooms")
def list_rooms(_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return {"items": [_room(r) for r in db.scalars(select(Room).order_by(Room.room_code))]}


@router.post("/rooms", status_code=201)
def create_room(body: RoomIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    r = Room(**{**body.model_dump(), "room_code": body.room_code.strip()})
    db.add(r)
    db.flush()
    audit(db, "ROOM_CREATED", a.user_id, "ROOM", r.room_id)
    _commit(db, "room")
    return _room(r)


@router.put("/rooms/{room_id}")
def update_room(room_id: int, body: RoomIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(Room, room_id) or _raise(not_found("Room"))
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    audit(db, "ROOM_UPDATED", a.user_id, "ROOM", room_id)
    _commit(db, "room")
    return _room(r)


# --------------------------------------------------------------------------- aliases


class AliasIn(BaseModel):
    entity_type: AliasEntity
    alias: str = Field(min_length=1, max_length=120)
    entity_id: str = Field(min_length=1, max_length=64)


_ALIAS_TARGET = {AliasEntity.COURSE: (Course, int), AliasEntity.ROOM: (Room, int), AliasEntity.BATCH: (Batch, int),
                 AliasEntity.STAFF: (Staff, uuid.UUID)}


@router.get("/aliases")
def list_aliases(entity_type: AliasEntity | None = None, _: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(EntityAlias).order_by(EntityAlias.entity_type, EntityAlias.alias)
    if entity_type:
        q = q.where(EntityAlias.entity_type == entity_type.value)
    return {"items": [{"alias_id": x.alias_id, "entity_type": x.entity_type, "alias": x.alias, "entity_id": x.entity_id}
                      for x in db.scalars(q)]}


@router.post("/aliases", status_code=201)
def create_alias(body: AliasIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    model, conv = _ALIAS_TARGET[body.entity_type]
    try:
        target = db.get(model, conv(body.entity_id))
    except ValueError:
        target = None
    if target is None:
        raise AppError(Code.INVALID_REQUEST, "The alias target does not exist.", {"field": "entity_id"})
    x = EntityAlias(entity_type=body.entity_type.value, alias=body.alias.strip(), alias_normalized=normalize_label(body.alias),
                    entity_id=body.entity_id, created_by_user_id=a.user_id)
    db.add(x)
    db.flush()
    audit(db, "ALIAS_CREATED", a.user_id, "ALIAS", x.alias_id, entity_type=x.entity_type)
    _commit(db, "alias")
    return {"alias_id": x.alias_id, "entity_type": x.entity_type, "alias": x.alias, "entity_id": x.entity_id}


@router.delete("/aliases/{alias_id}")
def delete_alias(alias_id: int, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    x = db.get(EntityAlias, alias_id) or _raise(not_found("Alias"))
    db.delete(x)
    audit(db, "ALIAS_DELETED", a.user_id, "ALIAS", alias_id)
    db.commit()
    return {"status": "OK"}


# --------------------------------------------------------------------------- institution config


class ConfigIn(BaseModel):
    institution_name: str | None = Field(None, max_length=200)
    week_start_day: int | None = Field(None, ge=1, le=7)
    lunch_boundary: time | None = None
    working_hours_start: time | None = None
    working_hours_end: time | None = None
    next_class_lookahead_days: int = Field(7, ge=0, le=14)


def _cfg(c: InstitutionConfig) -> dict:
    f = lambda t: t.strftime("%H:%M") if t else None  # noqa: E731
    return {"institution_name": c.institution_name, "week_start_day": c.week_start_day, "lunch_boundary": f(c.lunch_boundary),
            "working_hours_start": f(c.working_hours_start), "working_hours_end": f(c.working_hours_end),
            "next_class_lookahead_days": c.next_class_lookahead_days}


@router.get("/config")
def get_config(_: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return _cfg(db.get(InstitutionConfig, 1))


@router.put("/config")
def put_config(body: ConfigIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(InstitutionConfig, 1, with_for_update=True)
    if body.working_hours_start and body.working_hours_end and body.working_hours_end <= body.working_hours_start:
        raise AppError(Code.INVALID_REQUEST, "Working hours must end after they start.")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    c.updated_by_user_id = a.user_id
    audit(db, "INSTITUTION_CONFIG_UPDATED", a.user_id, "CONFIG", 1, **{k: str(v) if v is not None else None for k, v in body.model_dump().items()})
    db.commit()
    return _cfg(c)


# --------------------------------------------------------------------------- users


def _user_row(db: Session, u: UserAccount) -> dict:
    st = db.scalar(select(Student).where(Student.user_id == u.user_id))
    sf = db.scalar(select(Staff).where(Staff.user_id == u.user_id))
    return {
        "user_id": str(u.user_id), "email": u.college_email, "display_name": u.display_name,
        "account_status": u.account_status, "roles": sorted(r.role.code for r in u.roles),
        "student_id": str(st.student_id) if st else None, "uid": st.uid if st else None,
        "student_status": st.student_status if st else None,
        "staff_id": str(sf.staff_id) if sf else None, "staff_department_id": sf.department_id if sf else None,
        "short_code": sf.short_code if sf else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


@router.get("/users")
def list_users(
    q: str | None = Query(None, max_length=100),
    role: RoleCode | None = None,
    status: AccountStatus | None = None,
    page: Page = Depends(),
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(UserAccount)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.outerjoin(Student, Student.user_id == UserAccount.user_id).where(
            or_(UserAccount.college_email.like(like), func.lower(UserAccount.display_name).like(like), func.lower(Student.uid).like(like))
        )
    if role:
        from app.models import Role, UserRole

        stmt = stmt.where(UserAccount.user_id.in_(
            select(UserRole.user_id).join(Role, Role.role_id == UserRole.role_id).where(Role.code == role.value)))
    if status:
        stmt = stmt.where(UserAccount.account_status == status.value)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(UserAccount.display_name).limit(page.limit).offset(page.offset)).unique().all()
    return page.envelope([_user_row(db, u) for u in rows], total)


@router.get("/users/{user_id}")
def get_user(user_id: uuid.UUID, _: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    u = db.get(UserAccount, user_id) or _raise(not_found("User"))
    out = _user_row(db, u)
    if out["student_id"]:
        out["academic_history"] = academics.history(db, uuid.UUID(out["student_id"]))
    return out


class StudentIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=160)
    uid: str = Field(min_length=1, max_length=64)
    department_id: int
    academic_year_id: int
    year_of_study: int = Field(ge=1, le=6)
    semester: int | None = Field(None, ge=1, le=12)
    batch_id: int | None = None
    effective_from: date
    timezone: str | None = None


@router.post("/students", status_code=201)
def create_student(body: StudentIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return users.create_student(db, a, email=body.email, name=body.display_name, uid=body.uid,
                                department_id=body.department_id, academic_year_id=body.academic_year_id,
                                year_of_study=body.year_of_study, semester=body.semester, batch_id=body.batch_id,
                                effective_from=body.effective_from, timezone=body.timezone)


class StaffIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    display_name: str = Field(min_length=1, max_length=160)
    roles: list[RoleCode] = Field(min_length=1)
    department_id: int | None = None
    short_code: str | None = Field(None, max_length=20)
    designation: str | None = Field(None, max_length=80)
    timezone: str | None = None


@router.post("/staff", status_code=201)
def create_staff(body: StaffIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return users.create_staff(db, a, email=body.email, name=body.display_name, roles=body.roles,
                              department_id=body.department_id, short_code=body.short_code,
                              designation=body.designation, timezone=body.timezone)


class StaffPatch(BaseModel):
    department_id: int | None = None
    short_code: str | None = Field(None, max_length=20)
    designation: str | None = Field(None, max_length=80)
    display_name: str | None = Field(None, max_length=160)


@router.patch("/staff/{staff_id}")
def update_staff(staff_id: uuid.UUID, body: StaffPatch, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(Staff, staff_id) or _raise(not_found("Staff"))
    data = body.model_dump(exclude_unset=True)
    if "department_id" in data:
        if data["department_id"] is not None and db.get(Department, data["department_id"]) is None:
            raise AppError(Code.INVALID_REQUEST, "Unknown department.")
        s.department_id = data["department_id"]
    if "short_code" in data:
        s.short_code = (data["short_code"] or "").strip().upper() or None
    if "designation" in data:
        s.designation = data["designation"]
    if data.get("display_name"):
        s.user.display_name = data["display_name"].strip()
    audit(db, "STAFF_UPDATED", a.user_id, "STAFF", staff_id)
    _commit(db, "staff")
    return {"status": "OK"}


class RolesIn(BaseModel):
    roles: list[RoleCode] = Field(min_length=1)


@router.put("/users/{user_id}/roles")
def put_roles(user_id: uuid.UUID, body: RolesIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return {"roles": users.set_roles(db, a, user_id, body.roles)}


class StatusIn(BaseModel):
    account_status: AccountStatus


@router.put("/users/{user_id}/status")
def put_status(user_id: uuid.UUID, body: StatusIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    users.set_status(db, a, user_id, body.account_status)
    return {"status": "OK"}


@router.post("/users/{user_id}/reinvite")
def reinvite(user_id: uuid.UUID, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return users.reissue_invitation(db, a, user_id)


# --------------------------------------------------------------------------- promotion


class TransitionIn(BaseModel):
    student_id: uuid.UUID
    outcome: academics.Outcome
    effective_date: date
    academic_year_id: int | None = None
    year_of_study: int | None = Field(None, ge=1, le=6)
    semester: int | None = Field(None, ge=1, le=12)
    department_id: int | None = None
    batch_id: int | None = None
    note: str | None = Field(None, max_length=300)


class TransitionsIn(BaseModel):
    items: list[TransitionIn] = Field(min_length=1, max_length=500)


def _reqs(body: TransitionsIn) -> list[academics.TransitionRequest]:
    return [academics.TransitionRequest(**i.model_dump()) for i in body.items]


@router.post("/promotions/preview")
def promotion_preview(body: TransitionsIn, _: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return academics.preview(db, _reqs(body))


@router.post("/promotions/confirm")
def promotion_confirm(body: TransitionsIn, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    return academics.confirm(db, a, _reqs(body))


@router.get("/students/eligible")
def eligible_students(
    batch_id: int | None = None,
    academic_year_id: int | None = None,
    page: Page = Depends(),
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Students with an open placement, filterable by batch / academic year (promotion candidates)."""
    from app.models import StudentAcademicHistory as H

    stmt = select(Student, H).join(H, (H.student_id == Student.student_id) & H.effective_to.is_(None))
    if batch_id:
        stmt = stmt.where(H.batch_id == batch_id)
    if academic_year_id:
        stmt = stmt.where(H.academic_year_id == academic_year_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(stmt.order_by(Student.uid).limit(page.limit).offset(page.offset)).all()
    items = [{"student_id": str(s.student_id), "uid": s.uid, "name": s.user.display_name, "student_status": s.student_status,
              "current": academics._hist_dict(h)} for s, h in rows]
    return page.envelope(items, total)


# --------------------------------------------------------------------------- audit


@router.get("/audit")
def audit_log(
    event_type: str | None = Query(None, max_length=80),
    page: Page = Depends(),
    _: Principal = Depends(require_admin),
    db: Session = Depends(get_db),
):
    stmt = select(AuditEvent)
    if event_type:
        stmt = stmt.where(AuditEvent.event_type == event_type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditEvent.occurred_at.desc()).limit(page.limit).offset(page.offset)).all()
    names: dict[Any, str] = {}
    ids = {r.actor_user_id for r in rows if r.actor_user_id}
    if ids:
        names = {u.user_id: u.display_name for u in db.scalars(select(UserAccount).where(UserAccount.user_id.in_(ids)))}
    return page.envelope([
        {"audit_event_id": str(r.audit_event_id), "event_type": r.event_type, "actor": names.get(r.actor_user_id),
         "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None, "target_type": r.target_type,
         "target_id": r.target_id, "occurred_at": r.occurred_at.isoformat(), "request_id": r.request_id, "details": r.details}
        for r in rows
    ], total)
