"""Role-scope policy (Decision D-09). The single place where role → data scope is defined.

This is a *proposed default* to be confirmed by the college. Hidden buttons in the app are not
security: every rule here is enforced on the server for every request.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.enums import RoleCode
from app.security.principal import Principal


@dataclass(frozen=True)
class EntryScope:
    """Which institutional entries a principal may see. `college=True` means no restriction."""

    college: bool = False
    department_ids: frozenset[int] = field(default_factory=frozenset)
    batch_ids: frozenset[int] = field(default_factory=frozenset)
    staff_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    reason_if_empty: str | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.college or self.department_ids or self.batch_ids or self.staff_ids)


def institutional_scope(p: Principal) -> EntryScope:
    if p.has(RoleCode.ADMIN, RoleCode.PRINCIPAL):
        return EntryScope(college=True)
    depts: set[int] = set()
    batches: set[int] = set(p.student_batch_ids) if p.has(RoleCode.STUDENT) else set()
    staff: set[uuid.UUID] = set()
    if p.has(RoleCode.HOD, RoleCode.PROFESSOR) and p.staff_department_id is not None:
        depts.add(p.staff_department_id)
    if p.has(RoleCode.HOD, RoleCode.PROFESSOR) and p.staff_id is not None:
        staff.add(p.staff_id)
    reason = None
    if not (depts or batches or staff):
        if p.has(RoleCode.STUDENT):
            reason = (
                "Your student account is not yet linked to a batch for the current academic year. "
                "Ask the Admin office to complete your academic placement."
            )
        else:
            reason = "Your staff profile is not linked to a department. Ask the Admin office to complete setup."
    return EntryScope(
        department_ids=frozenset(depts), batch_ids=frozenset(batches), staff_ids=frozenset(staff),
        reason_if_empty=reason,
    )


# Intents (institutional domain) restricted beyond "any authenticated role with entry scope".
_MONITORING = frozenset({RoleCode.HOD, RoleCode.PRINCIPAL, RoleCode.ADMIN})
INTENT_ROLE_RESTRICTIONS: dict[str, frozenset[RoleCode]] = {
    "FLOOR_ACTIVITY": _MONITORING,
    "ROOMS_WITH_CLASSES_AFTER_TIME": _MONITORING,
}

# Evaluated against the whole selected institutional timetable regardless of batch/department scope:
# * room intents describe facilities, not people;
# * professor free-time / scheduled location must see the professor's *complete* schedule,
#   otherwise a student would be told "free all day" just because the busy slots are for other
#   batches. They reveal only busy/free or the current scheduled room, not other batches' details.
SCOPE_FREE_INTENTS = frozenset({"FIND_FREE_ROOMS", "ROOM_FREE_NOW", "ROOM_SCHEDULE", "ROOM_SCHEDULE_FOR_DAY",
                                "PROFESSOR_FREE_TIME", "PROFESSOR_SCHEDULED_LOCATION"})


def intent_allowed(p: Principal, intent: str) -> bool:
    allowed = INTENT_ROLE_RESTRICTIONS.get(intent)
    return allowed is None or bool(p.roles & allowed)


def can_view_conflicts(p: Principal) -> bool:
    return p.has(RoleCode.HOD, RoleCode.PRINCIPAL, RoleCode.ADMIN)


def can_manage_institutional(p: Principal) -> bool:
    return p.is_admin
