from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.enums import Domain, SelectionMode
from app.errors import AppError, Code
from app.models import Department, InstitutionConfig, PushDevice, UserAccount
from app.security.deps import get_current_user, get_principal
from app.security.principal import Principal
from app.services.academics import current_placement, history
from app.services.preferences import get_or_create_preferences, validate_timezone
from app.services.timetables import get_timetable

router = APIRouter(tags=["me"])


@router.get("/me")
def me(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    out = {
        "user_id": str(p.user_id),
        "email": p.email,
        "display_name": p.display_name,
        "timezone": p.timezone_id,
        "roles": sorted(r.value for r in p.roles),
        "student": None,
        "staff": None,
    }
    if p.student_id:
        cur = current_placement(db, p.student_id)
        from app.models import Student

        st = db.get(Student, p.student_id)
        out["student"] = {
            "student_id": str(p.student_id),
            "uid": st.uid if st else None,
            "status": st.student_status if st else None,
            "placement": history(db, p.student_id)[0] if cur else None,
            "batch_codes": list(p.student_batch_codes),
            "setup_required": not p.student_batch_ids,
        }
    if p.staff_id:
        dept = db.get(Department, p.staff_department_id) if p.staff_department_id else None
        out["staff"] = {
            "staff_id": str(p.staff_id),
            "department_id": p.staff_department_id,
            "department": dept.name if dept else None,
        }
    cfg = db.get(InstitutionConfig, 1)
    out["institution"] = {
        "name": cfg.institution_name if cfg else None,
        "week_start_day": cfg.week_start_day if cfg else None,
        "lunch_boundary": cfg.lunch_boundary.strftime("%H:%M") if cfg and cfg.lunch_boundary else None,
    }
    return out


def _pref_out(pref, user: UserAccount) -> dict:
    return {
        "timezone": user.timezone_id,
        "selection_mode": pref.selection_mode,
        "last_active_domain": pref.last_active_domain,
        "personal_primary_timetable_id": str(pref.personal_primary_timetable_id) if pref.personal_primary_timetable_id else None,
        "last_personal_timetable_id": str(pref.last_personal_timetable_id) if pref.last_personal_timetable_id else None,
        "last_institutional_timetable_id": str(pref.last_institutional_timetable_id) if pref.last_institutional_timetable_id else None,
        "notify_official_timetable": pref.notify_official_timetable,
        "notify_processing": pref.notify_processing,
        "search_history_enabled": pref.search_history_enabled,
        "theme": pref.theme,
        "time_format_24h": pref.time_format_24h,
    }


@router.get("/me/preferences")
def get_preferences(user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db)):
    pref = get_or_create_preferences(db, user.user_id)
    db.commit()
    return _pref_out(pref, user)


class PreferencesPatch(BaseModel):
    timezone: str | None = Field(None, max_length=64)
    selection_mode: SelectionMode | None = None
    last_active_domain: Domain | None = None
    notify_official_timetable: bool | None = None
    notify_processing: bool | None = None
    search_history_enabled: bool | None = None
    theme: Literal["system", "light", "dark"] | None = None
    time_format_24h: bool | None = None


@router.patch("/me/preferences")
def patch_preferences(body: PreferencesPatch, user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db)):
    """Only the caller's own preferences. Primary selection is NOT changed here (see make-primary)."""
    pref = get_or_create_preferences(db, user.user_id, lock=True)
    data = body.model_dump(exclude_unset=True)
    if "timezone" in data and data["timezone"] is not None:
        user.timezone_id = validate_timezone(data.pop("timezone"))
    data.pop("timezone", None)
    for k, v in data.items():
        if v is None:
            continue
        setattr(pref, k, v.value if hasattr(v, "value") else v)
    db.commit()
    return _pref_out(pref, user)


class SelectionIn(BaseModel):
    domain: Domain
    timetable_id: str | None = Field(None, description="null clears the remembered archive (use primary)")


@router.put("/me/selection")
def set_selection(body: SelectionIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Remember an archive selection in one domain. Does not change any primary."""
    pref = get_or_create_preferences(db, p.user_id, lock=True)
    tid = None
    if body.timetable_id:
        tt = get_timetable(db, p, body.domain, body.timetable_id)
        tid = tt.timetable_id
    if body.domain == Domain.INSTITUTIONAL:
        pref.last_institutional_timetable_id = tid
    else:
        pref.last_personal_timetable_id = tid
    pref.last_active_domain = body.domain.value
    db.commit()
    return {"status": "OK", "domain": body.domain.value, "timetable_id": str(tid) if tid else None}


class PushIn(BaseModel):
    expo_push_token: str = Field(min_length=10, max_length=200)
    platform: Literal["ios", "android", "web"]


@router.post("/me/push-devices")
def register_push(body: PushIn, user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db)):
    if not body.expo_push_token.startswith(("ExponentPushToken[", "ExpoPushToken[")):
        raise AppError(Code.INVALID_REQUEST, "Not an Expo push token.")
    dev = db.scalar(select(PushDevice).where(PushDevice.expo_push_token == body.expo_push_token))
    if dev is None:
        db.add(PushDevice(user_id=user.user_id, expo_push_token=body.expo_push_token, platform=body.platform))
    else:
        dev.user_id = user.user_id  # token moved to another account on the same device
        dev.platform = body.platform
    db.commit()
    return {"status": "OK"}


@router.delete("/me/push-devices")
def unregister_push(body: PushIn, user: UserAccount = Depends(get_current_user), db: Session = Depends(get_db)):
    dev = db.scalar(select(PushDevice).where(PushDevice.expo_push_token == body.expo_push_token, PushDevice.user_id == user.user_id))
    if dev:
        db.delete(dev)
        db.commit()
    return {"status": "OK"}
