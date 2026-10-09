"""Controlled vocabularies. Persisted as VARCHAR with CHECK constraints (see migration)."""
from __future__ import annotations

from enum import StrEnum


class RoleCode(StrEnum):
    STUDENT = "STUDENT"
    PROFESSOR = "PROFESSOR"
    HOD = "HOD"
    PRINCIPAL = "PRINCIPAL"
    ADMIN = "ADMIN"


class AccountStatus(StrEnum):
    INVITED = "INVITED"  # created by Admin, password not yet set
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISABLED = "DISABLED"


class StudentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    WITHDRAWN = "WITHDRAWN"
    GRADUATED = "GRADUATED"


class StaffStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AcademicYearStatus(StrEnum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class HistoryStatus(StrEnum):
    """Academic placement outcome for one history record."""
    ACTIVE = "ACTIVE"            # current placement, progressing normally
    REPEATING = "REPEATING"      # current placement, repeating the year
    PAUSED = "PAUSED"            # current placement, studies paused
    PROMOTED = "PROMOTED"        # closed: student moved on to next placement
    WITHDRAWN = "WITHDRAWN"      # closed: left the institution
    GRADUATED = "GRADUATED"      # closed: completed programme
    CLOSED = "CLOSED"            # closed for another administrative reason


OPEN_HISTORY_STATUSES = (HistoryStatus.ACTIVE, HistoryStatus.REPEATING, HistoryStatus.PAUSED)


class Domain(StrEnum):
    INSTITUTIONAL = "INSTITUTIONAL"
    PERSONAL = "PERSONAL"


class SelectionMode(StrEnum):
    REMEMBER_LAST = "REMEMBER_LAST"
    ALWAYS_USE_PRIMARY = "ALWAYS_USE_PRIMARY"


class SelectionType(StrEnum):
    PRIMARY = "PRIMARY"
    EXPLICIT_ARCHIVE = "EXPLICIT_ARCHIVE"


class ProcessingStatus(StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    READY = "READY"
    FAILED = "FAILED"
    UNUSABLE = "UNUSABLE"


SEARCHABLE_STATUSES = (ProcessingStatus.READY, ProcessingStatus.NEEDS_REVIEW)


class VerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    INCOMPLETE = "INCOMPLETE"
    REJECTED = "REJECTED"


class EntryKind(StrEnum):
    CLASS = "CLASS"
    BREAK = "BREAK"
    ACTIVITY = "ACTIVITY"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class TokenPurpose(StrEnum):
    INVITATION = "INVITATION"
    PASSWORD_RESET = "PASSWORD_RESET"


class AliasEntity(StrEnum):
    COURSE = "COURSE"
    STAFF = "STAFF"
    ROOM = "ROOM"
    BATCH = "BATCH"


def check_in(column: str, enum_cls: type[StrEnum]) -> str:
    values = ", ".join(f"'{v.value}'" for v in enum_cls)
    return f"{column} IN ({values})"
