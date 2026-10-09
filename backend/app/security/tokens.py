"""Access tokens (short-lived JWT) and opaque refresh/account tokens (hashed at rest)."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.config import get_settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(user_id: uuid.UUID, token_version: int) -> tuple[str, datetime]:
    s = get_settings()
    exp = utcnow() + timedelta(minutes=s.access_token_minutes)
    payload = {
        "sub": str(user_id),
        "ver": token_version,
        "typ": "access",
        "iat": int(utcnow().timestamp()),
        "exp": exp,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm), exp


def decode_access_token(token: str) -> dict:
    s = get_settings()
    payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm], options={"require": ["exp", "sub"]})
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
