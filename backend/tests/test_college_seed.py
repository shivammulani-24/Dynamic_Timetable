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
