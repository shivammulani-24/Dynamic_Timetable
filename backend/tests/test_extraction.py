"""PDF Extraction & Validation spec tests (PDF-01 … PDF-13) on SYNTHETIC fixtures, plus other formats."""
from __future__ import annotations

from datetime import time

import pytest

from app.extraction.cellparse import parse_cell
from app.extraction.filetypes import detect_format
from app.extraction.pipeline import ExtractionFailed, run_extraction
from app.extraction.timeparse import parse_time_label, resolve_sequence
from app.extraction.validate import summarize


def _run(fx, name, fmt=None, require_scope=True):
    data = open(fx(name), "rb").read()
    return run_extraction(data, fmt or detect_format(data, name), require_scope=require_scope)


@pytest.fixture(scope="module")
def pdf_result(fx):
    return _run(fx, "synthetic_timetable.pdf")


def test_pdf01_all_pages_with_provenance(pdf_result):
    assert pdf_result.page_count == 3
    assert [p["page"] for p in pdf_result.pages] == [1, 2, 3]
    assert all(p["status"] == "PARSED" for p in pdf_result.pages)
    assert all(e.page in (1, 2, 3) for e in pdf_result.entries)
    assert all(e.raw_text for e in pdf_result.entries)


def test_pdf02_grid_legends_and_entries(pdf_result):
    sec = pdf_result.sections[0]
    assert sec.program_level == "SE" and sec.divisions == ["A"]
    assert sec.legend["faculty"]["KKD"].startswith("Prof.")
    assert sec.legend["subject"]["DBMS"] == "Database Management Systems"
    mon9 = [e for e in pdf_result.entries if e.page == 1 and e.day_of_week == 1 and e.start_time == time(9)]
    assert len(mon9) == 1
    e = mon9[0]
    assert (e.course_label, e.staff_label, e.room_label, e.batch_label) == ("DBMS", "KKD", "508", "SE-A")
    assert e.course_name == "Database Management Systems" and e.end_time == time(10)


def test_pdf03_tentative_section_flag(pdf_result):
    assert [s.is_tentative for s in pdf_result.sections] == [False, True, False]
    tentative_entries = [e for e in pdf_result.entries if e.page == 2 and e.entry_kind == "CLASS"]
    assert tentative_entries and all(e.is_tentative and e.verification_status != "VERIFIED" for e in tentative_entries)


def test_pdf05_combined_divisions_not_assigned_to_one(pdf_result):
    be = [e for e in pdf_result.entries if e.page == 3 and e.entry_kind == "CLASS"]
    combined = [e for e in be if e.batch_label == "BE-A/B/C/D"]
    assert combined and all(e.has_code("DIVISION_SCOPE_COMBINED") for e in combined)
    # a cell that names its own sub-group keeps it
    assert any(e.batch_label == "BE-B2" for e in be)


def test_pdf06_stacked_labs_become_separate_entries(pdf_result):
    labs = [e for e in pdf_result.entries if e.page == 1 and e.day_of_week == 1 and e.start_time == time(10)]
    assert sorted(e.batch_label for e in labs) == ["SE-A1", "SE-A2"]
    assert {e.room_label for e in labs} == {"604", "605"}


def test_pdf07_only_legend_abbreviations_are_expanded(pdf_result):
    qq = [e for e in pdf_result.entries if e.course_label == "QQ"]
    assert qq and qq[0].course_name is None and qq[0].has_code("COURSE_ABBREVIATION_UNKNOWN")


def test_pdf08_room_suffixes_preserved(pdf_result):
    rooms = {e.room_label for e in pdf_result.entries if e.room_label}
    assert {"509 old", "702-B", "606-4"} <= rooms


def test_pdf09_inconsistent_noon_label_flagged_not_silently_fixed(pdf_result):
    noon = [e for e in pdf_result.entries if e.time_label_raw and "12.15 a.m." in e.time_label_raw]
    assert noon
    for e in noon:
        assert e.time_uncertain and e.has_code("TIME_LABEL_INCONSISTENT")
        assert e.verification_status in ("UNVERIFIED", "INCOMPLETE")


def test_merged_two_hour_lab_spans_rows(pdf_result):
    lab = [e for e in pdf_result.entries if e.page == 1 and e.batch_label == "SE-A3"]
    assert lab and lab[0].start_time == time(11, 15) and lab[0].end_time == time(13, 15)
    assert lab[0].time_uncertain  # second hour uses the inconsistent label


def test_pdf10_breaks_and_activity_are_not_classes(pdf_result):
    kinds = {(e.entry_kind, e.course_label) for e in pdf_result.entries if e.entry_kind != "CLASS"}
    assert ("BREAK", "SHORT BREAK") in kinds and ("BREAK", "LONG BREAK") in kinds
    assert any(k == "ACTIVITY" for k, _ in kinds)


def test_pdf11_missing_room_kept_with_warning(pdf_result):
    e = next(e for e in pdf_result.entries if e.course_label == "QQ")
    assert e.room_label is None and e.has_code("ROOM_MISSING") and e.staff_label == "KKD"


def test_effective_date_and_status(pdf_result):
    assert str(pdf_result.effective_from) == "2026-08-10"
    status, summary = summarize(pdf_result)
    assert status == "NEEDS_REVIEW"
    assert summary["tentative_sections"] == 1 and summary["usable_class_entries"] > 0


def test_pdf12_scanned_pdf_uses_ocr_with_provenance(fx):
    r = _run(fx, "synthetic_scanned.pdf")
    assert r.pages[0]["method"] == "OCR"
    classes = [e for e in r.entries if e.entry_kind == "CLASS"]
    assert classes, "OCR should recover at least some class entries"
    assert all(e.method == "OCR" and e.verification_status != "VERIFIED" for e in classes)


def test_pdf13_corrupt_pdf_fails_safely(fx):
    with pytest.raises(ExtractionFailed) as ei:
        _run(fx, "corrupt.pdf", "PDF")
    assert ei.value.code == "FILE_UNREADABLE"


def test_no_timetable_pdf_is_unusable(fx):
    r = _run(fx, "no_timetable.pdf")
    status, _ = summarize(r)
    assert status == "UNUSABLE"


@pytest.mark.parametrize("name,fmt", [("synthetic_timetable.xlsx", "XLSX"), ("synthetic_timetable.csv", "CSV"),
                                      ("synthetic_timetable.docx", "DOCX"), ("synthetic_page1.png", "IMAGE")])
def test_other_formats_use_same_pipeline(fx, name, fmt):
    data = open(fx(name), "rb").read()
    assert detect_format(data, name) == fmt
    r = run_extraction(data, fmt, require_scope=True)
    classes = [e for e in r.entries if e.entry_kind == "CLASS"]
    assert len(classes) >= 15
    assert any(e.course_label == "DBMS" and e.day_of_week == 1 for e in classes)
    status, _ = summarize(r)
    assert status in ("READY", "NEEDS_REVIEW")


def test_docx_merged_lab_cell_spans_two_rows(fx):
    r = _run(fx, "synthetic_timetable.docx")
    lab = [e for e in r.entries if e.batch_label == "SE-A3"]
    assert lab and lab[0].start_time == time(11, 15) and lab[0].end_time == time(13, 15)


def test_signature_detection_rejects_mismatch(fx):
    assert detect_format(b"hello world", "x.pdf") is None
    assert detect_format(open(fx("not_a_timetable.txt"), "rb").read(), "a.txt") is None
    assert detect_format(open(fx("synthetic_timetable.pdf"), "rb").read(), "renamed.xlsx") == "PDF"


def test_time_rules():
    seq = ["9:00-10:00", "10:00-11:00", "1:00-2:00"]
    out = resolve_sequence([parse_time_label(s) for s in seq])
    assert [(o.start, o.end) for o in out] == [(time(9), time(10)), (time(10), time(11)), (time(13), time(14))]
    amb = resolve_sequence([parse_time_label("7:00-8:00")])[0]
    assert amb.start is None and amb.issues[0]["code"] == "TIME_AMBIGUOUS_AMPM"
    bad = resolve_sequence([parse_time_label("11:00-10:00")])[0]
    assert bad.start is None


def test_cell_grammar_explicit_time_and_electives():
    leg = {"faculty": {"KKD": "Prof. K"}, "subject": {"DBMS": "Database"}}
    items = parse_cell("DBMS Lab B2/KKD/\n508 (1.15-3.15)", leg)
    assert items[0].subgroup == "B2" and items[0].room_label == "508" and items[0].explicit_time is not None
    el = parse_cell("PE III-TSDA Batch1/RHS/701", leg)[0]
    assert el.group_label == "Batch1" and el.course_label == "PE III-TSDA"
