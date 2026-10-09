from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import UserAccount
from app.security import ratelimit
from app.security.deps import get_current_user
from app.services import auth as svc

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)
    device_label: str | None = Field(None, max_length=120)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=200)


class LogoutIn(BaseModel):
    refresh_token: str | None = Field(None, max_length=200)


class ActivateIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=128)
    timezone: str | None = Field(None, max_length=64)


class ResetRequestIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetConfirmIn(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _token_out(tokens: dict) -> dict:
    return {k: v for k, v in tokens.items() if not k.startswith("_")}


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    ratelimit.check("login-ip", _client_key(request), s.rate_limit_login_per_minute * 3)
    ratelimit.check("login-email", body.email.strip().lower(), s.rate_limit_login_per_minute)
    _, tokens = svc.login(db, body.email, body.password, body.device_label)
    return _token_out(tokens)


@router.post("/refresh")
def refresh(body: RefreshIn, request: Request, db: Session = Depends(get_db)):
    ratelimit.check("refresh", _client_key(request), 60)
    _, tokens = svc.refresh(db, body.refresh_token)
    return _token_out(tokens)


@router.post("/logout")
def logout(body: LogoutIn, user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db)):
    svc.logout(db, body.refresh_token, user)
    return {"status": "OK"}


@router.post("/logout-all")
def logout_all(user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db)):
    svc.revoke_all_sessions(db, user)
    db.commit()
    return {"status": "OK"}


@router.post("/activate")
def activate(body: ActivateIn, request: Request, db: Session = Depends(get_db)):
    ratelimit.check("activate", _client_key(request), 10)
    _, tokens = svc.activate(db, body.token.strip(), body.password, body.timezone)
    return _token_out(tokens)


@router.post("/password-reset/request", status_code=202)
def reset_request(body: ResetRequestIn, request: Request, db: Session = Depends(get_db)):
    ratelimit.check("reset", _client_key(request), 5)
    raw = svc.request_password_reset(db, body.email)
    out: dict = {"status": "OK", "message": "If an active account exists for that email, a reset code has been sent."}
    if raw and get_settings().dev_tokens_exposed:
        out["dev_reset_token"] = raw
    return out


@router.post("/password-reset/confirm")
def reset_confirm(body: ResetConfirmIn, request: Request, db: Session = Depends(get_db)):
    ratelimit.check("reset-confirm", _client_key(request), 10)
    svc.confirm_password_reset(db, body.token.strip(), body.password)
    return {"status": "OK"}


@router.post("/change-password")
def change_password(body: ChangePasswordIn, user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db)):
    svc.change_password(db, user, body.current_password, body.new_password)
    return {"status": "OK", "message": "Password changed. Please sign in again on your other devices."}
