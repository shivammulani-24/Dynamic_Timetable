"""In-app notifications (persisted) + optional Expo push delivery.

Push is delivered through Expo's push service only when EXPO_PUSH_ENABLED=true; local
notifications cannot report server events while the app is closed, so we do not pretend they do.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import AccountStatus
from app.models import Notification, PushDevice, UserAccount, UserPreference

log = logging.getLogger(__name__)


def notify(db: Session, user_ids: Iterable[uuid.UUID], kind: str, title: str, body: str, data: dict | None = None) -> int:
    ids = list(user_ids)
    for uid in ids:
        db.add(Notification(user_id=uid, kind=kind, title=title, body=body, data=data or {}))
    return len(ids)


def users_wanting_official_updates(db: Session) -> list[uuid.UUID]:
    rows = db.execute(
        select(UserAccount.user_id)
        .outerjoin(UserPreference, UserPreference.user_id == UserAccount.user_id)
        .where(UserAccount.account_status == AccountStatus.ACTIVE)
        .where((UserPreference.notify_official_timetable.is_(None)) | (UserPreference.notify_official_timetable.is_(True)))
    )
    return [r[0] for r in rows]


def wants_processing_updates(db: Session, user_id: uuid.UUID) -> bool:
    pref = db.get(UserPreference, user_id)
    return pref is None or pref.notify_processing


def send_push(db: Session, user_ids: Iterable[uuid.UUID], title: str, body: str, data: dict | None = None) -> None:
    """Best-effort push after the DB commit. Failures are logged, never raised."""
    s = get_settings()
    if not s.expo_push_enabled:
        return
    tokens = db.scalars(select(PushDevice.expo_push_token).where(PushDevice.user_id.in_(list(user_ids)))).all()
    messages = [{"to": t, "title": title, "body": body, "data": data or {}} for t in tokens]
    for i in range(0, len(messages), 100):
        try:
            httpx.post(s.expo_push_url, json=messages[i : i + 100], timeout=10).raise_for_status()
        except Exception:  # noqa: BLE001
            log.exception("Expo push delivery failed")
