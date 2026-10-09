from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.common import Page
from app.config import get_settings
from app.db import get_db
from app.enums import Domain, ProcessingStatus, RoleCode
from app.errors import AppError, Code
from app.models import (
    AcademicYear,
    InstitutionalTimetable,
    PersonalTimetable,
    ProcessingJob,
    SavedSearch,
    SearchHistory,
    UserAccount,
)
from app.query import engine
from app.query.nlp import EXAMPLES
from app.query.registry import INTENTS, registry_document
from app.security import ratelimit
from app.security.deps import get_principal
from app.security.policy import can_view_conflicts, institutional_scope
from app.security.principal import Principal
from app.services import conflicts as conflict_svc
from app.services.context import parse_domain
from app.services.timetables import institutional_default_id

router = APIRouter(tags=["search"])


class SelectionIn(BaseModel):
    type: str = Field(pattern="^(PRIMARY|EXPLICIT_ARCHIVE)$")
    timetable_id: str | None = Field(None, max_length=40)


class SearchIn(BaseModel):
    query: str | None = Field(None, max_length=300)
    intent: str | None = Field(None, max_length=40)
    parameters: dict[str, Any] = Field(default_factory=dict)
    domain: str | None = Field(None, max_length=20)
    selection: SelectionIn | None = None
    client_request_id: str | None = Field(None, max_length=64)
    limit: int = Field(100, ge=1, le=200)
    cursor: str | None = Field(None, max_length=10)


def _run(db: Session, p: Principal, body: SearchIn) -> tuple[int, dict]:
    try:
        cursor = int(body.cursor) if body.cursor else 0
    except ValueError:
        raise AppError(Code.INVALID_REQUEST, "Invalid cursor.")
    req = engine.Request(query=body.query, intent=body.intent, parameters=dict(body.parameters), domain=body.domain,
                         selection=body.selection.model_dump() if body.selection else None, limit=body.limit, cursor=cursor)
    return engine.search(db, p, req)


@router.post("/search")
def search(body: SearchIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Natural-language or structured search. Clients must branch on `status`, never on `message`."""
    ratelimit.check("search", str(p.user_id), get_settings().rate_limit_search_per_minute)
    code, env = _run(db, p, body)
    return JSONResponse(env, status_code=code)


@router.get("/search/registry")
def registry(_: Principal = Depends(get_principal)):
    return {**registry_document(), "examples": EXAMPLES}


@router.get("/search/history")
def history(page: Page = Depends(), p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    q = select(SearchHistory).where(SearchHistory.user_id == p.user_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(SearchHistory.created_at.desc()).limit(page.limit).offset(page.offset)).all()
    return page.envelope([{"search_id": str(h.search_id), "query": h.query_text, "intent": h.intent, "status": h.status,
                           "domain": h.domain, "created_at": h.created_at.isoformat()} for h in rows], total)


@router.delete("/search/history")
def clear_history(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    db.execute(delete(SearchHistory).where(SearchHistory.user_id == p.user_id))
    db.commit()
    return {"status": "OK"}


class SavedIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    query: str | None = Field(None, max_length=300)
    intent: str | None = Field(None, max_length=40)
    parameters: dict[str, Any] = Field(default_factory=dict)


@router.get("/saved-searches")
def saved(p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    rows = db.scalars(select(SavedSearch).where(SavedSearch.user_id == p.user_id).order_by(SavedSearch.created_at.desc())).all()
    return {"items": [{"saved_search_id": str(s.saved_search_id), "name": s.name, "query": s.query_text, "intent": s.intent,
                       "parameters": s.parameters, "created_at": s.created_at.isoformat()} for s in rows]}


@router.post("/saved-searches", status_code=201)
def save(body: SavedIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Saves only the question (text and/or intent + typed parameters) — never a domain, timetable or user."""
    if not body.query and not body.intent:
        raise AppError(Code.INVALID_REQUEST, "Provide a query or an intent to save.")
    if body.intent and body.intent not in INTENTS:
        raise AppError(Code.INVALID_REQUEST, "Unknown intent.")
    params = {k: v for k, v in body.parameters.items() if k not in ("timetable_id", "confirm")}
    try:
        engine._validate_params(params)
    except engine.Halt as h:
        raise AppError(Code.INVALID_REQUEST, h.message)
    s = SavedSearch(user_id=p.user_id, name=body.name.strip(), query_text=body.query, intent=body.intent, parameters=params)
    db.add(s)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(Code.CONFLICT, "You already have a saved search with that name.")
    return {"saved_search_id": str(s.saved_search_id)}


@router.delete("/saved-searches/{saved_id}")
def unsave(saved_id: uuid.UUID, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    db.execute(delete(SavedSearch).where(SavedSearch.saved_search_id == saved_id, SavedSearch.user_id == p.user_id))
    db.commit()
    return {"status": "OK"}


@router.post("/saved-searches/{saved_id}/run")
def run_saved(saved_id: uuid.UUID, domain: str | None = Query(None), p: Principal = Depends(get_principal),
              db: Session = Depends(get_db)):
    s = db.scalar(select(SavedSearch).where(SavedSearch.saved_search_id == saved_id, SavedSearch.user_id == p.user_id))
    if s is None:
        raise AppError(Code.NOT_FOUND, "Saved search not found.")
    ratelimit.check("search", str(p.user_id), get_settings().rate_limit_search_per_minute)
    code, env = _run(db, p, SearchIn(query=s.query_text, intent=s.intent, parameters=s.parameters, domain=domain))
    return JSONResponse(env, status_code=code)


# --------------------------------------------------------------------------- dashboard


def _card(db: Session, p: Principal, intent: str, domain: str, parameters: dict | None = None) -> dict:
    code, env = engine.search(db, p, engine.Request(intent=intent, parameters=parameters or {}, domain=domain))
    return {k: env[k] for k in ("status", "intent", "message", "results", "warnings", "clarification", "result_type", "meta")}


@router.get("/dashboard")
def dashboard(domain: str = Query(...), p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Role-aware home. Every schedule card uses the same engine handlers as the equivalent typed question."""
    d = parse_domain(domain)
    out: dict[str, Any] = {"domain": d.value, "roles": sorted(r.value for r in p.roles), "cards": {}}
    for key, intent in (("current", "CURRENT_CLASS"), ("next", "NEXT_CLASS"), ("remaining", "REMAINING_CLASSES_TODAY"),
                        ("today", "SHOW_MY_TIMETABLE")):
        out["cards"][key] = _card(db, p, intent, d.value)
    first = out["cards"]["today"]
    out["context_status"] = first["status"]
    if d == Domain.INSTITUTIONAL:
        scope = institutional_scope(p)
        out["setup_required"] = scope.reason_if_empty if scope.is_empty else None
        if p.has(RoleCode.PROFESSOR) and p.staff_id:
            from app.models import InstitutionConfig

            cfg = db.get(InstitutionConfig, 1)
            if cfg and cfg.working_hours_start and cfg.working_hours_end:
                out["cards"]["free_today"] = _card(db, p, "PROFESSOR_FREE_TIME", d.value,
                                                   {"date": engine.Clock.now(p.timezone_id).date().isoformat()})
        default_id = institutional_default_id(db)
        if can_view_conflicts(p) and default_id:
            depts = None if scope.college else set(scope.department_ids)
            c = conflict_svc.detect(db, default_id, depts)
            out["conflicts"] = {"total": c["total"], "counts": c["counts"]}
    if p.is_admin:
        out["admin"] = {
            "users_active": db.scalar(select(func.count()).select_from(UserAccount).where(UserAccount.account_status == "ACTIVE")),
            "users_invited": db.scalar(select(func.count()).select_from(UserAccount).where(UserAccount.account_status == "INVITED")),
            "jobs_pending": db.scalar(select(func.count()).select_from(ProcessingJob).where(
                ProcessingJob.status.in_(["QUEUED", "RUNNING"]), ProcessingJob.domain == "INSTITUTIONAL")),
            "jobs_failed": db.scalar(select(func.count()).select_from(ProcessingJob).where(
                ProcessingJob.status == "FAILED", ProcessingJob.domain == "INSTITUTIONAL")),
            "institutional_needs_review": db.scalar(select(func.count()).select_from(InstitutionalTimetable).where(
                InstitutionalTimetable.processing_status == ProcessingStatus.NEEDS_REVIEW, InstitutionalTimetable.deleted_at.is_(None))),
            "institutional_archives": db.scalar(select(func.count()).select_from(InstitutionalTimetable).where(
                InstitutionalTimetable.deleted_at.is_(None))),
            "active_academic_year": db.scalar(select(AcademicYear.label).where(AcademicYear.status == "ACTIVE")),
            "official_default_id": str(default_id) if default_id else None,
        }
    if d == Domain.PERSONAL:
        out["personal_archives"] = db.scalar(select(func.count()).select_from(PersonalTimetable).where(
            PersonalTimetable.owner_user_id == p.user_id, PersonalTimetable.deleted_at.is_(None)))
    return out
