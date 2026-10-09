"""The authenticated principal: identity + roles + academic placement, loaded from the DB per request."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import RoleCode
from app.models import Batch, Role, Staff, Student, StudentAcademicHistory, UserAccount, UserRole


@dataclass(frozen=True)
class Principal:
    user_id: uuid.UUID
    email: str
    display_name: str
    timezone_id: str
    roles: frozenset[RoleCode]
    staff_id: uuid.UUID | None = None
    staff_department_id: int | None = None
    student_id: uuid.UUID | None = None
    student_department_id: int | None = None
    # Current placement batch plus its ancestors (lab sub-group -> division).
    student_batch_ids: frozenset[int] = field(default_factory=frozenset)
    student_batch_codes: tuple[str, ...] = ()

    def has(self, *roles: RoleCode) -> bool:
        return any(r in self.roles for r in roles)

    @property
    def is_admin(self) -> bool:
        return RoleCode.ADMIN in self.roles


def load_principal(db: Session, user: UserAccount) -> Principal:
    role_codes = frozenset(
        RoleCode(code)
        for code in db.scalars(
            select(Role.code).join(UserRole, UserRole.role_id == Role.role_id).where(UserRole.user_id == user.user_id)
        )
    )
    staff = db.scalar(select(Staff).where(Staff.user_id == user.user_id))
    student = db.scalar(select(Student).where(Student.user_id == user.user_id))
    batch_ids: set[int] = set()
    batch_codes: list[str] = []
    student_dept = None
    if student is not None:
        hist = db.scalar(
            select(StudentAcademicHistory).where(
                StudentAcademicHistory.student_id == student.student_id,
                StudentAcademicHistory.effective_to.is_(None),
            )
        )
        if hist is not None:
            student_dept = hist.department_id
            bid = hist.batch_id
            seen = 0
            while bid is not None and seen < 5:  # walk lab-group -> division chain
                b = db.get(Batch, bid)
                if b is None:
                    break
                batch_ids.add(b.batch_id)
                batch_codes.append(b.code)
                bid = b.parent_batch_id
                seen += 1
    return Principal(
        user_id=user.user_id,
        email=user.college_email,
        display_name=user.display_name,
        timezone_id=user.timezone_id,
        roles=role_codes,
        staff_id=staff.staff_id if staff else None,
        staff_department_id=staff.department_id if staff else None,
        student_id=student.student_id if student else None,
        student_department_id=student_dept,
        student_batch_ids=frozenset(batch_ids),
        student_batch_codes=tuple(batch_codes),
    )

