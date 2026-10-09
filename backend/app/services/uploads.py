"""Upload intake (PDF spec stages 1–3): validate, store privately, create archive + job.

Uploading never changes any primary selection.
"""
from __future__ import annotations

import hashlib
import os

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.enums import Domain, JobStatus, ProcessingStatus
from app.errors import AppError, Code
from app.extraction.filetypes import ACCEPT_EXTENSIONS, detect_format
from app.models import AcademicYear, Department, InstitutionalTimetable, PersonalTimetable, ProcessingJob
from app.security.principal import Principal
from app.services import storage
from app.services.audit import audit


def _quick_check(fmt: str, data: bytes) -> int | None:
    """Parseability / page-limit check done synchronously so obviously bad files are rejected at once."""
    if fmt != "PDF":
        return None
    from app.extraction.pdf import PdfOpenError, open_pdf

    try:
        doc = open_pdf(data)
    except PdfOpenError as e:
        raise AppError(Code.UNSUPPORTED_FILE, f"This PDF cannot be read: {e}", {"reason": "PDF_UNREADABLE"})
    n = doc.page_count
    doc.close()
    if n > get_settings().max_pages:
        raise AppError(Code.FILE_TOO_LARGE, f"The PDF has {n} pages; the maximum is {get_settings().max_pages}.",
                       {"reason": "TOO_MANY_PAGES"})
    return n


def create_upload(
    db: Session,
    p: Principal,
    domain: Domain,
    data: bytes,
    filename: str,
    title: str | None,
    academic_year_id: int | None = None,
    department_id: int | None = None,
    client_request_id: str | None = None,
) -> tuple[object, ProcessingJob, bool, list[dict]]:
    s = get_settings()
    if domain == Domain.INSTITUTIONAL and not p.is_admin:
        raise AppError(Code.ACCESS_DENIED, "Only an Admin can upload official institutional timetables.")
    filename = os.path.basename(filename or "upload")[:255]
    ext = os.path.splitext(filename.lower())[1]
    if ext not in ACCEPT_EXTENSIONS:
        raise AppError(Code.UNSUPPORTED_FILE, "Supported files: PDF, Excel (.xlsx/.xls), CSV, Word (.docx/.doc), JPG or PNG.",
                       {"reason": "EXTENSION"})
    if not data:
        raise AppError(Code.INVALID_REQUEST, "The file is empty.")
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise AppError(Code.FILE_TOO_LARGE, f"Files must be at most {s.max_upload_mb} MB.")
    fmt = detect_format(data, filename)
    if fmt is None:
        raise AppError(Code.UNSUPPORTED_FILE, "The file's contents do not match a supported timetable format.",
                       {"reason": "SIGNATURE"})

    m = InstitutionalTimetable if domain == Domain.INSTITUTIONAL else PersonalTimetable
    owner_col = m.uploaded_by_user_id if domain == Domain.INSTITUTIONAL else m.owner_user_id
    if client_request_id:
        existing = db.scalar(select(m).where(owner_col == p.user_id, m.client_request_id == client_request_id))
        if existing is not None:  # idempotent retry of the same upload
            job = db.scalar(select(ProcessingJob).where(
                (ProcessingJob.institutional_timetable_id if domain == Domain.INSTITUTIONAL else ProcessingJob.personal_timetable_id)
                == existing.timetable_id).order_by(ProcessingJob.created_at.desc()))
            return existing, job, False, []

    page_count = _quick_check(fmt, data)
    sha = hashlib.sha256(data).hexdigest()
    warnings: list[dict] = []
    dup_q = select(m.timetable_id, m.title).where(m.file_sha256 == sha, m.deleted_at.is_(None))
    if domain == Domain.PERSONAL:
        dup_q = dup_q.where(m.owner_user_id == p.user_id)
    dup = db.execute(dup_q.limit(1)).first()
    if dup:
        warnings.append({"code": "DUPLICATE_FILE",
                         "message": f"This exact file was uploaded before (“{dup.title}”). A separate archive was still created.",
                         "duplicate_of": str(dup.timetable_id)})

    if domain == Domain.INSTITUTIONAL:
        if academic_year_id is None:
            raise AppError(Code.INVALID_REQUEST, "Choose the academic year for this timetable.", {"field": "academic_year_id"})
        if db.get(AcademicYear, academic_year_id) is None:
            raise AppError(Code.INVALID_REQUEST, "Unknown academic year.", {"field": "academic_year_id"})
        if department_id is not None and db.get(Department, department_id) is None:
            raise AppError(Code.INVALID_REQUEST, "Unknown department.", {"field": "department_id"})
        scope = str(academic_year_id)
    else:
        scope = str(p.user_id)

    key = storage.new_key(domain.value, scope, ext)
    try:
        storage.put(key, data)
    except storage.StorageError:
        raise AppError(Code.INTERNAL_ERROR, "The file could not be stored. Nothing was saved; please try again.")

    common = dict(
        title=(title or os.path.splitext(filename)[0]).strip()[:200] or "Timetable",
        original_file_key=key, original_filename=filename, file_sha256=sha, file_format=fmt,
        file_size_bytes=len(data), processing_status=ProcessingStatus.QUEUED, page_count=page_count,
        client_request_id=client_request_id,
        validation_summary={"upload_warnings": warnings} if warnings else {},
    )
    if domain == Domain.INSTITUTIONAL:
        tt = InstitutionalTimetable(academic_year_id=academic_year_id, department_id=department_id,
                                    uploaded_by_user_id=p.user_id, **common)
    else:
        tt = PersonalTimetable(owner_user_id=p.user_id, **common)
    try:
        db.add(tt)
        db.flush()
        job = ProcessingJob(
            domain=domain.value, requested_by_user_id=p.user_id, status=JobStatus.QUEUED,
            max_attempts=s.job_max_attempts,
            **({"institutional_timetable_id": tt.timetable_id} if domain == Domain.INSTITUTIONAL
               else {"personal_timetable_id": tt.timetable_id}),
        )
        db.add(job)
        if domain == Domain.INSTITUTIONAL:
            audit(db, "INSTITUTIONAL_UPLOAD", p.user_id, "INSTITUTIONAL_TIMETABLE", tt.timetable_id,
                  filename=filename, sha256=sha, format=fmt)
        db.commit()
    except IntegrityError:
        db.rollback()
        storage.delete(key)
        if client_request_id:  # a concurrent identical request won the race
            existing = db.scalar(select(m).where(owner_col == p.user_id, m.client_request_id == client_request_id))
            if existing is not None:
                job = db.scalar(select(ProcessingJob).where(
                    (ProcessingJob.institutional_timetable_id if domain == Domain.INSTITUTIONAL else ProcessingJob.personal_timetable_id)
                    == existing.timetable_id))
                return existing, job, False, []
        raise
    except Exception:
        db.rollback()
        storage.delete(key)
        raise
    return tt, job, True, warnings


def retry_processing(db: Session, p: Principal, domain: Domain, tt) -> ProcessingJob:
    if tt.processing_status not in (ProcessingStatus.FAILED, ProcessingStatus.UNUSABLE, ProcessingStatus.NEEDS_REVIEW,
                                    ProcessingStatus.READY):
        raise AppError(Code.CONFLICT, "This timetable is already queued or processing.")
    active = db.scalar(select(ProcessingJob).where(
        (ProcessingJob.institutional_timetable_id if domain == Domain.INSTITUTIONAL else ProcessingJob.personal_timetable_id)
        == tt.timetable_id, ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING])))
    if active:
        raise AppError(Code.CONFLICT, "A processing job is already pending for this timetable.")
    from app.services.timetables import primary_id

    if primary_id(db, p, domain) == tt.timetable_id:
        raise AppError(Code.PRIMARY_SELECTION_CONFLICT,
                       "Re-processing the current primary timetable would change live data. Select another primary first.")
    job = ProcessingJob(domain=domain.value, requested_by_user_id=p.user_id, status=JobStatus.QUEUED,
                        max_attempts=get_settings().job_max_attempts,
                        **({"institutional_timetable_id": tt.timetable_id} if domain == Domain.INSTITUTIONAL
                           else {"personal_timetable_id": tt.timetable_id}))
    tt.processing_status = ProcessingStatus.QUEUED
    db.add(job)
    audit(db, f"{domain.value}_REPROCESS_REQUESTED", p.user_id, f"{domain.value}_TIMETABLE", tt.timetable_id)
    db.commit()
    return job
