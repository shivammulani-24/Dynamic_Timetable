"""User, role and account-status management (Admin only — enforced at the router)."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import AccountStatus, HistoryStatus, RoleCode, TokenPurpose
from app.errors import AppError, Code, not_found
from app.models import (
    AcademicYear,
    Batch,
    Department,
    Role,
    Staff,
    Student,
    StudentAcademicHistory,
    UserAccount,
    UserPreference,
    UserRole,
)
from app.security.principal import Principal
from app.services.audit import audit
from app.services.auth import create_account_token, normalize_email, revoke_all_sessions
from app.services.mailer import send_email
from app.services.preferences import validate_timezone


def _role_ids(db: Session) -> dict[RoleCode, int]:
    return {RoleCode(r.code): r.role_id for r in db.scalars(select(Role))}


def _ensure_email_free(db: Session, email: str) -> str:
    e = normalize_email(email)
    if "@" not in e:
        raise AppError(Code.INVALID_REQUEST, "Enter a valid college email.", {"field": "college_email"})
    if db.scalar(select(UserAccount.user_id).where(UserAccount.college_email == e)):
        raise AppError(Code.CONFLICT, "An account with this email already exists.", {"field": "college_email"})
    return e


def _new_account(db: Session, admin: Principal, email: str, name: str, tz: str | None, roles: list[RoleCode]) -> tuple[UserAccount, str]:
    user = UserAccount(
        college_email=_ensure_email_free(db, email),
        display_name=name.strip(),
        timezone_id=validate_timezone(tz or "Asia/Kolkata"),
        account_status=AccountStatus.INVITED,
    )
    db.add(user)
    db.flush()
    ids = _role_ids(db)
    for r in set(roles):
        db.add(UserRole(user_id=user.user_id, role_id=ids[r], assigned_by_user_id=admin.user_id))
    db.add(UserPreference(user_id=user.user_id))
    token = create_account_token(db, user, TokenPurpose.INVITATION)
    return user, token


def _invitation_result(user: UserAccount, token: str) -> dict:
    sent = send_email(user.college_email, "Activate your timetable account",
                      f"Your activation code: {token}\nOpen the app and choose 'Activate account'.")
    out: dict = {"user_id": str(user.user_id), "invitation_email_sent": sent}
    if get_settings().dev_tokens_exposed:
        out["dev_invitation_token"] = token  # development only; never in production
    return out


def create_student(db: Session, admin: Principal, *, email: str, name: str, uid: str, department_id: int,
                   academic_year_id: int, year_of_study: int, semester: int | None, batch_id: int | None,
                   effective_from: date, timezone: str | None = None) -> dict:
    """Fresher registration: new identity + initial history row. Existing students are never duplicated."""
    uid = uid.strip()
    if db.scalar(select(Student.student_id).where(Student.uid == uid)):
        raise AppError(Code.CONFLICT, "A student with this UID already exists. Use promotion for continuing students.",
                       {"field": "uid"})
    _validate_placement(db, department_id, academic_year_id, batch_id, year_of_study)
    user, token = _new_account(db, admin, email, name, timezone, [RoleCode.STUDENT])
    student = Student(user_id=user.user_id, uid=uid, department_id=department_id)
    db.add(student)
    db.flush()
    staff_id = _admin_staff_id(db, admin)
    db.add(StudentAcademicHistory(
        student_id=student.student_id, academic_year_id=academic_year_id, year_of_study=year_of_study,
        semester=semester, department_id=department_id, batch_id=batch_id, status=HistoryStatus.ACTIVE,
        effective_from=effective_from, confirmed_by_staff_id=staff_id,
        confirmed_at=_now(), note="Initial registration",
    ))
    audit(db, "STUDENT_REGISTERED", admin.user_id, "STUDENT", student.student_id, uid=uid)
    db.commit()
    out = _invitation_result(user, token)
    out["student_id"] = str(student.student_id)
    return out


def create_staff(db: Session, admin: Principal, *, email: str, name: str, roles: list[RoleCode],
                 department_id: int | None, short_code: str | None, designation: str | None,
                 timezone: str | None = None) -> dict:
    if RoleCode.STUDENT in roles:
        raise AppError(Code.INVALID_REQUEST, "Staff accounts cannot hold the STUDENT role.")
    if not roles:
        raise AppError(Code.INVALID_REQUEST, "Assign at least one staff role.")
    if department_id is not None and db.get(Department, department_id) is None:
        raise AppError(Code.INVALID_REQUEST, "Unknown department.", {"field": "department_id"})
    if RoleCode.HOD in roles and department_id is None:
        raise AppError(Code.INVALID_REQUEST, "A HOD must belong to a department.", {"field": "department_id"})
    user, token = _new_account(db, admin, email, name, timezone, roles)
    staff = Staff(user_id=user.user_id, department_id=department_id,
                  short_code=(short_code or "").strip().upper() or None, designation=designation)
    db.add(staff)
    db.flush()
    audit(db, "STAFF_REGISTERED", admin.user_id, "STAFF", staff.staff_id, roles=[r.value for r in roles])
    db.commit()
    out = _invitation_result(user, token)
    out["staff_id"] = str(staff.staff_id)
    return out


def reissue_invitation(db: Session, admin: Principal, user_id: uuid.UUID) -> dict:
    user = db.get(UserAccount, user_id)
    if user is None:
        raise not_found("User")
    if user.account_status != AccountStatus.INVITED:
        raise AppError(Code.CONFLICT, "This account has already been activated.")
    token = create_account_token(db, user, TokenPurpose.INVITATION)
    audit(db, "INVITATION_REISSUED", admin.user_id, "USER", user.user_id)
    db.commit()
    return _invitation_result(user, token)


def set_roles(db: Session, admin: Principal, user_id: uuid.UUID, roles: list[RoleCode]) -> list[str]:
    user = db.get(UserAccount, user_id)
    if user is None:
        raise not_found("User")
    if user.user_id == admin.user_id and RoleCode.ADMIN not in roles:
        raise AppError(Code.CONFLICT, "You cannot remove your own Admin role.")
    is_student = db.scalar(select(Student.student_id).where(Student.user_id == user_id)) is not None
    is_staff = db.scalar(select(Staff.staff_id).where(Staff.user_id == user_id)) is not None
    if any(r != RoleCode.STUDENT for r in roles) and not is_staff:
        raise AppError(Code.INVALID_REQUEST, "Staff roles require a staff profile.")
    if RoleCode.STUDENT in roles and not is_student:
        raise AppError(Code.INVALID_REQUEST, "The STUDENT role requires a student profile.")
    if not roles:
        raise AppError(Code.INVALID_REQUEST, "A user must keep at least one role.")
    ids = _role_ids(db)
    before = sorted(r.role.code for r in user.roles)
    db.execute(delete(UserRole).where(UserRole.user_id == user_id))
    for r in set(roles):
        db.add(UserRole(user_id=user_id, role_id=ids[r], assigned_by_user_id=admin.user_id))
    user.token_version += 1  # force re-authentication so new permissions apply everywhere
    audit(db, "ROLES_CHANGED", admin.user_id, "USER", user_id, before=before, after=sorted(r.value for r in roles))
    db.commit()
    return sorted(r.value for r in roles)


def set_status(db: Session, admin: Principal, user_id: uuid.UUID, status: AccountStatus) -> None:
    user = db.get(UserAccount, user_id)
    if user is None:
        raise not_found("User")
    if user.user_id == admin.user_id:
        raise AppError(Code.CONFLICT, "You cannot change the status of your own account.")
    if status == AccountStatus.INVITED:
        raise AppError(Code.INVALID_REQUEST, "Use re-invite to send a new activation link.")
    if status == AccountStatus.ACTIVE and user.password_hash is None:
        raise AppError(Code.CONFLICT, "This user has not activated their account yet.")
    before = user.account_status
    user.account_status = status
    if status != AccountStatus.ACTIVE:
        revoke_all_sessions(db, user)
    audit(db, "ACCOUNT_STATUS_CHANGED", admin.user_id, "USER", user_id, before=before, after=status.value)
    db.commit()


def _validate_placement(db: Session, department_id: int, academic_year_id: int, batch_id: int | None, year_of_study: int) -> None:
    if db.get(Department, department_id) is None:
        raise AppError(Code.INVALID_REQUEST, "Unknown department.", {"field": "department_id"})
    ay = db.get(AcademicYear, academic_year_id)
    if ay is None:
        raise AppError(Code.INVALID_REQUEST, "Unknown academic year.", {"field": "academic_year_id"})
    if ay.status == "CLOSED":
        raise AppError(Code.INVALID_REQUEST, f"Academic year {ay.label} is closed.", {"field": "academic_year_id"})
    if year_of_study < 1 or year_of_study > 6:
        raise AppError(Code.INVALID_REQUEST, "Year of study must be between 1 and 6.", {"field": "year_of_study"})
    if batch_id is not None:
        b = db.get(Batch, batch_id)
        if b is None or b.department_id != department_id:
            raise AppError(Code.INVALID_REQUEST, "The batch does not belong to that department.", {"field": "batch_id"})


def _admin_staff_id(db: Session, admin: Principal) -> uuid.UUID:
    if admin.staff_id is None:
        raise AppError(Code.CONFLICT, "Your Admin account needs a staff profile to confirm academic changes.")
    return admin.staff_id


def _now():
    from app.security.tokens import utcnow

    return utcnow()
