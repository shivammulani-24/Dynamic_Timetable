"""Entry verification status, heuristic confidence, document-level checks and usability (D-08).

The numeric confidence is an *uncalibrated heuristic* used for sorting/review only; the
verification status is authoritative. No accuracy figure is claimed until measured against a
manually labelled set (PDF spec §5, §11).
"""
from __future__ import annotations

from collections import defaultdict

from app.enums import ProcessingStatus, VerificationStatus
from app.extraction.model import CandidateEntry, ExtractionResult, Finding
from app.services.matching import normalize_label

USABLE_MIN_RATIO = 0.25


def assign_status(e: CandidateEntry) -> None:
    sev = {m["severity"] for m in e.messages}
    missing_critical = e.day_of_week is None or e.start_time is None or e.end_time is None
    if missing_critical or any(m["code"] == "SECTION_SCOPE_UNKNOWN" for m in e.messages):
        e.verification_status = VerificationStatus.INCOMPLETE
    elif e.time_uncertain or "CRITICAL" in sev or "WARNING" in sev or e.method in ("OCR", "TEXT_GEOMETRIC") or e.is_tentative:
        e.verification_status = VerificationStatus.UNVERIFIED
    else:
        e.verification_status = VerificationStatus.VERIFIED
    if e.is_tentative and not any(m["code"] == "TENTATIVE_SECTION" for m in e.messages):
        e.messages.append({"severity": "WARNING", "code": "TENTATIVE_SECTION",
                           "message": "This timetable section is marked 'Tentative' in the source."})
    conf = 1.0
    if e.method == "OCR":
        ocr = (e.region or {}).get("ocr_confidence")
        conf -= 0.3 if ocr is None else max(0.1, (100 - ocr) / 100 + 0.1)
    if e.method == "TEXT_GEOMETRIC":
        conf -= 0.15
    conf -= 0.08 * sum(1 for m in e.messages if m["severity"] == "WARNING")
    if e.time_uncertain:
        conf -= 0.25
    if e.verification_status == VerificationStatus.INCOMPLETE:
        conf = min(conf, 0.3)
    e.confidence = round(max(0.05, min(1.0, conf)), 4)


def _key(e: CandidateEntry, with_region: bool) -> tuple:
    k = (e.page, e.day_of_week, e.start_time, e.end_time, e.entry_kind, normalize_label(e.course_label),
         normalize_label(e.batch_label), normalize_label(e.staff_label), normalize_label(e.room_label))
    return k + ((str(e.region),) if with_region else ())


def _is_division_of(a: str, b: str) -> bool:
    """'SE-A' is the division of 'SE-A1' (lab sub-group)."""
    return b.startswith(a) and len(b) == len(a) + 1 and b[-1].isdigit()


def _same_cell(a: CandidateEntry, b: CandidateEntry) -> bool:
    ra, rb = a.region or {}, b.region or {}
    return (a.page == b.page and ra.get("grid_row") is not None
            and (ra.get("grid_row"), ra.get("grid_col")) == (rb.get("grid_row"), rb.get("grid_col")))


def document_checks(entries: list[CandidateEntry]) -> list[Finding]:
    findings: list[Finding] = []
    seen_exact: dict[tuple, int] = {}
    seen_loose: dict[tuple, int] = {}
    for i, e in enumerate(entries):
        ke = _key(e, True)
        if ke in seen_exact:
            e.verification_status = VerificationStatus.REJECTED
            e.messages.append({"severity": "WARNING", "code": "DUPLICATE_EXTRACTION",
                               "message": "Identical to another extracted entry from the same cell; rejected as an extraction artifact."})
            continue
        seen_exact[ke] = i
        kl = _key(e, False)
        if kl in seen_loose and e.entry_kind == "CLASS":
            j = seen_loose[kl]
            for x in (e, entries[j]):
                if not x.has_code("DUPLICATE_ENTRY"):
                    x.messages.append({"severity": "WARNING", "code": "DUPLICATE_ENTRY",
                                       "message": "The same class appears more than once on this page."})
            findings.append(Finding("WARNING", "DUPLICATE_ENTRY", "Possible duplicate class entries.", e.page,
                                    entry_index=i, details={"other_entry_index": j}))
        else:
            seen_loose[kl] = i

    by_day: dict[tuple, list[int]] = defaultdict(list)
    for i, e in enumerate(entries):
        if e.entry_kind == "CLASS" and e.day_of_week and e.start_time and e.end_time and e.batch_label \
                and e.verification_status != VerificationStatus.REJECTED:
            by_day[(e.day_of_week, e.section_key)].append(i)
    for idxs in by_day.values():
        for a_pos, a in enumerate(idxs):
            for b in idxs[a_pos + 1:]:
                ea, eb = entries[a], entries[b]
                if not (ea.start_time < eb.end_time and eb.start_time < ea.end_time):
                    continue
                la, lb = normalize_label(ea.batch_label), normalize_label(eb.batch_label)
                if not (la == lb or _is_division_of(la, lb) or _is_division_of(lb, la)):
                    continue
                if "batch" in (ea.course_label or "").lower() and "batch" in (eb.course_label or "").lower():
                    continue  # parallel elective groups
                if _same_cell(ea, eb) or (ea.has_code("PARALLEL_OPTION") and eb.has_code("PARALLEL_OPTION")):
                    continue  # stacked in one cell / elective options: listed together on purpose
                for x in (ea, eb):
                    if not x.has_code("POSSIBLE_BATCH_OVERLAP"):
                        x.messages.append({"severity": "WARNING", "code": "POSSIBLE_BATCH_OVERLAP",
                                           "message": "Overlaps another class for the same batch; review (parallel groups may be valid)."})
                findings.append(Finding("WARNING", "POSSIBLE_BATCH_OVERLAP",
                                        f"Batch {ea.batch_label} has overlapping classes.", ea.page, entry_index=a,
                                        details={"other_entry_index": b}))
    return findings


def summarize(result: ExtractionResult) -> tuple[ProcessingStatus, dict]:
    classes = [e for e in result.entries if e.entry_kind == "CLASS"]
    counts: dict[str, int] = defaultdict(int)
    for e in classes:
        counts[e.verification_status] += 1
    usable = counts[VerificationStatus.VERIFIED] + counts[VerificationStatus.UNVERIFIED]
    total = len(classes)
    sev = defaultdict(int)
    codes: dict[str, int] = defaultdict(int)
    for f in result.findings:
        sev[f.severity] += 1
    for e in result.entries:
        for m in e.messages:
            codes[m["code"]] += 1
    blocking = any(f.severity == "BLOCKING" for f in result.findings)
    if blocking or usable == 0 or (total and usable / total < USABLE_MIN_RATIO):
        status = ProcessingStatus.UNUSABLE
    elif (counts[VerificationStatus.UNVERIFIED] or counts[VerificationStatus.INCOMPLETE]
          or counts[VerificationStatus.REJECTED] or sev.get("WARNING") or sev.get("PAGE_ERROR")
          or any(s.is_tentative for s in result.sections) or sev.get("METADATA_WARNING")):
        status = ProcessingStatus.NEEDS_REVIEW
    else:
        status = ProcessingStatus.READY
    pages_parsed = sum(1 for p in result.pages if p.get("status") == "PARSED")
    summary = {
        "status_reason": _reason(status, usable, total, blocking),
        "page_count": result.page_count,
        "pages_parsed": pages_parsed,
        "pages_ocr": sum(1 for p in result.pages if p.get("method") == "OCR"),
        "pages_failed": sum(1 for p in result.pages if p.get("status") in ("FAILED", "NO_TABLE")),
        "pages": result.pages,
        "sections": [
            {"key": s.key, "page": s.page, "title": s.title, "program_level": s.program_level, "divisions": s.divisions,
             "is_tentative": s.is_tentative, "legend_faculty": len(s.legend.get("faculty", {})),
             "legend_subjects": len(s.legend.get("subject", {}))}
            for s in result.sections
        ],
        "entries_total": len(result.entries),
        "class_entries": total,
        "non_class_entries": len(result.entries) - total,
        "usable_class_entries": usable,
        "by_status": dict(counts),
        "issue_counts": dict(sorted(codes.items(), key=lambda kv: -kv[1])),
        "findings_by_severity": dict(sev),
        "tentative_sections": sum(1 for s in result.sections if s.is_tentative),
        "time_uncertain_entries": sum(1 for e in classes if e.time_uncertain),
        "usability_rule": f"UNUSABLE if no usable class entries or fewer than {int(USABLE_MIN_RATIO * 100)}% usable.",
        "confidence_note": "Confidence scores are uncalibrated heuristics; verification status is authoritative.",
    }
    return status, summary


def _reason(status: ProcessingStatus, usable: int, total: int, blocking: bool) -> str:
    if status == ProcessingStatus.UNUSABLE:
        if blocking:
            return "A blocking problem prevented extraction."
        return f"Only {usable} of {total} class entries are usable — below the minimum threshold."
    if status == ProcessingStatus.NEEDS_REVIEW:
        return "Usable, but some entries are unverified, incomplete or flagged for review."
    return "All class entries passed validation."
