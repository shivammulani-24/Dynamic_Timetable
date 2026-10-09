"""Background extraction worker (Decision D-17).

Jobs live in Postgres. A worker claims one job with SELECT … FOR UPDATE SKIP LOCKED, so several
workers can run concurrently without double-processing. Jobs whose worker died (stale heartbeat)
are re-claimed. Deterministic failures (unreadable file) fail immediately; unexpected errors are
retried up to `max_attempts`.

Run:  python -m app.worker
"""
from __future__ import annotations

import logging
import os
import signal
import socket
import time
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_factory
from app.enums import Domain, JobStatus, ProcessingStatus, VerificationStatus
from app.extraction.model import PARSER_VERSION
from app.extraction.pipeline import ExtractionFailed, run_extraction
from app.extraction.validate import assign_status, summarize
from app.logging_setup import configure_logging
from app.models import ProcessingJob, ValidationFinding
from app.security.tokens import utcnow
from app.services import storage
from app.services.audit import audit
from app.services.domains import models_for
from app.services.mapping import load_index, map_entry
from app.services.notifications import notify, send_push, wants_processing_updates

log = logging.getLogger("worker")
WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"
STALE_AFTER = timedelta(minutes=10)


def claim(db: Session) -> ProcessingJob | None:
    job = db.scalar(
        select(ProcessingJob)
        .where(or_(
            ProcessingJob.status == JobStatus.QUEUED,
            (ProcessingJob.status == JobStatus.RUNNING) & (ProcessingJob.heartbeat_at < utcnow() - STALE_AFTER),
        ))
        .order_by(ProcessingJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    job.status = JobStatus.RUNNING
    job.attempts += 1
    job.worker_id = WORKER_ID
    job.started_at = job.heartbeat_at = utcnow()
    tt = _timetable(db, job)
    tt.processing_status = ProcessingStatus.PROCESSING
    tt.processing_started_at = utcnow()
    db.commit()
    return job


def _timetable(db: Session, job: ProcessingJob):
    m = models_for(job.domain)
    tid = job.institutional_timetable_id if job.domain == Domain.INSTITUTIONAL else job.personal_timetable_id
    return db.get(m.meta, tid, with_for_update=True)


def _target_kwargs(domain: str, tid) -> dict:
    return {"institutional_timetable_id": tid} if domain == Domain.INSTITUTIONAL else {"personal_timetable_id": tid}


def persist(db: Session, domain: Domain, tt, result) -> tuple[ProcessingStatus, dict]:
    """Replace this timetable's extracted rows with the new result (idempotent for retries)."""
    m = models_for(domain)
    institutional = domain == Domain.INSTITUTIONAL
    db.execute(delete(m.entry).where(m.entry.timetable_id == tt.timetable_id))
    db.execute(delete(m.section).where(m.section.timetable_id == tt.timetable_id))
    db.execute(delete(ValidationFinding).where(
        (ValidationFinding.institutional_timetable_id if institutional else ValidationFinding.personal_timetable_id) == tt.timetable_id))

    section_ids = {}
    for s in result.sections:
        row = m.section(timetable_id=tt.timetable_id, source_page=s.page, title=s.title, program_level=s.program_level,
                        divisions=s.divisions, is_tentative=s.is_tentative, header_raw=s.header_raw, legend=s.legend,
                        extraction_method=s.method)
        db.add(row)
        db.flush()
        section_ids[s.key] = row.section_id

    index = load_index(db, tt.department_id) if institutional else None
    entry_rows = []
    for e in result.entries:
        ids = {}
        if institutional and e.verification_status != VerificationStatus.REJECTED:
            ids = map_entry(index, e)
            assign_status(e)  # mapping warnings can downgrade VERIFIED → UNVERIFIED
        common = dict(
            timetable_id=tt.timetable_id, section_id=section_ids.get(e.section_key), entry_kind=e.entry_kind,
            day_of_week=e.day_of_week, class_date=e.class_date, start_time=e.start_time, end_time=e.end_time,
            time_label_raw=e.time_label_raw, time_uncertain=e.time_uncertain, course_name_resolved=e.course_name,
            staff_name_resolved=e.staff_name, raw_extracted_text=e.raw_text, source_page=e.page, source_region=e.region,
            confidence_score=Decimal(str(e.confidence)), verification_status=e.verification_status,
            validation_messages=e.messages, is_tentative=e.is_tentative, extraction_method=e.method,
        )
        if institutional:
            row = m.entry(course_label_raw=e.course_label, batch_label_raw=e.batch_label, staff_label_raw=e.staff_label,
                          room_label_raw=e.room_label, **ids, **common)
        else:
            row = m.entry(course_label=e.course_label, batch_label=e.batch_label, professor_label=e.staff_label,
                          room_label=e.room_label, **common)
        db.add(row)
        entry_rows.append(row)
    db.flush()

    status, summary = summarize(result)
    for f in result.findings:
        db.add(ValidationFinding(
            domain=domain.value, **_target_kwargs(domain, tt.timetable_id), severity=f.severity, code=f.code,
            message=f.message[:500], source_page=f.page,
            entry_id=entry_rows[f.entry_index].entry_id if f.entry_index is not None and f.entry_index < len(entry_rows) else None,
            details=f.details,
        ))
    prior = tt.validation_summary or {}
    if prior.get("upload_warnings"):
        summary["upload_warnings"] = prior["upload_warnings"]
    tt.validation_summary = summary
    tt.processing_status = status
    tt.parser_version = PARSER_VERSION
    tt.page_count = result.page_count
    tt.effective_from = result.effective_from
    tt.effective_from_raw = result.effective_from_raw
    tt.term_label = result.term_label
    tt.data_version = (tt.data_version or 0) + 1
    return status, summary


def _finish_notify(db: Session, domain: str, tt, job: ProcessingJob, ok: bool, msg: str) -> None:
    uid = job.requested_by_user_id
    if wants_processing_updates(db, uid):
        title = "Timetable processed" if ok else "Timetable processing failed"
        notify(db, [uid], "PROCESSING_COMPLETED" if ok else "PROCESSING_FAILED", title, msg,
               {"timetable_id": str(tt.timetable_id), "domain": domain})


def process_job(job_id) -> str:
    """Process one claimed job. Returns the final job status."""
    sf = session_factory()
    with sf() as db:
        job = db.get(ProcessingJob, job_id, with_for_update=True)
        tt = _timetable(db, job)
        domain = Domain(job.domain)
        try:
            data = storage.get(tt.original_file_key)
            result = run_extraction(data, tt.file_format, require_scope=domain == Domain.INSTITUTIONAL)
            status, summary = persist(db, domain, tt, result)
            tt.processing_finished_at = utcnow()
            job.status = JobStatus.SUCCEEDED
            job.finished_at = utcnow()
            job.progress = {"entries": summary["entries_total"], "pages": summary["page_count"]}
            if domain == Domain.INSTITUTIONAL:
                audit(db, "INSTITUTIONAL_VALIDATION_COMPLETED", job.requested_by_user_id, "INSTITUTIONAL_TIMETABLE",
                      tt.timetable_id, status=status.value, by_status=summary["by_status"])
            msg = f"“{tt.title}”: {summary['usable_class_entries']} usable classes — status {status.value.replace('_', ' ').lower()}."
            _finish_notify(db, domain.value, tt, job, status in (ProcessingStatus.READY, ProcessingStatus.NEEDS_REVIEW), msg)
            db.commit()
            send_push(db, [job.requested_by_user_id], "Timetable processed", msg)
            return job.status
        except (ExtractionFailed, storage.StorageError) as e:
            db.rollback()
            code = getattr(e, "code", "FILE_MISSING")
            message = getattr(e, "message", str(e))
            return _fail(job_id, code, message, retry=False)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            log.exception("job %s crashed", job_id)
            return _fail(job_id, "INTERNAL_ERROR", f"Unexpected processing error ({e.__class__.__name__}).", retry=True)


def _fail(job_id, code: str, message: str, retry: bool) -> str:
    with session_factory()() as db:
        job = db.get(ProcessingJob, job_id, with_for_update=True)
        tt = _timetable(db, job)
        job.error_code = code
        job.error_message = message[:500]
        if retry and job.attempts < job.max_attempts:
            job.status = JobStatus.QUEUED
            tt.processing_status = ProcessingStatus.QUEUED
        else:
            job.status = JobStatus.FAILED
            job.finished_at = utcnow()
            tt.processing_status = ProcessingStatus.FAILED
            tt.processing_finished_at = utcnow()
            tt.validation_summary = {**(tt.validation_summary or {}), "status_reason": message, "error_code": code}
            if job.domain == Domain.INSTITUTIONAL:
                audit(db, "INSTITUTIONAL_VALIDATION_FAILED", job.requested_by_user_id, "INSTITUTIONAL_TIMETABLE",
                      tt.timetable_id, error_code=code)
            _finish_notify(db, job.domain, tt, job, False, f"“{tt.title}” could not be processed: {message}")
        db.commit()
        return job.status


def process_next() -> str | None:
    with session_factory()() as db:
        job = claim(db)
        job_id = job.job_id if job else None
    if job_id is None:
        return None
    return process_job(job_id)


def drain(max_jobs: int = 100) -> int:
    """Process queued jobs until none remain (used by tests and the dev seed)."""
    n = 0
    while n < max_jobs and process_next() is not None:
        n += 1
    return n


_running = True


def main() -> None:
    configure_logging(get_settings().log_level)
    log.info("worker %s started", WORKER_ID)

    def stop(*_):
        global _running
        _running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while _running:
        try:
            if process_next() is None:
                time.sleep(get_settings().worker_poll_seconds)
        except Exception:  # noqa: BLE001 — keep the worker alive (e.g. DB restart)
            log.exception("worker loop error")
            time.sleep(5)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
