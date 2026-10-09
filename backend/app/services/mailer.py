"""Optional SMTP email. If SMTP is not configured, nothing is sent (tokens are surfaced only in dev)."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

log = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> bool:
    s = get_settings()
    if not s.smtp_host or not s.smtp_from:
        log.info("SMTP not configured; email '%s' not sent", subject)
        return False
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if s.smtp_user:
                smtp.login(s.smtp_user, s.smtp_password or "")
            smtp.send_message(msg)
        return True
    except Exception:  # noqa: BLE001 - email failure must not break the request
        log.exception("Failed to send email '%s'", subject)
        return False
