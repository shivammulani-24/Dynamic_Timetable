"""Regression tests on the college's real timetable PDF (tests/fixtures/reference/college_timetable.pdf).

Expected values below were read by hand from the rendered pages. They pin behaviour on this one
document; they are NOT an accuracy measurement (no labelled sample has been scored yet).
"""
from __future__ import annotations

from datetime import date, time
from pathlib import Path

import pytest

from app.enums import ProcessingStatus
from app.extraction.pipeline import run_extraction
from app.extraction.validate import summarize

PDF = Path(__file__).parent / "fixtures" / "reference" / "college_timetable.pdf"


@pytest.fixture(scope="module")
def result():
    return run_extraction(PDF.read_bytes(), "PDF", require_scope=True)


def _find(result, page, day, start, course, batch=None):
    return [e for e in result.entries if e.page == page and e.day_of_week == day and e.start_time == start
            and e.course_label == course and (batch is None or e.batch_label == batch)]


def test_every_page_parsed_and_document_usable(result):
    status, summary = summarize(result)
    assert result.page_count == 10 and summary["pages_parsed"] == 10
    assert status == ProcessingStatus.NEEDS_REVIEW          # usable, with honest review flags
    assert summary["usable_class_entries"] / summary["class_entries"] > 0.9
    assert "SECTION_SCOPE_UNKNOWN" not in summary["issue_counts"]


def test_section_headings_inside_the_table_are_read(result):
    got = [(s.page, s.program_level, tuple(s.divisions)) for s in result.sections]
    assert got == [(1, "SE", ("A",)), (2, "SE", ("B",)), (3, "SE", ("C",)), (4, "SE", ("D",)),
                   (5, "TE", ("A",)), (6, "TE", ("B",)), (7, "TE", ("C",)), (8, "TE", ("D",)),
                   (9, "BE", ("A", "B", "C", "D")), (10, "MTECH", ())]
    assert result.sections[0].effective_from == date(2026, 8, 10)
    assert result.sections[9].effective_from == date(2026, 9, 7)
    # Page 10 states a different W.E.F. date: the date most pages state is used, the other is noted.
    assert result.effective_from == date(2026, 8, 10)
    assert any(f.code == "EFFECTIVE_DATE_VARIES" and f.severity == "INFO" for f in result.findings)
    assert all(s.academic_year_label == "2026-2027" for s in result.sections)


def test_legends_below_the_grid_are_split_by_column(result):
    p1 = result.sections[0].legend
    assert len(p1["faculty"]) == 21 and len(p1["subject"]) == 9
    assert p1["faculty"]["KKD"] == "Dr. Kailas Devadkar"
    assert p1["subject"]["DBMS"] == "Database Management Systems"
    assert "KKD" not in p1["subject"]
    # Page 1's cell clips "Graph Theory" at its border; page 2 prints it in full.
    assert p1["subject"]["DSGT"] == "Discreate Structures & Graph Theory"
    assert p1["subject"]["COA"] == "Computer Organization & Architecture"
    p10 = result.sections[9].legend               # separate legend table + merged duplicate cell
    assert set(p10["faculty"]) == {"SND", "PJB", "KKD", "FM", "AVN", "PG", "SV", "KS"}
    assert p10["subject"]["PE I - FDS"].startswith("Program Elective I")


def test_legend_rows_are_not_parsed_as_classes(result):
    assert not [e for e in result.entries if "Dr." in (e.raw_text or "") or "Faculties" in (e.raw_text or "")]


def test_plain_and_stacked_lab_cells(result):
    dbms = _find(result, 1, 1, time(10), "DBMS")
    assert len(dbms) == 1
    e = dbms[0]
    assert (e.batch_label, e.staff_label, e.room_label, e.end_time) == ("SE-A", "KKD", "508", time(11))
    assert e.verification_status == "VERIFIED"
    labs = [e for e in result.entries if e.page == 1 and e.day_of_week == 3 and e.start_time == time(9)]
    assert {(e.batch_label, e.staff_label, e.room_label) for e in labs} == {
        ("SE-A1", "AVN", "604"), ("SE-A2", "JS", "607-B"), ("SE-A4", "AAG", "608")}
    assert all(e.end_time == time(11) for e in labs)          # two-hour merged cell


def test_noon_row_labelled_am_is_read_as_midday_with_a_visible_note(result):
    e = _find(result, 1, 1, time(12, 15), "DS")[0]
    assert e.end_time == time(13, 15) and not e.time_uncertain
    assert e.has_code("NOON_AM_MARKER_CORRECTED") and "12.15 a.m." in e.time_label_raw
    assert e.verification_status == "VERIFIED"
    # Page 3 also writes "11.15 a.m. to 12.15 a.m." — same rule on the end time.
    p3 = _find(result, 3, 3, time(11, 15), "DSGT")[0]
    assert p3.end_time == time(12, 15) and not p3.time_uncertain
    assert not any(e.has_code("TIME_LABEL_INCONSISTENT") for e in result.entries)


def test_open_electives_are_parallel_options_not_clashes(result):
    opts = [e for e in result.entries if e.page == 1 and e.day_of_week == 3 and e.start_time == time(14, 15)]
    assert {e.course_label for e in opts} == {"FOSE", "F-IoT", "DBMS"}
    assert all(e.has_code("PARALLEL_OPTION") for e in opts)
    assert not any(e.has_code("POSSIBLE_BATCH_OVERLAP") for e in opts)
    assert "Open Elective" in opts[0].course_name


def test_cell_time_inside_merged_span_is_used(result):
    e = _find(result, 9, 3, time(10), "PE III-TSDA (Batch1)")[0]
    assert e.end_time == time(11) and e.has_code("TIME_FROM_CELL_WITHIN_SPAN")
    # A cell that writes its own full time is more specific than the row it is drawn in.
    llm = _find(result, 9, 3, time(10), "PE III- LLM")[0]
    assert llm.end_time == time(12) and llm.has_code("TIME_FROM_CELL_OVERRIDES_ROW") and not llm.time_uncertain
    c3 = _find(result, 3, 5, time(14, 15), "Data Sci.Lab", "SE-C3")[0]
    assert c3.end_time == time(16, 15) and c3.has_code("SUBGROUP_DURING_DIVISION_CLASS")
    assert not any(e.has_code("POSSIBLE_BATCH_OVERLAP") or e.has_code("EXPLICIT_TIME_CONFLICT") for e in result.entries)


def test_combined_division_page_keeps_combined_scope(result):
    be = [e for e in result.entries if e.page == 9 and e.entry_kind == "CLASS"]
    assert be and all(e.batch_label == "BE-A/B/C/D" for e in be)


def test_wrapped_and_grouped_tokens(result):
    batch = _find(result, 9, 4, time(15, 15), "PE IV- DMBI Lab (Batch D)")
    assert batch and batch[0].room_label == "703-A" and batch[0].staff_label == "NR"
    multi_room = [e for e in result.entries if e.page == 4 and e.room_label == "703-A&B"]
    assert multi_room and multi_room[0].staff_label == "SB+AK"
    hss = [e for e in result.entries if e.page == 10 and e.course_label == "HSS" and e.room_label == "609"]
    assert hss


def test_slots_without_faculty_or_room_are_valid(result):
    llc = _find(result, 1, 1, time(9), "LLC")[0]                # "LLC ()" — deliberately blank
    assert llc.staff_label is None and llc.room_label is None and llc.has_code("DETAILS_NOT_GIVEN")
    assert llc.verification_status == "VERIFIED"
    mdm = _find(result, 5, 5, time(9), "MDM Lab")[0]
    assert mdm.verification_status == "VERIFIED"
    hss = _find(result, 10, 1, time(13, 15), "HSS")[0]          # "HSS(609)": course + room only
    assert hss.room_label == "609" and hss.verification_status == "VERIFIED"


def test_only_remaining_gap_is_the_unlabelled_mtech_row(result):
    flagged = [e for e in result.entries
               if any(m["severity"] in ("WARNING", "CRITICAL") for m in e.messages)]
    assert [(e.page, e.course_label, e.room_label) for e in flagged] == [(10, "HSS", "305")]
    assert flagged[0].start_time is None and flagged[0].verification_status == "INCOMPLETE"


def test_codes_missing_from_legends_are_kept_as_written(result):
    la = _find(result, 1, 2, time(16, 15), "LA M1")[0]
    assert la.course_name is None and la.has_code("COURSE_ABBREVIATION_UNKNOWN")
    assert la.verification_status == "VERIFIED"


def test_real_pdf_end_to_end_upload_persist_activate(client, f):
    """The real file through the API, the worker and the database (institutional domain)."""
    from app.enums import RoleCode
    from tests.helpers import upload_and_process

    dept, year = f.dept(), f.year()
    admin, _ = f.staff(RoleCode.ADMIN, dept=dept)
    ah = f.auth(admin)
    tt = upload_and_process(client, ah, str(PDF), "INSTITUTIONAL", academic_year_id=year.academic_year_id)
    assert tt["processing_status"] == "NEEDS_REVIEW"
    r = client.post(f"/api/v1/timetables/{tt['timetable_id']}/make-primary", params={"domain": "INSTITUTIONAL"}, headers=ah)
    assert r.status_code == 200
