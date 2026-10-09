from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from sqlalchemy.orm import Session

from app.errors import AppError, Code
from app.models import UserPreference

_ZONES: set[str] | None = None


def validate_timezone(tz: str) -> str:
    global _ZONES
    if _ZONES is None:
        _ZONES = available_timezones()
    if tz not in _ZONES:
        raise AppError(Code.INVALID_REQUEST, "Unknown timezone. Use an IANA name such as Asia/Kolkata.", {"field": "timezone"})
    try:
        ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        raise AppError(Code.INVALID_REQUEST, "Unknown timezone.", {"field": "timezone"})
    return tz


def get_or_create_preferences(db: Session, user_id, lock: bool = False) -> UserPreference:
    q = db.query(UserPreference).filter(UserPreference.user_id == user_id)
    if lock:
        q = q.with_for_update()
    pref = q.one_or_none()
    if pref is None:
        pref = UserPreference(user_id=user_id)
        db.add(pref)
        db.flush()
        if lock:
            pref = db.query(UserPreference).filter(UserPreference.user_id == user_id).with_for_update().one()
    return pref
