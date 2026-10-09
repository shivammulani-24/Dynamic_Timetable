"""Audit logging for sensitive operations. Never store secrets or free-text personal content."""
from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
log = logging.getLogger("audit")


def audit(
    db: Session,
    event_type: str,
    actor_user_id: uuid.UUID | None,
    target_type: str | None = None,
    target_id: Any = None,
    **details: Any,
) -> None:
    """Adds an audit row to the current transaction (committed with the business change)."""
    db.add(
        AuditEvent(
            actor_user_id=actor_user_id,
            event_type=event_type,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            request_id=request_id_var.get(),
            details={k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in details.items()},
        )
    )
    log.info("audit %s actor=%s target=%s:%s", event_type, actor_user_id, target_type, target_id)


def audit_now(db_factory, event_type: str, actor_user_id: uuid.UUID | None, **kw: Any) -> None:
    """Writes an audit event in its own transaction (used for ACCESS_DENIED etc. on failing requests)."""
    with db_factory() as db:
        audit(db, event_type, actor_user_id, **kw)
        db.commit()
