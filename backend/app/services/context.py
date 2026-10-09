"""Server-resolved search context (API Contract §3, SRS §5).

Client-supplied domain / timetable id are *hints*. This module validates them against the
authenticated principal and persisted preferences, and never falls back across domains.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.enums import Domain, ProcessingStatus, SelectionMode, SelectionType
from app.errors import AppError, Code
from app.security.principal import Principal
from app.services.preferences import get_or_create_preferences
from app.services.timetables import get_timetable, primary_id


@dataclass
class SearchContext:
    principal: Principal
    domain: Domain
    selection_type: SelectionType
    timetable: Any
    timezone: str
    now: datetime  # aware, in the user's timezone
    warnings: list[dict] = field(default_factory=list)

    @property
    def timetable_id(self) -> uuid.UUID:
        return self.timetable.timetable_id

    def as_dict(self) -> dict:
        return {
            "domain": self.domain.value,
            "selection_type": self.selection_type.value,
            "timetable_id": str(self.timetable.timetable_id),
            "timetable_title": self.timetable.title,
            "processing_status": self.timetable.processing_status,
            "timezone": self.timezone,
            "now": self.now.isoformat(),
        }


class Clock:
    """Injectable clock so tests can control 'now'. Always the server's time, never the client's."""

    _fixed: datetime | None = None

    @classmethod
    def now(cls, tz: str) -> datetime:
        base = cls._fixed or datetime.now(ZoneInfo("UTC"))
        return base.astimezone(ZoneInfo(tz))

    @classmethod
    def freeze(cls, at: datetime | None) -> None:
        cls._fixed = at


def parse_domain(value: Any, default: Domain | None = None) -> Domain:
    if value is None:
        if default is None:
            raise AppError(Code.INVALID_REQUEST, "domain is required.", {"field": "domain"})
        return default
    try:
        return Domain(str(value).upper())
    except ValueError:
        raise AppError(Code.INVALID_REQUEST, "domain must be INSTITUTIONAL or PERSONAL.", {"field": "domain"})


def resolve_context(
    db: Session,
    p: Principal,
    domain_hint: Any = None,
    selection: dict | None = None,
    *,
    remember: bool = True,
) -> SearchContext:
    pref = get_or_create_preferences(db, p.user_id)
    domain = parse_domain(domain_hint, Domain(pref.last_active_domain) if pref.last_active_domain else Domain.INSTITUTIONAL)
    warnings: list[dict] = []
    sel_type_raw = (selection or {}).get("type")
    sel_id = (selection or {}).get("timetable_id")

    tt = None
    sel_type = SelectionType.PRIMARY
    if sel_type_raw is not None:
        try:
            sel_type = SelectionType(str(sel_type_raw).upper())
        except ValueError:
            raise AppError(Code.INVALID_REQUEST, "selection.type must be PRIMARY or EXPLICIT_ARCHIVE.")
        if sel_type == SelectionType.EXPLICIT_ARCHIVE:
            if not sel_id:
                raise AppError(Code.INVALID_REQUEST, "selection.timetable_id is required for EXPLICIT_ARCHIVE.")
            tt = get_timetable(db, p, domain, sel_id)
            if tt.timetable_id == primary_id(db, p, domain):
                sel_type = SelectionType.PRIMARY  # selecting the primary is not an archive selection
    elif pref.selection_mode == SelectionMode.REMEMBER_LAST:
        last = pref.last_institutional_timetable_id if domain == Domain.INSTITUTIONAL else pref.last_personal_timetable_id
        if last is not None:
            try:
                tt = get_timetable(db, p, domain, last)
                sel_type = SelectionType.EXPLICIT_ARCHIVE
            except AppError:
                # D-07: same-domain fallback to primary, with a visible warning. Never cross-domain.
                warnings.append({
                    "code": "REMEMBERED_SELECTION_UNAVAILABLE",
                    "message": "Your previously selected timetable is no longer available; using the primary timetable of this view.",
                })
                tt = None

    if tt is None:
        pid = primary_id(db, p, domain)
        if pid is None:
            raise AppError(
                Code.NO_TIMETABLE_SELECTED,
                "No personal primary timetable is set. Upload a timetable or choose one from your archive."
                if domain == Domain.PERSONAL
                else "No official timetable has been activated yet.",
                {"domain": domain.value},
            )
        tt = get_timetable(db, p, domain, pid)
        sel_type = SelectionType.PRIMARY if sel_type_raw is None or sel_type == SelectionType.PRIMARY else sel_type

    if tt.processing_status in (ProcessingStatus.QUEUED, ProcessingStatus.PROCESSING):
        raise AppError(Code.TIMETABLE_NOT_READY, "This timetable is still being processed.", {"timetable_id": str(tt.timetable_id)})
    if tt.processing_status in (ProcessingStatus.FAILED, ProcessingStatus.UNUSABLE):
        raise AppError(
            Code.TIMETABLE_UNUSABLE,
            "The selected timetable could not be processed into usable schedule data, so it cannot answer queries.",
            {"timetable_id": str(tt.timetable_id), "processing_status": tt.processing_status},
        )
    if tt.processing_status == ProcessingStatus.NEEDS_REVIEW:
        warnings.append({"code": "TIMETABLE_NEEDS_REVIEW",
                         "message": "This timetable has extraction warnings; some entries may be unverified."})

    if remember:
        pref.last_active_domain = domain.value
        if sel_type == SelectionType.EXPLICIT_ARCHIVE and sel_type_raw is not None:
            if domain == Domain.INSTITUTIONAL:
                pref.last_institutional_timetable_id = tt.timetable_id
            else:
                pref.last_personal_timetable_id = tt.timetable_id
        elif sel_type_raw is not None and sel_type == SelectionType.PRIMARY:
            # User explicitly went back to the primary: forget the remembered archive for this domain only.
            if domain == Domain.INSTITUTIONAL:
                pref.last_institutional_timetable_id = None
            else:
                pref.last_personal_timetable_id = None
        db.flush()

    tz = p.timezone_id
    return SearchContext(p, domain, sel_type, tt, tz, Clock.now(tz), warnings)
