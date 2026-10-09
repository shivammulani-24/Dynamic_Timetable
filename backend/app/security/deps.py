"""FastAPI dependencies: authentication and role guards."""
from __future__ import annotations

import uuid
from collections.abc import Callable

import jwt
from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.enums import AccountStatus, RoleCode
from app.errors import AppError, Code
from app.models import UserAccount
from app.security.principal import Principal, load_principal
from app.security.tokens import decode_access_token


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise AppError(Code.UNAUTHENTICATED, "Sign in to continue.")
    return token


def get_current_user(request: Request, db: Session = Depends(get_db)) -> UserAccount:
    token = _bearer(request)
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise AppError(Code.UNAUTHENTICATED, "Your session has expired.", {"reason": "TOKEN_EXPIRED"})
    except (jwt.InvalidTokenError, ValueError, KeyError):
        raise AppError(Code.UNAUTHENTICATED, "Invalid session.", {"reason": "TOKEN_INVALID"})
    user = db.get(UserAccount, user_id)
    if user is None or user.token_version != payload.get("ver"):
        raise AppError(Code.UNAUTHENTICATED, "Your session is no longer valid.", {"reason": "TOKEN_REVOKED"})
    if user.account_status != AccountStatus.ACTIVE:
        raise AppError(Code.UNAUTHENTICATED, "This account is not active.", {"reason": "ACCOUNT_" + user.account_status})
    request.state.user_id = user.user_id
    return user


def get_principal(user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db)) -> Principal:
    return load_principal(db, user)


def require_roles(*roles: RoleCode) -> Callable[..., Principal]:
    def dep(p: Principal = Depends(get_principal)) -> Principal:
        if not p.has(*roles):
            raise AppError(Code.ACCESS_DENIED, "You do not have permission to perform this action.")
        return p

    return dep


require_admin = require_roles(RoleCode.ADMIN)
