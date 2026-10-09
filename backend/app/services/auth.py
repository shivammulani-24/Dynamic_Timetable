"""Authentication: login, refresh-token rotation (with reuse detection), invitations, resets."""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import AccountStatus, TokenPurpose
from app.errors import AppError, Code
from app.models import AccountToken, RefreshToken, UserAccount, UserPreference
from app.security.passwords import hash_password, needs_rehash, password_problems, verify_password
from app.security.tokens import create_access_token, hash_token, new_opaque_token, utcnow
from app.services.audit import audit
from app.services.mailer import send_email


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _issue(db: Session, user: UserAccount, family_id: uuid.UUID | None = None, device: str | None = None) -> dict:
    s = get_settings()
    access, access_exp = create_access_token(user.user_id, user.token_version)
    raw = new_opaque_token()
    rt = RefreshToken(
        user_id=user.user_id,
        token_hash=hash_token(raw),
        family_id=family_id or uuid.uuid4(),
        expires_at=utcnow() + timedelta(days=s.refresh_token_days),
        device_label=(device or "")[:120] or None,
    )
    db.add(rt)
    db.flush()
    return {
        "access_token": access,
        "access_expires_at": access_exp.isoformat(),
        "refresh_token": raw,
        "token_type": "bearer",
        "_refresh_id": rt.token_id,
    }


def login(db: Session, email: str, password: str, device: str | None) -> tuple[UserAccount, dict]:
    user = db.scalar(select(UserAccount).where(UserAccount.college_email == normalize_email(email)))
    ok = verify_password(password, user.password_hash if user else None)
    if not user or not ok:
        audit(db, "AUTH_LOGIN_FAILED", user.user_id if user else None, "USER", user.user_id if user else None)
        db.commit()
        raise AppError(Code.UNAUTHENTICATED, "Incorrect email or password.", {"reason": "BAD_CREDENTIALS"})
    if user.account_status != AccountStatus.ACTIVE:
        raise AppError(
            Code.UNAUTHENTICATED, "This account is not active. Contact the Admin office.",
            {"reason": "ACCOUNT_" + user.account_status},
        )
    if needs_rehash(user.password_hash):  # type: ignore[arg-type]
        user.password_hash = hash_password(password)
    user.last_login_at = utcnow()
    tokens = _issue(db, user, device=device)
    audit(db, "AUTH_LOGIN", user.user_id, "USER", user.user_id)
    db.commit()
    return user, tokens


def refresh(db: Session, raw_token: str) -> tuple[UserAccount, dict]:
    rt = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)).with_for_update())
    if rt is None:
        raise AppError(Code.UNAUTHENTICATED, "Session expired. Please sign in again.", {"reason": "REFRESH_INVALID"})
    if rt.revoked_at is not None:
        # Reuse of a rotated token → likely theft. Revoke the entire family.
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == rt.family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
        audit(db, "AUTH_REFRESH_REUSE_DETECTED", rt.user_id, "USER", rt.user_id)
        db.commit()
        raise AppError(Code.UNAUTHENTICATED, "Session expired. Please sign in again.", {"reason": "REFRESH_REUSED"})
    if rt.expires_at <= utcnow():
        raise AppError(Code.UNAUTHENTICATED, "Session expired. Please sign in again.", {"reason": "REFRESH_EXPIRED"})
    user = db.get(UserAccount, rt.user_id)
    if user is None or user.account_status != AccountStatus.ACTIVE:
        raise AppError(Code.UNAUTHENTICATED, "This account is not active.", {"reason": "ACCOUNT_INACTIVE"})
    tokens = _issue(db, user, family_id=rt.family_id, device=rt.device_label)
    rt.revoked_at = utcnow()
    rt.replaced_by_id = tokens["_refresh_id"]
    db.commit()
    return user, tokens


def logout(db: Session, raw_token: str | None, user: UserAccount) -> None:
    if raw_token:
        db.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == hash_token(raw_token), RefreshToken.user_id == user.user_id)
            .values(revoked_at=utcnow())
        )
    audit(db, "AUTH_LOGOUT", user.user_id, "USER", user.user_id)
    db.commit()


def revoke_all_sessions(db: Session, user: UserAccount) -> None:
    user.token_version += 1
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def create_account_token(db: Session, user: UserAccount, purpose: TokenPurpose) -> str:
    s = get_settings()
    ttl = (
        timedelta(hours=s.invitation_token_hours)
        if purpose == TokenPurpose.INVITATION
        else timedelta(minutes=s.password_reset_minutes)
    )
    # Invalidate older unused tokens of the same purpose.
    db.execute(
        update(AccountToken)
        .where(AccountToken.user_id == user.user_id, AccountToken.purpose == purpose, AccountToken.used_at.is_(None))
        .values(used_at=utcnow())
    )
    raw = new_opaque_token()
    db.add(AccountToken(user_id=user.user_id, purpose=purpose, token_hash=hash_token(raw), expires_at=utcnow() + ttl))
    return raw


def _consume(db: Session, raw: str, purpose: TokenPurpose) -> UserAccount:
    tok = db.scalar(
        select(AccountToken)
        .where(AccountToken.token_hash == hash_token(raw), AccountToken.purpose == purpose)
        .with_for_update()
    )
    if tok is None or tok.used_at is not None or tok.expires_at <= utcnow():
        raise AppError(Code.INVALID_REQUEST, "This link is invalid or has expired.", {"reason": "TOKEN_INVALID"})
    tok.used_at = utcnow()
    user = db.get(UserAccount, tok.user_id)
    assert user is not None
    return user


def _check_password(password: str) -> None:
    problems = password_problems(password)
    if problems:
        raise AppError(Code.INVALID_REQUEST, " ".join(problems), {"field": "password"})


def activate(db: Session, raw: str, password: str, timezone_id: str | None) -> tuple[UserAccount, dict]:
    _check_password(password)
    user = _consume(db, raw, TokenPurpose.INVITATION)
    if user.account_status not in (AccountStatus.INVITED, AccountStatus.ACTIVE):
        raise AppError(Code.INVALID_REQUEST, "This account cannot be activated. Contact the Admin office.")
    user.password_hash = hash_password(password)
    user.account_status = AccountStatus.ACTIVE
    if timezone_id:
        from app.services.preferences import validate_timezone

        user.timezone_id = validate_timezone(timezone_id)
    if db.get(UserPreference, user.user_id) is None:
        db.add(UserPreference(user_id=user.user_id))
    audit(db, "AUTH_ACCOUNT_ACTIVATED", user.user_id, "USER", user.user_id)
    tokens = _issue(db, user)
    db.commit()
    return user, tokens


def request_password_reset(db: Session, email: str) -> str | None:
    user = db.scalar(select(UserAccount).where(UserAccount.college_email == normalize_email(email)))
    if user is None or user.account_status != AccountStatus.ACTIVE:
        return None  # do not reveal whether the account exists
    raw = create_account_token(db, user, TokenPurpose.PASSWORD_RESET)
    audit(db, "AUTH_PASSWORD_RESET_REQUESTED", user.user_id, "USER", user.user_id)
    db.commit()
    send_email(user.college_email, "Reset your timetable password",
               f"Use this code in the app to reset your password: {raw}\nIt expires soon.")
    return raw


def confirm_password_reset(db: Session, raw: str, password: str) -> None:
    _check_password(password)
    user = _consume(db, raw, TokenPurpose.PASSWORD_RESET)
    user.password_hash = hash_password(password)
    revoke_all_sessions(db, user)
    audit(db, "AUTH_PASSWORD_RESET", user.user_id, "USER", user.user_id)
    db.commit()


def change_password(db: Session, user: UserAccount, current: str, new: str) -> None:
    if not verify_password(current, user.password_hash):
        raise AppError(Code.INVALID_REQUEST, "Current password is incorrect.", {"field": "current_password"})
    _check_password(new)
    user.password_hash = hash_password(new)
    revoke_all_sessions(db, user)
    audit(db, "AUTH_PASSWORD_CHANGED", user.user_id, "USER", user.user_id)
    db.commit()
