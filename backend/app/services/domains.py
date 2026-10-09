"""Domain adapter: maps a Domain to its own, separate tables and label columns.

Code that must work for both domains asks this adapter for the right model. No function ever
receives both domains' models at once, which is how "never union/join across domains" is kept.
"""
from __future__ import annotations

import re
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


_GROUP = re.compile(r"\((?:batch|s\.?\s*n)[^)]*\)\s*$", re.I)
_PRACTICAL = re.compile(r"\b(lab|laboratory|practical|tutorial)\b", re.I)


def _course_display(entry: Any) -> str | None:
    """Course name for people: the subject's name, keeping what the printed label adds —
    "(Lab)"/"(Tutorial)", "(Open Elective)" and the student group ("(Batch1)")."""
    printed = entry.course_label_raw or ""
    resolved = entry.course_name_resolved
    name = entry.course.name if entry.course else None
    if name and resolved and resolved.lower().startswith(name.lower()):
        name = resolved                                   # "Data Structures (Lab)"
    elif name:
        kind = _PRACTICAL.search(printed)
        if kind and kind.group(0).lower() not in name.lower():
            name = f"{name} ({kind.group(0).title()})"
    else:
        name = resolved or printed or None
    group = _GROUP.search(printed)
    if name and group and group.group(0).strip() not in name:
        name = f"{name} {group.group(0).strip()}"
    return name


def entry_labels(entry: Any) -> dict[str, str | None]:
    """Uniform view of an entry's labels for serialisation. `course_code` is the label exactly as
    printed in the timetable (e.g. "PE III-TSDA -A"), so students can match it to the paper copy."""
    if isinstance(entry, InstitutionalTimetableEntry):
        return {
            "course": _course_display(entry),
            "course_code": entry.course_label_raw or (entry.course.course_code if entry.course else None),
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
