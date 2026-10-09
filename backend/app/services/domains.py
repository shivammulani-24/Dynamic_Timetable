"""Domain adapter: maps a Domain to its own, separate tables and label columns.

Code that must work for both domains asks this adapter for the right model. No function ever
receives both domains' models at once, which is how "never union/join across domains" is kept.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.enums import Domain
from app.models import (
    InstitutionalTimetable,
    InstitutionalTimetableEntry,
    InstitutionalTimetableSection,
    PersonalTimetable,
    PersonalTimetableEntry,
    PersonalTimetableSection,
)


@dataclass(frozen=True)
class DomainModels:
    domain: Domain
    meta: Any
    entry: Any
    section: Any
    course_label: Any
    staff_label: Any
    batch_label: Any
    room_label: Any

    @property
    def is_institutional(self) -> bool:
        return self.domain == Domain.INSTITUTIONAL


INSTITUTIONAL = DomainModels(
    Domain.INSTITUTIONAL,
    InstitutionalTimetable,
    InstitutionalTimetableEntry,
    InstitutionalTimetableSection,
    InstitutionalTimetableEntry.course_label_raw,
    InstitutionalTimetableEntry.staff_label_raw,
    InstitutionalTimetableEntry.batch_label_raw,
    InstitutionalTimetableEntry.room_label_raw,
)
PERSONAL = DomainModels(
    Domain.PERSONAL,
    PersonalTimetable,
    PersonalTimetableEntry,
    PersonalTimetableSection,
    PersonalTimetableEntry.course_label,
    PersonalTimetableEntry.professor_label,
    PersonalTimetableEntry.batch_label,
    PersonalTimetableEntry.room_label,
)


def models_for(domain: Domain | str) -> DomainModels:
    return INSTITUTIONAL if Domain(domain) == Domain.INSTITUTIONAL else PERSONAL


def entry_labels(entry: Any) -> dict[str, str | None]:
    """Uniform view of an entry's labels for serialisation."""
    if isinstance(entry, InstitutionalTimetableEntry):
        return {
            "course": entry.course.name if entry.course else (entry.course_name_resolved or entry.course_label_raw),
            "course_code": entry.course.course_code if entry.course else entry.course_label_raw,
            "professor": entry.staff.user.display_name if entry.staff else (entry.staff_name_resolved or entry.staff_label_raw),
            "professor_code": entry.staff_label_raw,
            "batch": entry.batch.code if entry.batch else entry.batch_label_raw,
            "room": entry.room.room_code if entry.room else entry.room_label_raw,
            "floor": entry.room.floor_label if entry.room else None,
        }
    return {
        "course": entry.course_name_resolved or entry.course_label,
        "course_code": entry.course_label,
        "professor": entry.staff_name_resolved or entry.professor_label,
        "professor_code": entry.professor_label,
        "batch": entry.batch_label,
        "room": entry.room_label,
        "floor": None,
    }
