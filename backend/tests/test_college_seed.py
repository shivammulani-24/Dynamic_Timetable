"""End to end on the college's real timetable: dev seed from the PDF (master data, accounts,
upload → worker → activation), then the API as students, faculty, HOD and Admin would use it.
Clock frozen at Tuesday 2026-10-13 10:30 Asia/Kolkata.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.context import Clock
from tests.conftest import truncate_all
from tests.test_reference_pdf import PDF

SHARED_DB = True
NOW = datetime(2026, 10, 13, 10, 30, tzinfo=ZoneInfo("Asia/Kolkata"))  # Tuesday
TOKENS: dict[str, dict] = {}


@pytest.fixture(scope="module")
def college():
    from app.seed_college import seed

    Clock.freeze(None)
    truncate_all()
    TOKENS.clear()
    info = seed(str(PDF))
    yield info
    truncate_all()


@pytest.fixture(autouse=True)
def frozen(college):
    Clock.freeze(NOW)
    yield
    Clock.freeze(NOW)


def H(client, who: str) -> dict:
    if who not in TOKENS:
        r = client.post("/api/v1/auth/login", json={"email": f"{who}@demo.college.edu", "password": "Demo@12345"})
        assert r.status_code == 200, r.text
        TOKENS[who] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return TOKENS[who]


def ask(client, who, query, *, ok=True, **kw):
    r = client.post("/api/v1/search", headers=H(client, who), json={"query": query, "domain": "INSTITUTIONAL", **kw})
    if ok:
        assert r.status_code == 200, r.text
    return r.json()


def test_seed_loads_every_class(college):
    assert college["counts"] == {"VERIFIED": 452, "INCOMPLETE": 1}


def test_only_the_two_clashes_printed_in_the_pdf_are_reported(client, college):
    r = client.get(f"/api/v1/timetables/{college['timetable_id']}/conflicts", headers=H(client, "admin"))
    assert r.status_code == 200
    found = sorted((c["type"], c["resource"], c["entries"][0]["day_of_week"]) for c in r.json()["conflicts"])
    assert found == [("PROFESSOR_OVERLAP", "Prof. Sushama Pande", 5), ("ROOM_OVERLAP", "603-2", 2)]


def test_student_week_view_with_lab_group(client):
    j = ask(client, "student.se.a1", "What are my classes on Wednesday?")
    assert j["status"] == "OK", j
    rows = {(x["start_time"], x["course"], x["batch"]) for x in j["results"]}
    assert ("09:00", "Data Structures (Lab)", "SE-A1") in rows, rows
    assert not any(b == "SE-A2" for _, _, b in rows)          # another lab group's lab is not hers


def test_llc_shows_course_without_room_or_teacher(client):
    j = ask(client, "student.se.a1", "What are my classes on Monday?")
    llc = next(x for x in j["results"] if x["start_time"] == "09:00")
    assert llc["course"] and llc["professor"] is None and llc["room"] is None
    assert llc["verification_status"] == "VERIFIED"


def test_noon_row_is_a_normal_class(client):
    j = ask(client, "student.se.a1", "What are my classes on Monday?")
    noon = next(x for x in j["results"] if x["start_time"] == "12:15")
    assert noon["end_time"] == "13:15" and noon["verification_status"] == "VERIFIED"


def test_be_students_see_the_combined_be_page(client):
    for who in ("student.be.a", "student.be.c"):
        j = ask(client, who, "What are my classes on Tuesday?")
        assert j["status"] == "OK" and len(j["results"]) >= 10, (who, j.get("message"))
        assert {x["batch"] for x in j["results"]} == {"BE"}


def test_lunch_differs_by_year(client):
    se = ask(client, "student.se.a1", "Do I have classes after lunch?")
    te = ask(client, "student.te.a1", "Do I have classes after lunch?")
    assert (se["meta"]["boundary"], se["meta"]["boundary_source"]) == ("14:15", "TIMETABLE")   # SE: 1:15–2:15
    assert (te["meta"]["boundary"], te["meta"]["boundary_source"]) == ("13:15", "TIMETABLE")   # TE: 12:15–1:15


def test_now_and_next(client):
    j = ask(client, "student.se.a1", "What is my next class?")
    assert j["status"] == "OK" and j["results"], j
    assert j["results"][0]["start_time"] >= "10:30"


def test_professor_and_hod_schedules(client):
    j = ask(client, "kkd", "What is my schedule today?")
    assert j["status"] == "OK" and j["results"]
    assert all(x["professor"] and "Devadkar" in x["professor"] for x in j["results"])
    hod = client.get("/api/v1/me", headers=H(client, "snd")).json()
    assert {"HOD", "PROFESSOR"} <= set(hod["roles"])


def test_free_room_and_unknown_legend_code(client):
    j = ask(client, "admin", "Is room 508 free at 10 am today?")
    assert j["status"] == "OK"
    la = ask(client, "student.se.a1", "Find all LA M1 classes")
    assert la["status"] in ("OK", "CLARIFICATION_REQUIRED")


def test_newbie_without_batch_gets_setup_message(client):
    j = ask(client, "student.newbie", "What is my next class?", ok=False)
    assert (j.get("clarification") or {}).get("kind") == "SETUP_REQUIRED"


def test_review_notice_is_for_the_admin_only(client):
    student = ask(client, "student.se.a1", "What are my classes on Monday?")
    assert not any(w["code"] == "TIMETABLE_NEEDS_REVIEW" for w in student["warnings"])
    admin = ask(client, "admin", "Find all DBMS classes")
    assert any(w["code"] == "TIMETABLE_NEEDS_REVIEW" for w in admin["warnings"])


def test_free_room_answer_has_no_disclaimer_banner(client):
    j = ask(client, "student.se.a1", "Which rooms are free now?")
    assert j["status"] == "OK" and not any(w["code"] == "FREE_MEANS_UNSCHEDULED" for w in j["warnings"])


def test_choosing_the_official_timetable_is_not_archive_browsing(client, college):
    h = H(client, "student.se.a2")
    tid = str(college["timetable_id"])
    r = client.put("/api/v1/me/selection", headers=h, json={"domain": "INSTITUTIONAL", "timetable_id": tid})
    assert r.status_code == 200 and r.json()["timetable_id"] is None      # nothing remembered
    ctx = client.get("/api/v1/timetable-context", params={"domain": "INSTITUTIONAL"}, headers=h).json()
    assert ctx["current"]["selection_type"] == "PRIMARY"


def test_faculty_missing_from_legends_shown_by_code(client):
    j = ask(client, "student.te.a1", "What are my classes on Monday?")
    assert not any("legend" in (x["professor"] or "") for x in j["results"])


# ---------------------------------------------------------------- composed query plans (Q31 / QT23)

def _slots(items):
    return {(i.get("date") or i["day_of_week"], i["start_time"], i["end_time"]) for i in items}


def test_composed_count_labs_this_week(client):
    j = ask(client, "student.te.b4", "How many labs do I have this week?")
    assert j["intent"] == "COMPOSED_QUERY" and j["intent_id"] == "Q31" and j["result_type"] == "AGGREGATE", j
    agg = j["results"][0]
    assert agg["metric"] == "COUNT" and agg["value"] == len(_slots(agg["entries"])) > 0
    assert all("lab" in f"{e['course']} {e['course_code']}".lower() for e in agg["entries"])
    assert j["meta"]["plan"] == {"operation": "COUNT", "composed": True, "kind": "LAB", "filters": {"self": True},
                                 "when": {"week": "this"}}


def test_composed_last_class_matches_the_day_listing(client):
    day = ask(client, "student.te.b4", "What are my classes on Friday?")["results"]
    j = ask(client, "student.te.b4", "When is my last class on Friday?")
    assert j["status"] == "OK" and j["intent"] == "COMPOSED_QUERY"
    assert j["results"][0]["end_time"] == max(x["end_time"] for x in day if x["end_time"])
    first = ask(client, "student.te.b4", "When is my first class on Friday?")
    assert first["results"][0]["start_time"] == min(x["start_time"] for x in day if x["start_time"])


def test_composed_busiest_day_is_sorted(client):
    j = ask(client, "student.te.b4", "Which day is my busiest?")
    assert j["result_type"] == "DAY_SUMMARY"
    counts = [d["classes"] for d in j["results"]]
    assert counts == sorted(counts, reverse=True) and j["message"].startswith(f"Busiest day: {j['results'][0]['day']}")
    fin = ask(client, "student.te.b4", "Which day do I finish earliest?")
    ends = [d["last_end"] for d in fin["results"]]
    assert fin["meta"]["plan"]["metric"] == "LAST_END" and ends == sorted(ends)


def test_composed_lab_filter_keeps_the_lab_group_scope(client):
    j = ask(client, "student.se.a1", "Show my labs")
    assert j["intent"] == "COMPOSED_QUERY" and j["results"]
    assert all("lab" in f"{e['course']} {e['course_code']}".lower() for e in j["results"])
    assert not any(e["batch"] in ("SE-A2", "SE-A3", "SE-A4", "SE-B1", "SE-C1") for e in j["results"])
    other = ask(client, "student.se.a1", "Show SE-B labs on Monday", ok=False)
    assert not any((e.get("batch") or "").startswith("SE-B") for e in other.get("results", []))


def test_composed_exists_and_counting_other_things(client):
    sat = ask(client, "student.te.b4", "Do I have any lab on Saturday?")
    assert sat["status"] == "NO_MATCH" and sat["message"].startswith("No")
    profs = ask(client, "student.se.a1", "Which professors teach my batch?")["results"]
    n = ask(client, "student.se.a1", "How many professors teach my batch?")
    assert n["result_type"] == "AGGREGATE" and n["results"][0]["value"] == len(profs)
    subj = ask(client, "student.te.b4", "How many subjects do I have?")
    assert subj["results"][0]["value"] == len(subj["results"][0]["labels"]) > 0


def test_composed_clarifies_instead_of_guessing_and_treats_text_as_data(client):
    j = ask(client, "student.te.b4", "Do I have classes before 11 on Tuesday?", ok=False)
    assert j["status"] == "CLARIFICATION_REQUIRED" and j["clarification"]["kind"] == "AMPM"
    j2 = ask(client, "student.te.b4", "Do I have classes before 11 on Tuesday?", parameters={"time": "11:00"})
    assert j2["status"] == "OK" and all(x["start_time"] < "11:00" for x in j2["results"])
    inj = ask(client, "student.te.b4", "How many labs'; DROP TABLE institutional_timetable_entry; --")
    assert inj["status"] == "OK"
    assert ask(client, "student.te.b4", "How many labs do I have this week?")["results"][0]["value"] > 0


def test_specialised_questions_keep_their_operations(client):
    for who, q, intent in (("student.se.a1", "What is my next class?", "NEXT_CLASS"),
                           ("student.se.a1", "Find all DBMS classes", "FIND_COURSE_CLASSES"),
                           ("student.se.a1", "How long until my next class?", "TIME_UNTIL_NEXT_CLASS"),
                           ("admin", "Which rooms are free now?", "FIND_FREE_ROOMS")):
        j = ask(client, who, q)
        assert j["intent"] == intent and j["meta"]["plan"]["composed"] is False, (q, j["intent"])


# ---------------------------------------------------------------- names as people say them

def test_teacher_found_by_code_full_name_first_name_surname_or_sir(client):
    want = None
    for q in ("Where is AVN on Wednesday at 9 am?", "Where is Dr. Anant Nimkar on Wednesday at 9 am?",
              "Where is Anant on Wednesday at 9 am?", "Where is Nimkar sir on Wednesday at 9 am?"):
        j = ask(client, "student.se.a1", q)
        assert j["intent"] == "PROFESSOR_SCHEDULED_LOCATION" and j["status"] == "OK", (q, j["message"])
        got = (j["results"][0]["professor"], j["results"][0]["room"])
        want = want or got
        assert got == want == ("Dr. Anant Nimkar", "604"), (q, got)
    sched = ask(client, "student.se.a1", "Show Nimkar's schedule")
    assert sched["intent"] == "PROFESSOR_SCHEDULE" and sched["results"]
    assert {x["professor"] for x in sched["results"]} == {"Dr. Anant Nimkar"}


def test_shared_surname_asks_which_teacher_once_per_person(client):
    j = ask(client, "student.se.a1", "Is Sawant free at 2 pm on Monday?", ok=False)
    assert j["status"] == "CLARIFICATION_REQUIRED" and j["clarification"]["kind"] == "ENTITY_CHOICE"
    labels = [c["label"] for c in j["clarification"]["choices"]]
    assert len(labels) == 3 and sum("Rupali" in x for x in labels) == 1, labels


def test_one_teacher_spelled_two_ways_in_the_pdf_is_one_person(client):
    full = ask(client, "admin", "Show Sushama Pande's schedule")
    surname = ask(client, "admin", "Show Pande's schedule")
    code = ask(client, "admin", "Show SP's schedule")
    ids = [{x["entry_id"] for x in r["results"]} for r in (full, surname, code)]
    assert ids[0] == ids[1] == ids[2] and len(ids[0]) >= 4
    assert ask(client, "student.se.a1", "When is Pande ma'am free on Friday?")["status"] == "OK"


def test_subject_found_by_part_of_its_name_or_a_small_typo(client):
    full = {x["entry_id"] for x in ask(client, "student.se.a1", "Find all DBMS classes")["results"]}
    assert {x["entry_id"] for x in ask(client, "student.se.a1", "Find all database classes")["results"]} == full
    coa = ask(client, "student.se.a1", "Show Computer Organization classes")
    assert coa["intent"] == "FIND_COURSE_CLASSES" and all("Computer Organization" in x["course"] for x in coa["results"])
    n = ask(client, "student.se.a1", "How many discrete structures classes do I have?")   # PDF spells it "Discreate"
    listed = ask(client, "student.se.a1", "Find all discreate structures classes")["results"]
    assert n["results"][0]["value"] == len(_slots(listed)) == 3


def test_lab_group_timetable_includes_its_division_lectures(client):
    j = ask(client, "admin", "Show TE-B4 timetable on Monday")
    batches = {x["batch"] for x in j["results"]}
    assert j["status"] == "OK" and "TE-B" in batches and batches <= {"TE-B", "TE-B4"}, batches
    student = {x["entry_id"] for x in ask(client, "student.te.b4", "What are my classes on Monday?")["results"]}
    assert {x["entry_id"] for x in j["results"]} == student          # same view as the TE-B4 student's own


def test_we_us_our_mean_me_and_professor_questions_by_day_or_batch(client):
    j = ask(client, "student.te.b4", "Which professors teach us?")
    assert j["intent"] == "PROFESSORS_FOR_BATCH" and j["results"]
    day = ask(client, "student.te.b4", "What is Bhavathankar sir teaching on Monday?")
    assert day["intent"] == "PROFESSOR_SCHEDULE" and all(x["day_of_week"] == 1 for x in day["results"])
    taught = ask(client, "kkd", "Which batches do I teach?")
    agg = taught["results"][0]
    assert taught["result_type"] == "AGGREGATE" and agg["unit"] == "batches" and "SE-A" in agg["labels"]
