from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.common import Page
from app.db import get_db
from app.models import Notification, UserAccount
from app.security.deps import get_current_user
from app.security.tokens import utcnow

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(page: Page = Depends(), user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db)):
    q = select(Notification).where(Notification.user_id == user.user_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    unread = db.scalar(select(func.count()).where(Notification.user_id == user.user_id, Notification.read_at.is_(None))) or 0
    rows = db.scalars(q.order_by(Notification.created_at.desc()).limit(page.limit).offset(page.offset)).all()
    env = page.envelope([{"notification_id": str(n.notification_id), "kind": n.kind, "title": n.title, "body": n.body,
                          "data": n.data, "created_at": n.created_at.isoformat(),
                          "read_at": n.read_at.isoformat() if n.read_at else None} for n in rows], total)
    env["unread"] = unread
    return env


@router.get("/unread-count")
def unread_count(user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.scalar(select(func.count()).where(Notification.user_id == user.user_id, Notification.read_at.is_(None))) or 0
    return {"unread": n}


@router.post("/{notification_id}/read")
def mark_read(notification_id: uuid.UUID, user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.notification_id == notification_id, Notification.user_id == user.user_id,
                                          Notification.read_at.is_(None)).values(read_at=utcnow()))
    db.commit()
    return {"status": "OK"}


@router.post("/read-all")
def mark_all(user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.user_id == user.user_id, Notification.read_at.is_(None)).values(read_at=utcnow()))
    db.commit()
    return {"status": "OK"}
