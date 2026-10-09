"""Timetable archives, uploads, entries, review, primary selection and conflicts.

Every endpoint takes an explicit `domain`; IDs are only ever looked up in that domain's table.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import Page
from app.config import get_settings
from app.db import get_db
from app.enums import Domain, EntryKind, JobStatus, ProcessingStatus, VerificationStatus
from app.errors import AppError, Code
from app.models import ProcessingJob, ValidationFinding
from app.security import ratelimit
from app.security.deps import get_principal, require_admin
from app.security.policy import can_view_conflicts, institutional_scope
from app.security.principal import Principal
from app.services import conflicts as conflict_svc
from app.services import storage
from app.services.context import parse_domain, resolve_context
from app.services.domains import models_for
from app.services.entries import correct_entry, corrections_for, scope_condition, serialize_entry
from app.services.preferences import get_or_create_preferences
from app.services.timetables import (
    get_timetable,
    list_timetables,
    primary_id,
    serialize_timetable,
    set_primary,
    settings_version,
    soft_delete,
)
from app.services.uploads import create_upload, retry_processing

router = APIRouter(tags=["timetables"])
DomainQ = Query(..., description="INSTITUTIONAL or PERSONAL")


def _dom(v: str) -> Domain:
    return parse_domain(v)


@router.get("/timetable-context")
def timetable_context(domain: str = DomainQ, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Primary + current selection for one domain. Never returns the other domain's data."""
    d = _dom(domain)
    pid = primary_id(db, p, d)
    primary = None
    if pid:
        try:
            primary = serialize_timetable(get_timetable(db, p, d, pid), d, pid, include_summary=False)
        except AppError:
            primary = None
    pref = get_or_create_preferences(db, p.user_id)
    current, status, message, warnings = None, "OK", None, []
    try:
        ctx = resolve_context(db, p, d, None, remember=False)
        current = serialize_timetable(ctx.timetable, d, pid, include_summary=False)
        current["selection_type"] = ctx.selection_type.value
        warnings = ctx.warnings
    except AppError as e:
        status, message = e.code.value, e.message
    db.commit()
    return {
        "domain": d.value, "status": status, "message": message, "primary": primary, "current": current,
        "selection_mode": pref.selection_mode, "warnings": warnings,
        "institutional_settings_version": settings_version(db) if d == Domain.INSTITUTIONAL else None,
        "timezone": p.timezone_id,
    }


@router.get("/timetables")
def archives(domain: str = DomainQ, page: Page = Depends(), p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    d = _dom(domain)
    rows, total = list_timetables(db, p, d, page.limit, page.offset)
    pid = primary_id(db, p, d)
    return page.envelope([serialize_timetable(t, d, pid, include_summary=False) for t in rows], total)


@router.post("/timetables/uploads", status_code=201)
async def upload(
    request: Request,
    domain: str = Form(...),
    file: UploadFile = File(...),
    title: str | None = Form(None, max_length=200),
    academic_year_id: int | None = Form(None),
    department_id: int | None = Form(None),
    client_request_id: str | None = Form(None, max_length=64),
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    s = get_settings()
    ratelimit.check("upload", str(p.user_id), s.rate_limit_upload_per_minute)
    d = _dom(domain)
    limit = s.max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AppError(Code.FILE_TOO_LARGE, f"Files must be at most {s.max_upload_mb} MB.")
    tt, job, created, warnings = create_upload(db, p, d, data, file.filename or "upload", title, academic_year_id,
                                               department_id, client_request_id)
    out = serialize_timetable(tt, d, primary_id(db, p, d))
    out.update({"created": created, "job_id": str(job.job_id) if job else None, "warnings": warnings})
    return out


@router.get("/timetables/{timetable_id}")
def get_one(timetable_id: str, domain: str = DomainQ, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    d = _dom(domain)
    tt = get_timetable(db, p, d, timetable_id)
    out = serialize_timetable(tt, d, primary_id(db, p, d))
    m = models_for(d)
    out["sections"] = [
        {"section_id": str(s.section_id), "page": s.source_page, "title": s.title, "program_level": s.program_level,
         "divisions": s.divisions, "is_tentative": s.is_tentative, "extraction_method": s.extraction_method,
         "legend": s.legend}
        for s in db.scalars(select(m.section).where(m.section.timetable_id == tt.timetable_id).order_by(m.section.source_page))
    ]
    job = db.scalar(select(ProcessingJob).where(
        (ProcessingJob.institutional_timetable_id if d == Domain.INSTITUTIONAL else ProcessingJob.personal_timetable_id)
        == tt.timetable_id).order_by(ProcessingJob.created_at.desc()))
    out["job"] = _job(job) if job else None
    return out


def _job(j: ProcessingJob) -> dict:
    return {"job_id": str(j.job_id), "status": j.status, "attempts": j.attempts, "max_attempts": j.max_attempts,
            "error_code": j.error_code, "error_message": j.error_message, "created_at": j.created_at.isoformat(),
            "started_at": j.started_at.isoformat() if j.started_at else None,
            "finished_at": j.finished_at.isoformat() if j.finished_at else None, "progress": j.progress}


@router.get("/timetables/{timetable_id}/entries")
def entries(
    timetable_id: str,
    domain: str = DomainQ,
    day_of_week: int | None = Query(None, ge=1, le=7),
    status: VerificationStatus | None = None,
    kind: EntryKind | None = None,
    needs_review: bool = False,
    review: bool = False,
    page: Page = Depends(),
    p: Principal = Depends(get_principal),
    db: Session = Depends(get_db),
):
    d = _dom(domain)
    tt = get_timetable(db, p, d, timetable_id)
    if tt.processing_status in (ProcessingStatus.QUEUED, ProcessingStatus.PROCESSING):
        raise AppError(Code.TIMETABLE_NOT_READY, "This timetable is still being processed.")
    m = models_for(d)
    q = select(m.entry).where(m.entry.timetable_id == tt.timetable_id)
    include_review = review and (d == Domain.PERSONAL or p.is_admin)
    if d == Domain.INSTITUTIONAL and not p.is_admin:
        cond = scope_condition(institutional_scope(p), tt, m.entry)
        if cond is not None:
            q = q.where(cond)
        q = q.where(m.entry.verification_status != VerificationStatus.REJECTED)
    if day_of_week:
        q = q.where(m.entry.day_of_week == day_of_week)
    if status:
        q = q.where(m.entry.verification_status == status.value)
    if kind:
        q = q.where(m.entry.entry_kind == kind.value)
    if needs_review:
        q = q.where(m.entry.verification_status.in_([VerificationStatus.UNVERIFIED, VerificationStatus.INCOMPLETE]))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(m.entry.day_of_week.nulls_last(), m.entry.start_time.nulls_last(), m.entry.source_page)
                      .limit(page.limit).offset(page.offset)).unique().all()
    env = page.envelope([serialize_entry(e, include_review=include_review) for e in rows], total)
    env["data_version"] = tt.data_version
    env["processing_status"] = tt.processing_status
    return env


@router.get("/timetables/{timetable_id}/findings")
def findings(timetable_id: str, domain: str = DomainQ, page: Page = Depends(), p: Principal = Depends(get_principal),
             db: Session = Depends(get_db)):
    d = _dom(domain)
    if d == Domain.INSTITUTIONAL and not p.is_admin:
        raise AppError(Code.ACCESS_DENIED, "Only an Admin can review institutional extraction findings.")
    tt = get_timetable(db, p, d, timetable_id)
    col = ValidationFinding.institutional_timetable_id if d == Domain.INSTITUTIONAL else ValidationFinding.personal_timetable_id
    q = select(ValidationFinding).where(col == tt.timetable_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    order = {"BLOCKING": 0, "PAGE_ERROR": 1, "CRITICAL": 2, "WARNING": 3, "METADATA_WARNING": 4, "SECTION_FLAG": 5, "INFO": 6}
    rows = sorted(db.scalars(q).all(), key=lambda f: (order.get(f.severity, 9), f.source_page or 0))
    rows = rows[page.offset: page.offset + page.limit]
    return page.envelope([{"finding_id": str(f.finding_id), "severity": f.severity, "code": f.code, "message": f.message,
                           "source_page": f.source_page, "entry_id": str(f.entry_id) if f.entry_id else None,
                           "details": f.details} for f in rows], total)


@router.get("/timetables/{timetable_id}/review-summary")
def review_summary(timetable_id: str, domain: str = DomainQ, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Everything an Admin needs before activation (prompt §9); owners get the same for personal uploads."""
    d = _dom(domain)
    if d == Domain.INSTITUTIONAL and not p.is_admin:
        raise AppError(Code.ACCESS_DENIED, "Only an Admin can review institutional uploads.")
    tt = get_timetable(db, p, d, timetable_id)
    m = models_for(d)
    base = select(m.entry).where(m.entry.timetable_id == tt.timetable_id, m.entry.entry_kind == EntryKind.CLASS)

    def count(*conds) -> int:
        return db.scalar(select(func.count()).select_from(base.where(*conds).subquery())) or 0

    missing = {
        "day": count(m.entry.day_of_week.is_(None)),
        "time": count(m.entry.start_time.is_(None)),
        "course": count(m.course_label.is_(None)),
        "professor": count(m.staff_label.is_(None)),
        "room": count(m.room_label.is_(None)),
        "batch": count(m.batch_label.is_(None)),
    }
    summary = tt.validation_summary or {}
    issue_counts = summary.get("issue_counts", {})
    out = {
        "timetable": serialize_timetable(tt, d, primary_id(db, p, d)),
        "pages_processed": summary.get("pages_parsed"),
        "pages": summary.get("pages", []),
        "sections": summary.get("sections", []),
        "entry_counts": summary.get("by_status", {}),
        "class_entries": summary.get("class_entries"),
        "missing_required_fields": missing,
        "ambiguous_time_labels": sum(issue_counts.get(k, 0) for k in
                                     ("TIME_LABEL_INCONSISTENT", "TIME_AMBIGUOUS_AMPM", "TIME_LABEL_INVALID", "TIME_SEQUENCE_CONFLICT")),
        "explicit_time_conflicts": issue_counts.get("EXPLICIT_TIME_CONFLICT", 0),
        "unverified_entries": count(m.entry.verification_status == VerificationStatus.UNVERIFIED),
        "incomplete_entries": count(m.entry.verification_status == VerificationStatus.INCOMPLETE),
        "duplicate_entries": issue_counts.get("DUPLICATE_ENTRY", 0) + issue_counts.get("DUPLICATE_EXTRACTION", 0),
        "tentative_sections": summary.get("tentative_sections", 0),
        "issue_counts": issue_counts,
        "usability": {"status": tt.processing_status, "reason": summary.get("status_reason"),
                      "primary_eligible": tt.processing_status in (ProcessingStatus.READY, ProcessingStatus.NEEDS_REVIEW)},
    }
    if d == Domain.INSTITUTIONAL and tt.processing_status in (ProcessingStatus.READY, ProcessingStatus.NEEDS_REVIEW):
        c = conflict_svc.detect(db, tt.timetable_id)
        out["conflicts"] = {"total": c["total"], "counts": c["counts"]}
    return out


@router.get("/timetables/{timetable_id}/conflicts")
def conflicts(timetable_id: str, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    if not can_view_conflicts(p):
        raise AppError(Code.ACCESS_DENIED, "Conflict overview is available to HOD, Principal and Admin.")
    tt = get_timetable(db, p, Domain.INSTITUTIONAL, timetable_id)
    depts = None
    scope = institutional_scope(p)
    if not scope.college:
        depts = set(scope.department_ids)
    return conflict_svc.detect(db, tt.timetable_id, depts)


@router.get("/timetables/{timetable_id}/file")
def download(timetable_id: str, domain: str = DomainQ, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    """Original file, streamed only after the same domain/ownership checks (no public URLs)."""
    d = _dom(domain)
    tt = get_timetable(db, p, d, timetable_id)
    try:
        data = storage.get(tt.original_file_key)
    except storage.StorageError:
        raise AppError(Code.NOT_FOUND, "The original file is not available.")
    media = {"PDF": "application/pdf", "IMAGE": "image/png" if data.startswith(b"\x89PNG") else "image/jpeg",
             "XLSX": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "DOCX": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "CSV": "text/csv"}.get(tt.file_format, "application/octet-stream")
    safe = "".join(ch for ch in tt.original_filename if ch.isalnum() or ch in "._- ") or "timetable"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{safe}"',
                                                     "Cache-Control": "private, no-store"})


@router.post("/timetables/{timetable_id}/make-primary")
def make_primary(timetable_id: str, domain: str = DomainQ, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    return set_primary(db, p, _dom(domain), timetable_id)


@router.post("/timetables/{timetable_id}/reprocess")
def reprocess(timetable_id: str, domain: str = DomainQ, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    d = _dom(domain)
    if d == Domain.INSTITUTIONAL and not p.is_admin:
        raise AppError(Code.ACCESS_DENIED, "Only an Admin can reprocess institutional uploads.")
    tt = get_timetable(db, p, d, timetable_id, for_update=True)
    return _job(retry_processing(db, p, d, tt))


@router.delete("/timetables/{timetable_id}")
def remove(timetable_id: str, domain: str = DomainQ, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    soft_delete(db, p, _dom(domain), timetable_id)
    return {"status": "OK"}


class CorrectionIn(BaseModel):
    day_of_week: int | None = Field(None, ge=1, le=7)
    start_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    end_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    entry_kind: EntryKind | None = None
    course: str | None = Field(None, max_length=200)
    professor: str | None = Field(None, max_length=200)
    batch: str | None = Field(None, max_length=100)
    room: str | None = Field(None, max_length=100)
    course_id: int | None = None
    staff_id: str | None = None
    room_id: int | None = None
    batch_id: int | None = None
    verification_status: Literal["VERIFIED", "UNVERIFIED", "REJECTED"] | None = None
    reason: str | None = Field(None, max_length=300)


@router.patch("/timetables/{timetable_id}/entries/{entry_id}")
def correct(timetable_id: str, entry_id: str, body: CorrectionIn, domain: str = DomainQ,
            p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    d = _dom(domain)
    if d == Domain.INSTITUTIONAL and not p.is_admin:
        raise AppError(Code.ACCESS_DENIED, "Only an Admin can correct institutional entries.")
    tt = get_timetable(db, p, d, timetable_id, for_update=True)
    changes = body.model_dump(exclude_unset=True)
    reason = changes.pop("reason", None)
    if d == Domain.PERSONAL:
        for k in ("course_id", "staff_id", "room_id", "batch_id"):
            if k in changes:
                raise AppError(Code.INVALID_REQUEST, "Personal entries use their own labels, not institutional records.")
    if not changes:
        raise AppError(Code.INVALID_REQUEST, "No changes supplied.")
    return correct_entry(db, p, d, tt, entry_id, changes, reason)


@router.get("/timetables/{timetable_id}/entries/{entry_id}/corrections")
def entry_corrections(timetable_id: str, entry_id: uuid.UUID, domain: str = DomainQ, p: Principal = Depends(get_principal),
                      db: Session = Depends(get_db)):
    d = _dom(domain)
    if d == Domain.INSTITUTIONAL and not p.is_admin:
        raise AppError(Code.ACCESS_DENIED, "Only an Admin can view correction history.")
    get_timetable(db, p, d, timetable_id)
    return {"items": corrections_for(db, d, entry_id)}


class BulkVerifyIn(BaseModel):
    entry_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    verification_status: Literal["VERIFIED", "REJECTED"]
    reason: str | None = Field(None, max_length=300)


@router.post("/timetables/{timetable_id}/entries/bulk-review")
def bulk_review(timetable_id: str, body: BulkVerifyIn, domain: str = DomainQ, p: Principal = Depends(get_principal),
                db: Session = Depends(get_db)):
    d = _dom(domain)
    if d == Domain.INSTITUTIONAL and not p.is_admin:
        raise AppError(Code.ACCESS_DENIED, "Only an Admin can review institutional entries.")
    tt = get_timetable(db, p, d, timetable_id, for_update=True)
    done, skipped = 0, []
    for eid in body.entry_ids:
        try:
            correct_entry(db, p, d, tt, eid, {"verification_status": body.verification_status}, body.reason)
            done += 1
        except AppError as e:
            db.rollback()
            tt = get_timetable(db, p, d, timetable_id, for_update=True)
            skipped.append({"entry_id": str(eid), "reason": e.message})
    return {"updated": done, "skipped": skipped}


@router.post("/admin/timetables/{timetable_id}/remap")
def remap(timetable_id: str, a: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Re-run master-data mapping (after adding rooms/aliases) without re-parsing the file."""
    from app.extraction.validate import assign_status
    from app.services.audit import audit
    from app.services.entries import recompute_summary
    from app.services.mapping import load_index, map_entry

    tt = get_timetable(db, a, Domain.INSTITUTIONAL, timetable_id, for_update=True)
    m = models_for(Domain.INSTITUTIONAL)
    ix = load_index(db)
    changed = 0
    for e in db.scalars(select(m.entry).where(m.entry.timetable_id == tt.timetable_id)).unique():
        if e.is_corrected or e.verification_status == VerificationStatus.REJECTED or e.entry_kind != EntryKind.CLASS:
            continue
        from app.extraction.model import CandidateEntry

        ce = CandidateEntry(None, e.source_page or 0, e.entry_kind, e.day_of_week, e.class_date, e.start_time, e.end_time,
                            e.time_label_raw, e.time_uncertain, e.course_label_raw, e.course_name_resolved,
                            e.staff_label_raw, e.staff_name_resolved, e.batch_label_raw, e.room_label_raw,
                            e.raw_extracted_text or "", e.source_region, e.extraction_method,
                            [x for x in (e.validation_messages or []) if not x["code"].endswith("_NOT_MAPPED")],
                            is_tentative=e.is_tentative)
        ids = map_entry(ix, ce)
        assign_status(ce)
        before = (e.course_id, e.staff_id, e.room_id, e.batch_id, e.verification_status)
        e.course_id, e.staff_id, e.room_id, e.batch_id = ids["course_id"], ids["staff_id"], ids["room_id"], ids["batch_id"]
        e.validation_messages = ce.messages
        e.verification_status = ce.verification_status
        if before != (e.course_id, e.staff_id, e.room_id, e.batch_id, e.verification_status):
            changed += 1
    tt.data_version += 1
    recompute_summary(db, Domain.INSTITUTIONAL, tt)
    audit(db, "INSTITUTIONAL_REMAPPED", a.user_id, "INSTITUTIONAL_TIMETABLE", tt.timetable_id, changed=changed)
    db.commit()
    return {"changed_entries": changed, "processing_status": tt.processing_status}


@router.get("/jobs")
def my_jobs(page: Page = Depends(), status: JobStatus | None = None, p: Principal = Depends(get_principal),
            db: Session = Depends(get_db)):
    """Processing-job monitor: own jobs for everyone; all institutional jobs for Admins (never others' personal jobs)."""
    q = select(ProcessingJob)
    if p.is_admin:
        q = q.where((ProcessingJob.requested_by_user_id == p.user_id) | (ProcessingJob.domain == Domain.INSTITUTIONAL.value))
    else:
        q = q.where(ProcessingJob.requested_by_user_id == p.user_id)
    if status:
        q = q.where(ProcessingJob.status == status.value)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(q.order_by(ProcessingJob.created_at.desc()).limit(page.limit).offset(page.offset)).all()
    items = []
    for j in rows:
        d = {**_job(j), "domain": j.domain,
             "timetable_id": str(j.institutional_timetable_id or j.personal_timetable_id)}
        items.append(d)
    return page.envelope(items, total)
