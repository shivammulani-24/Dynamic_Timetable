"""Archive access, listing and primary selection — enforcing domain + ownership on every call."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.enums import Domain, ProcessingStatus, SEARCHABLE_STATUSES
from app.errors import AppError, Code
from app.models import InstitutionalTimetableSettings, UserPreference
from app.security.principal import Principal
from app.services.audit import audit
from app.services.domains import models_for
from app.services.notifications import notify, users_wanting_official_updates
from app.services.preferences import get_or_create_preferences


def _not_found() -> AppError:
    return AppError(Code.TIMETABLE_NOT_FOUND, "Timetable not found in the selected view.")


def parse_uuid(value: Any) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise _not_found()


def get_timetable(db: Session, p: Principal, domain: Domain, timetable_id: Any, *, for_update: bool = False):
    """Return a timetable the principal may see in `domain`, else TIMETABLE_NOT_FOUND.

    The lookup only touches the domain's own table, so an ID from the other domain is simply
    "not found". A personal timetable owned by someone else is also "not found" (no existence
    leak) and the attempt is audited.
    """
    tid = parse_uuid(timetable_id)
    m = models_for(domain)
    q = select(m.meta).where(m.meta.timetable_id == tid, m.meta.deleted_at.is_(None))
    if for_update:
        q = q.with_for_update()
    tt = db.scalar(q)
    if tt is None:
        raise _not_found()
    if domain == Domain.PERSONAL and tt.owner_user_id != p.user_id:
        from app.db import session_factory
        from app.services.audit import audit_now

        audit_now(session_factory(), "ACCESS_DENIED", p.user_id, target_type="PERSONAL_TIMETABLE", target_id=tid)
        raise _not_found()
    if domain == Domain.INSTITUTIONAL and not p.is_admin and tt.processing_status not in SEARCHABLE_STATUSES:
        raise _not_found()  # ordinary users only see published-usable archives
    return tt


def institutional_default_id(db: Session) -> uuid.UUID | None:
    return db.scalar(select(InstitutionalTimetableSettings.default_timetable_id).where(InstitutionalTimetableSettings.settings_id == 1))


def settings_version(db: Session) -> int:
    return db.scalar(select(InstitutionalTimetableSettings.version).where(InstitutionalTimetableSettings.settings_id == 1)) or 0


def primary_id(db: Session, p: Principal, domain: Domain) -> uuid.UUID | None:
    if domain == Domain.INSTITUTIONAL:
        return institutional_default_id(db)
    pref = db.get(UserPreference, p.user_id)
    return pref.personal_primary_timetable_id if pref else None


def list_timetables(db: Session, p: Principal, domain: Domain, limit: int, offset: int) -> tuple[list, int]:
    m = models_for(domain)
    q = select(m.meta).where(m.meta.deleted_at.is_(None))
    if domain == Domain.PERSONAL:
        q = q.where(m.meta.owner_user_id == p.user_id)
    elif not p.is_admin:
        q = q.where(m.meta.processing_status.in_(list(SEARCHABLE_STATUSES)))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(m.meta.uploaded_at.desc()).limit(limit).offset(offset)).all()
    return list(rows), total


def serialize_timetable(tt, domain: Domain, primary: uuid.UUID | None, *, include_summary: bool = True) -> dict:
    d: dict[str, Any] = {
        "timetable_id": str(tt.timetable_id),
        "domain": domain.value,
        "title": tt.title,
        "original_filename": tt.original_filename,
        "file_format": tt.file_format,
        "uploaded_at": tt.uploaded_at.isoformat(),
        "processing_status": tt.processing_status,
        "is_primary": primary is not None and tt.timetable_id == primary,
        "page_count": tt.page_count,
        "parser_version": tt.parser_version,
        "effective_from": tt.effective_from.isoformat() if tt.effective_from else None,
        "effective_from_raw": tt.effective_from_raw,
        "term_label": tt.term_label,
        "data_version": tt.data_version,
        "primary_eligible": tt.processing_status in SEARCHABLE_STATUSES,
    }
    if domain == Domain.INSTITUTIONAL:
        d["academic_year"] = tt.academic_year.label if tt.academic_year else None
        d["academic_year_id"] = tt.academic_year_id
        d["department"] = tt.department.name if tt.department else None
    if include_summary:
        d["validation_summary"] = tt.validation_summary or {}
    return d


def set_primary(db: Session, p: Principal, domain: Domain, timetable_id: Any) -> dict:
    """QT22 SET_DOMAIN_PRIMARY. Changes exactly one domain's primary, transactionally."""
    if domain == Domain.INSTITUTIONAL:
        if not p.is_admin:
            raise AppError(Code.ACCESS_DENIED, "Only an Admin can change the official institutional timetable.")
        settings = db.scalar(
            select(InstitutionalTimetableSettings).where(InstitutionalTimetableSettings.settings_id == 1).with_for_update()
        )
        tt = get_timetable(db, p, domain, timetable_id, for_update=True)
        _check_eligible(tt)
        if settings.default_timetable_id == tt.timetable_id:
            raise AppError(Code.PRIMARY_SELECTION_CONFLICT, "This timetable is already the official default.")
        previous = settings.default_timetable_id
        settings.default_timetable_id = tt.timetable_id
        settings.updated_by_user_id = p.user_id
        settings.version += 1
        audit(db, "INSTITUTIONAL_DEFAULT_CHANGED", p.user_id, "INSTITUTIONAL_TIMETABLE", tt.timetable_id,
              previous=str(previous) if previous else None, status=tt.processing_status)
        recipients = users_wanting_official_updates(db)
        notify(db, recipients, "OFFICIAL_TIMETABLE_ACTIVATED", "New official timetable",
               f"“{tt.title}” is now the official timetable.", {"timetable_id": str(tt.timetable_id)})
        db.commit()
        from app.services.notifications import send_push

        send_push(db, recipients, "New official timetable", f"“{tt.title}” is now the official timetable.")
        return {"domain": domain.value, "primary_timetable_id": str(tt.timetable_id), "settings_version": settings.version}

    pref = get_or_create_preferences(db, p.user_id, lock=True)
    tt = get_timetable(db, p, domain, timetable_id, for_update=True)
    _check_eligible(tt)
    if pref.personal_primary_timetable_id == tt.timetable_id:
        raise AppError(Code.PRIMARY_SELECTION_CONFLICT, "This timetable is already your personal primary.")
    pref.personal_primary_timetable_id = tt.timetable_id
    audit(db, "PERSONAL_PRIMARY_CHANGED", p.user_id, "PERSONAL_TIMETABLE", tt.timetable_id)
    db.commit()
    return {"domain": domain.value, "primary_timetable_id": str(tt.timetable_id)}


def _check_eligible(tt) -> None:
    if tt.processing_status not in SEARCHABLE_STATUSES:
        raise AppError(
            Code.PRIMARY_SELECTION_CONFLICT,
            f"A timetable with status {tt.processing_status} cannot be made primary.",
            {"processing_status": tt.processing_status},
        )


def soft_delete(db: Session, p: Principal, domain: Domain, timetable_id: Any) -> None:
    """Archive retention: soft delete only; a current primary/default cannot be deleted."""
    if domain == Domain.INSTITUTIONAL and not p.is_admin:
        raise AppError(Code.ACCESS_DENIED, "Only an Admin can remove institutional archives.")
    tt = get_timetable(db, p, domain, timetable_id, for_update=True)
    if primary_id(db, p, domain) == tt.timetable_id:
        raise AppError(Code.PRIMARY_SELECTION_CONFLICT, "Select a different primary timetable before removing this one.")
    if tt.processing_status in (ProcessingStatus.QUEUED, ProcessingStatus.PROCESSING):
        raise AppError(Code.CONFLICT, "Wait for processing to finish before removing this upload.")
    from app.security.tokens import utcnow

    tt.deleted_at = utcnow()
    if domain == Domain.PERSONAL:
        pref = get_or_create_preferences(db, p.user_id)
        if pref.last_personal_timetable_id == tt.timetable_id:
            pref.last_personal_timetable_id = None
    else:
        db.execute(
            UserPreference.__table__.update()
            .where(UserPreference.last_institutional_timetable_id == tt.timetable_id)
            .values(last_institutional_timetable_id=None)
        )
    audit(db, f"{domain.value}_TIMETABLE_REMOVED", p.user_id, f"{domain.value}_TIMETABLE", tt.timetable_id)
    db.commit()

