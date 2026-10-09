"""Query engine: every registered intent Q01–Q30, templates QT01–QT22, clarification, scope and isolation.

World: the dev seed (synthetic CE timetable activated as the institutional default; Alice has a
personal primary). Clock frozen at Monday 2026-10-12 09:30 Asia/Kolkata.
"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.db import session_factory
from app.models import InstitutionalTimetableEntry, UserAccount
from app.services.context import Clock
from tests.conftest import truncate_all

SHARED_DB = True
NOW = datetime(2026, 10, 12, 9, 30, tzinfo=ZoneInfo("Asia/Kolkata"))  # Monday


@pytest.fixture(scope="module")
def world():
    from app.seed import seed_master, seed_timetables

    Clock.freeze(None)
    truncate_all()
    with session_factory()() as db:
        info = seed_master(db)
        seed_timetables(db, info)
    yield info
    truncate_all()


@pytest.fixture(autouse=True)
def frozen(world):
    Clock.freeze(NOW)
    yield
    Clock.freeze(NOW)


TOKENS: dict[str, dict] = {}


def H(client, who: str) -> dict:
    if who not in TOKENS:
        r = client.post("/api/v1/auth/login", json={"email": f"{who}@demo.college.edu", "password": "Demo@12345"})
        assert r.status_code == 200, r.text
        TOKENS[who] = {"Authorization": f"Bearer {r.json()['access_token']}"}
    return TOKENS[who]


def ask(client, who, query=None, domain="INSTITUTIONAL", **kw):
    body = {"query": query, "domain": domain, **kw}
    r = client.post("/api/v1/search", headers=H(client, who), json=body)
    j = r.json()
    j["_http"] = r.status_code
    return j


def courses(j):
    return [(x.get("day_name") or x.get("date"), x["start_time"], x["course"], x["batch"]) for x in j["results"]]


# ------------------------------------------------------------------ Q01–Q05 browsing


def test_q01_my_timetable_defaults_to_today_and_student_scope(client):
    j = ask(client, "alice", "Show my timetable")
    assert j["intent_id"] == "Q01" and j["status"] in ("OK", "DATA_UNVERIFIED")
    assert j["context"]["domain"] == "INSTITUTIONAL" and j["context"]["selection_type"] == "PRIMARY"
    batches = {x["batch"] for x in j["results"]}
    assert batches <= {"SE-A", "SE-A1"}, batches  # own division + own lab group only
    assert all(x["date"] == "2026-10-12" for x in j["results"])
    assert ("Monday", "09:00", "Database Management Systems", "SE-A") in courses(j) or any(c[1] == "09:00" for c in courses(j))


def test_q02_weekday_view_recurring(client):
    j = ask(client, "alice", "Show Wednesday's timetable")
    assert j["intent"] == "SHOW_DAY_TIMETABLE" and j["results"]
    assert all(x["day_of_week"] == 3 for x in j["results"]) and j["meta"]["recurring_view"]


def test_q02_missing_day_structured_asks(client):
    j = ask(client, "alice", intent="SHOW_DAY_TIMETABLE")
    assert j["status"] == "CLARIFICATION_REQUIRED" and j["clarification"]["parameter"] == "day_of_week"


def test_q03_tomorrow_uses_user_timezone(client):
    j = ask(client, "alice", "What classes do I have tomorrow?")
    assert j["intent_id"] == "Q03" and {x["date"] for x in j["results"]} == {"2026-10-13"}
    assert j["context"]["timezone"] == "Asia/Kolkata"


def test_q03_ambiguous_numeric_date_asks(client):
    j = ask(client, "alice", "Show classes on 5/6")
    assert j["status"] == "CLARIFICATION_REQUIRED" and j["clarification"]["kind"] == "DATE"


def test_q04_week_uses_configured_week_start(client):
    j = ask(client, "alice", "Show my timetable for this week")
    assert j["intent_id"] == "Q04"
    assert {x["date"] for x in j["results"]} <= {f"2026-10-{d}" for d in range(12, 19)}
    assert {x["day_of_week"] for x in j["results"]} >= {1, 2, 3, 4, 5}


def test_q04_without_week_start_config_asks(client, db):
    from app.models import InstitutionConfig

    cfg = db.get(InstitutionConfig, 1)
    cfg.week_start_day = None
    db.commit()
    try:
        j = ask(client, "alice", "Show my timetable for this week")
        assert j["status"] == "CLARIFICATION_REQUIRED" and j["clarification"]["kind"] == "DATE_RANGE"
        assert len(j["clarification"]["choices"]) == 2
        choice = j["clarification"]["choices"][0]["value"]
        j2 = ask(client, "alice", "Show my timetable for this week", parameters=choice)
        assert j2["intent_id"] == "Q04" and j2["results"]
    finally:
        cfg.week_start_day = 1
        db.commit()


def test_q04_range_limit(client):
    j = ask(client, "alice", "Show my timetable", intent="SHOW_WEEK_TIMETABLE",
            parameters={"start_date": "2026-10-01", "end_date": "2026-12-31"})
    assert j["status"] == "INVALID_REQUEST"


def test_q05_batch_timetable_and_scope(client):
    j = ask(client, "kkd", "Show SE-C timetable on Tuesday")
    assert j["intent_id"] == "Q05" and j["results"] and {x["batch"] for x in j["results"]} == {"SE-C"}
    # A student cannot read another batch's timetable: honest NO_MATCH, never broadened.
    j = ask(client, "alice", "Show SE-C timetable on Tuesday")
    assert j["status"] == "NO_MATCH" and j["results"] == []


# ------------------------------------------------------------------ Q06–Q08


def test_q06_course_and_session_variants(client):
    j = ask(client, "alice", "Find all DBMS classes")
    assert j["intent_id"] == "Q06" and len(j["results"]) >= 4
    assert {x["course"] for x in j["results"]} == {"Database Management Systems"}
    lab = ask(client, "alice", "Find all DS classes")
    assert {"Data Structures", "Data Structures (Lab)"} <= {x["course"] for x in lab["results"]}


def test_q06_unknown_course_no_match_no_fallback(client):
    j = ask(client, "alice", "Find all classes of course XYZQ", intent="FIND_COURSE_CLASSES", parameters={"course": "XYZQ"})
    assert j["status"] == "NO_MATCH" and "selected timetable" in j["message"]


def test_q07_time_range(client):
    j = ask(client, "alice", "Show classes between 10 and 12 tomorrow")
    assert j["intent_id"] == "Q07"
    for x in j["results"]:
        assert x["start_time"] < "12:00" and x["end_time"] > "10:00"


def test_q07_needs_date(client):
    j = ask(client, "alice", "Show my classes between 10 am and 12 pm")
    assert j["status"] == "CLARIFICATION_REQUIRED" and j["clarification"]["kind"] == "DATE"
    j2 = ask(client, "alice", "Show my classes between 10 am and 12 pm", parameters={"date": "2026-10-13"})
    assert j2["intent_id"] == "Q07" and j2["status"] in ("OK", "DATA_UNVERIFIED")


def test_q08_details_by_entry_and_by_fields(client):
    today = ask(client, "alice", "Show my timetable")["results"]
    eid = today[0]["entry_id"]
    j = ask(client, "alice", "Show details of this class", parameters={"entry_id": eid})
    assert j["intent_id"] == "Q08" and j["results"][0]["entry_id"] == eid and "raw_text" in j["results"][0]
    vague = ask(client, "alice", "Show details of this class")
    assert vague["status"] == "CLARIFICATION_REQUIRED" and vague["clarification"]["parameter"] == "entry_id"


def test_q08_entry_from_other_scope_not_found(client, db):
    other = db.scalar(select(InstitutionalTimetableEntry).where(InstitutionalTimetableEntry.batch_label_raw == "SE-C"))
    j = ask(client, "alice", "details", intent="SHOW_CLASS_DETAILS", parameters={"entry_id": str(other.entry_id)})
    assert j["status"] == "NO_MATCH"


# ------------------------------------------------------------------ Q09–Q14 current / next / remaining


def test_q09_current_class(client):
    j = ask(client, "alice", "What class is happening now?")
    assert j["intent_id"] == "Q09" and j["status"] == "OK"
    assert courses(j) == [("Monday", "09:00", "Database Management Systems", "SE-A")]
    assert j["results"][0]["status"] == "IN_PROGRESS"


def test_q10_next_class_respects_lab_group(client):
    j = ask(client, "alice", "What is my next class?")
    assert j["intent_id"] == "Q10"
    assert [(x["start_time"], x["batch"], x["room"]) for x in j["results"]] == [("10:00", "SE-A1", "604")]
    assert j["meta"]["minutes_until"] == 30


def test_q10_crosses_days_within_lookahead(client):
    Clock.freeze(datetime(2026, 10, 16, 18, 0, tzinfo=ZoneInfo("Asia/Kolkata")))  # Friday evening
    j = ask(client, "alice", "What is my next class?")
    assert j["results"] and j["results"][0]["date"] == "2026-10-19"  # next Monday


def test_q11_after_lunch_and_unconfigured(client, db):
    j = ask(client, "alice", "Do I have classes after lunch?")
    assert j["intent_id"] == "Q11" and j["meta"]["boundary"] == "14:00"
    from app.models import InstitutionConfig

    cfg = db.get(InstitutionConfig, 1)
    cfg.lunch_boundary = None
    db.commit()
    try:
        j = ask(client, "alice", "Do I have classes after lunch?")
        assert j["status"] == "CLARIFICATION_REQUIRED" and j["clarification"]["kind"] == "CONFIGURATION"  # T14
        j2 = ask(client, "alice", "Do I have classes after lunch?", parameters={"lunch_time": "13:00"})
        assert j2["intent_id"] == "Q11" and j2["meta"]["boundary"] == "13:00"
    finally:
        cfg.lunch_boundary = time(14, 0)
        db.commit()


def test_q12_time_until_next(client):
    j = ask(client, "alice", "How long until my next class?")
    assert j["intent_id"] == "Q12" and "30 min" in j["message"]


def test_q13_ampm_and_date_clarification(client):
    j = ask(client, "alice", "Am I free at 2?")
    assert j["status"] == "CLARIFICATION_REQUIRED" and j["clarification"]["kind"] == "AMPM"  # API-11 / T13
    j = ask(client, "alice", "Am I free at 2 pm?")
    assert j["status"] == "CLARIFICATION_REQUIRED" and j["clarification"]["kind"] == "DATE"
    j = ask(client, "alice", "Am I free at 9:30 am today?")
    assert j["intent_id"] == "Q13" and j["results"][0]["schedule_status"] == "SCHEDULED"
    j = ask(client, "alice", "Am I free at 4:30 pm today?")
    assert j["results"][0]["free"] is True and any(w["code"] == "FREE_MEANS_UNSCHEDULED" for w in j["warnings"])


def test_q14_remaining_today(client):
    j = ask(client, "alice", "Do I have any classes left today?")
    assert j["intent_id"] == "Q14"
    assert all(x["end_time"] > "09:30" for x in j["results"])
    assert any(x["status"] == "IN_PROGRESS" for x in j["results"])
    assert any(w["code"] == "UNCERTAIN_TIME_EXCLUDED" for w in j["warnings"])  # 12:15 row excluded


# ------------------------------------------------------------------ Q15–Q19 professors


def test_q15_professor_schedule_and_scope(client):
    admin = ask(client, "admin", "Show Professor Shah's schedule")
    assert admin["intent_id"] == "Q15" and len(admin["results"]) >= 10
    student = ask(client, "alice", "Show Professor Shah's schedule")
    assert student["results"] and {x["batch"] for x in student["results"]} <= {"SE-A", "SE-A1"}


def test_q15_ambiguous_professor_asks_choice(client):
    j = ask(client, "admin", "Show Prof. Dessai schedule")  # typo → suggestions, never auto-picked
    assert j["status"] == "CLARIFICATION_REQUIRED" and j["clarification"]["kind"] == "ENTITY_CHOICE"
    key = j["clarification"]["choices"][0]["value"]["professor"]
    j2 = ask(client, "admin", "Show Prof. Dessai schedule", parameters={"professor": key})
    assert j2["intent_id"] == "Q15" and j2["results"]


def test_q16_scheduled_location_wording(client):
    j = ask(client, "alice", "Where is Prof Nair now?")
    assert j["intent_id"] == "Q16" and "not real-time tracking" in j["message"]


def test_q17_professor_courses(client):
    j = ask(client, "admin", "Which course does Prof Bhatt teach?")
    assert j["intent_id"] == "Q17" and j["result_type"] == "COURSES"
    assert "Data Structures" in {x["course"] for x in j["results"]}


def test_q18_free_time_requires_working_hours(client, db):
    j = ask(client, "alice", "When is Professor Desai free tomorrow?")
    assert j["intent_id"] == "Q18" and j["result_type"] == "FREE_INTERVALS" and j["results"]
    from app.models import InstitutionConfig

    cfg = db.get(InstitutionConfig, 1)
    old = (cfg.working_hours_start, cfg.working_hours_end)
    cfg.working_hours_start = cfg.working_hours_end = None
    db.commit()
    try:
        j = ask(client, "alice", "When is Professor Desai free tomorrow?")
        assert j["status"] == "UNSUPPORTED_INTENT" and j["details"]["reason"] == "WORKING_HOURS_NOT_CONFIGURED"  # API-12
    finally:
        cfg.working_hours_start, cfg.working_hours_end = old
        db.commit()


def test_q18_personal_unsupported(client):
    j = ask(client, "alice", "When is Professor Desai free tomorrow?", domain="PERSONAL")
    assert j["status"] == "UNSUPPORTED_INTENT"


def test_q19_professors_for_batch(client):
    j = ask(client, "kkd", "Which professors teach SE-A?")
    assert j["intent_id"] == "Q19" and len(j["results"]) == 4


# ------------------------------------------------------------------ Q20–Q25 rooms / floors


def test_q20_room_schedule_disclaimer(client):
    j = ask(client, "alice", "Show room 508 schedule")
    assert j["intent_id"] == "Q20" and j["results"] and "occupancy" in j["meta"]["disclaimer"]


def test_q21_room_free_now_and_at_time(client):
    j = ask(client, "alice", "Is room 508 free now?")
    assert j["intent_id"] == "Q21" and j["results"][0]["scheduled_status"] == "SCHEDULED"
    j = ask(client, "alice", "Is room 508 free at 2 PM?")
    assert j["status"] == "CLARIFICATION_REQUIRED" and j["clarification"]["kind"] == "DATE"
    j = ask(client, "alice", "Is room 508 free at 4:30 PM today?")
    assert j["results"][0]["scheduled_status"] == "NO_SCHEDULED_CLASS"


def test_q21_unverified_room_not_claimed_free(client):
    # 702-B has a Monday 12:15 class whose time label is inconsistent (uncertain).
    j = ask(client, "alice", "Is room 702-B free at 12:30 pm today?")
    assert j["results"][0]["scheduled_status"] == "UNCERTAIN"  # PDF-16 / API-14
    assert any(w["code"] == "ROOM_HAS_UNCERTAIN_ENTRIES" for w in j["warnings"])


def test_q22_free_rooms_with_floor(client):
    j = ask(client, "admin", "Which rooms are free now on the 6th floor?")
    assert j["intent_id"] == "Q22" and {x["room"] for x in j["results"]} <= {"604", "605", "606-4", "607"}
    j = ask(client, "admin", "Which rooms are free at 2 pm?")
    assert j["status"] == "CLARIFICATION_REQUIRED"


def test_q22_incomplete_inventory_flagged(client, db):
    from app.models import Room

    r = db.scalar(select(Room).where(Room.room_code == "510"))
    r.floor_label = None
    db.commit()
    try:
        j = ask(client, "admin", "Which rooms are free now on the 5th floor?")
        assert any(w["code"] == "FLOOR_MAPPING_INCOMPLETE" for w in j["warnings"])  # API-13
    finally:
        r.floor_label = "5"
        db.commit()


def test_q23_floor_activity_role_restricted(client):
    assert ask(client, "alice", "What is happening on the 5th floor?")["status"] == "ACCESS_DENIED"
    j = ask(client, "principal", "What is happening on the 5th floor?")
    assert j["intent_id"] == "Q23" and j["results"] and all(x["floor"] == "5" for x in j["results"])


def test_q24_room_for_day(client):
    j = ask(client, "alice", "Show room 702-B schedule for Friday")
    assert j["intent_id"] == "Q24" and all(x["day_of_week"] == 5 for x in j["results"])


def test_q25_rooms_after_time(client):
    j = ask(client, "kkd", "Which rooms have classes after 2 pm today?")
    assert j["intent_id"] == "Q25" and j["result_type"] == "ROOMS"
    assert all(x["first_start"] >= "14:00" for x in j["results"])


# ------------------------------------------------------------------ Q26–Q30 archives / primary / cross-domain


def test_q26_requires_selected_archive_then_searches_only_it(client, db):
    j = ask(client, "admin", "Search this archived timetable for DBMS")
    assert j["status"] == "CLARIFICATION_REQUIRED" and j["clarification"]["kind"] == "SELECT_ARCHIVE"
    sel = j["clarification"]["choices"][0]["value"]["selection"]
    j2 = ask(client, "admin", "Search this archived timetable for DBMS", selection=sel)
    assert j2["intent"] == "SEARCH_SELECTED_ARCHIVE" and j2["meta"]["inner_intent"] == "FIND_COURSE_CLASSES"
    assert j2["context"]["selection_type"] == "EXPLICIT_ARCHIVE" and j2["context"]["timetable_id"] == sel["timetable_id"]


def test_q27_primary_per_domain(client):
    i = ask(client, "alice", "Which timetable is currently primary?")
    p = ask(client, "alice", "Which timetable is currently primary?", domain="PERSONAL")
    assert i["intent_id"] == p["intent_id"] == "Q27"
    assert i["results"][0]["domain"] == "INSTITUTIONAL" and p["results"][0]["domain"] == "PERSONAL"
    assert i["results"][0]["timetable_id"] != p["results"][0]["timetable_id"]


def test_q28_make_primary_needs_confirmation_and_authority(client):
    assert ask(client, "alice", "Make this timetable primary")["status"] == "ACCESS_DENIED"  # institutional
    j = ask(client, "admin", "Make this timetable my primary", domain="PERSONAL")
    assert j["status"] == "CLARIFICATION_REQUIRED"  # admin has no personal archives → asks which (none)
    pers = ask(client, "alice", "Show my archives", domain="PERSONAL")["results"][0]["timetable_id"]
    j = ask(client, "alice", "Make this timetable my primary", domain="PERSONAL", parameters={"timetable_id": pers})
    assert j["status"] == "CLARIFICATION_REQUIRED" and j["clarification"]["kind"] == "CONFIRMATION"
    j = ask(client, "alice", "Make this timetable my primary", domain="PERSONAL", parameters=j["clarification"]["choices"][0]["value"])
    assert j["status"] == "PRIMARY_SELECTION_CONFLICT"  # already primary — and nothing else changed


def test_q29_list_archives_owner_private(client):
    a = ask(client, "alice", "Show my old timetable archives", domain="PERSONAL")
    b = ask(client, "bob", "Show my old timetable archives", domain="PERSONAL")
    assert a["intent_id"] == "Q29" and len(a["results"]) == 1
    assert b["status"] == "NO_MATCH" and b["results"] == []


def test_q30_cross_domain_rejected_without_querying(client, monkeypatch):
    import app.query.engine as eng

    def boom(*a, **k):
        raise AssertionError("context must not be resolved for Q30")

    monkeypatch.setattr(eng, "resolve_context", boom)
    for q in ("Compare my personal and college timetable", "What's the difference between my personal and official timetables?"):
        j = ask(client, "alice", q)
        assert j["status"] == "UNSUPPORTED_INTENT" and j["intent"] == "CROSS_DOMAIN_COMPARE" and j["_http"] == 422


# ------------------------------------------------------------------ isolation, safety, consistency


def test_personal_domain_never_falls_back_to_institutional(client):
    j = ask(client, "bob", "What is my next class?", domain="PERSONAL")  # API-07 / T11
    assert j["status"] == "NO_TIMETABLE_SELECTED" and j["results"] == []


def test_personal_and_institutional_results_are_disjoint(client, db):
    i = ask(client, "alice", "Show Monday's timetable")
    p = ask(client, "alice", "Show Monday's timetable", domain="PERSONAL")
    assert i["context"]["timetable_id"] != p["context"]["timetable_id"]
    inst_ids = {str(x) for x in db.scalars(select(InstitutionalTimetableEntry.entry_id))}
    assert not ({x["entry_id"] for x in p["results"]} & inst_ids)


def test_personal_labels_not_mapped_to_institutional_records(client):
    j = ask(client, "alice", "Who teaches SE-A?", domain="PERSONAL")
    assert j["intent_id"] == "Q19" and j["results"]  # label-based within the personal upload only


def test_explicit_archive_other_users_personal_id_denied(client, db):
    bob_tid = None
    alice = db.scalar(select(UserAccount).where(UserAccount.college_email == "alice@demo.college.edu"))
    from app.models import PersonalTimetable

    alice_tid = db.scalar(select(PersonalTimetable.timetable_id).where(PersonalTimetable.owner_user_id == alice.user_id))
    j = ask(client, "bob", "What is my next class?", domain="PERSONAL",
            selection={"type": "EXPLICIT_ARCHIVE", "timetable_id": str(alice_tid)})
    assert j["status"] == "TIMETABLE_NOT_FOUND" and j["results"] == []  # T06
    del bob_tid


def test_institutional_id_in_personal_domain_rejected(client, db):
    from app.models import InstitutionalTimetable

    tid = db.scalar(select(InstitutionalTimetable.timetable_id))
    j = ask(client, "alice", "Show my timetable", domain="PERSONAL", selection={"type": "EXPLICIT_ARCHIVE", "timetable_id": str(tid)})
    assert j["status"] == "TIMETABLE_NOT_FOUND"


def test_sql_injection_text_is_data(client):
    before = ask(client, "admin", "Show room 508 schedule")
    for q in ("Show room 508'; DROP TABLE institutional_timetable_entry; -- schedule",
              "Find all ' OR 1=1 -- classes", "Show prof x' UNION SELECT password_hash FROM user_account -- schedule"):
        j = ask(client, "admin", q)
        assert j["_http"] in (200, 422)
        assert "password" not in str(j["results"]).lower()
    after = ask(client, "admin", "Show room 508 schedule")
    assert len(after["results"]) == len(before["results"])  # API-10: nothing dropped or altered


def test_raw_sql_or_unknown_parameters_rejected(client):
    j = ask(client, "alice", None, intent="SHOW_MY_TIMETABLE", parameters={"sql": "SELECT 1"})
    assert j["status"] == "INVALID_REQUEST"
    j = ask(client, "alice", None, intent="RUN_SQL")
    assert j["status"] == "UNSUPPORTED_INTENT"
    j = ask(client, "alice", None, intent="SHOW_MY_TIMETABLE", parameters={"date": "2026-13-40"})
    assert j["status"] == "INVALID_REQUEST"


def test_unsupported_free_text(client):
    j = ask(client, "alice", "tell me a joke")
    assert j["status"] == "UNSUPPORTED_INTENT" and j["details"]["examples"]  # API-15


def test_student_without_batch_gets_setup_message(client):
    j = ask(client, "newbie", "What is my next class?")
    assert j["status"] == "CLARIFICATION_REQUIRED" and j["clarification"]["kind"] == "SETUP_REQUIRED"


def test_dashboard_uses_same_logic_as_typed_query(client):
    dash = client.get("/api/v1/dashboard", params={"domain": "INSTITUTIONAL"}, headers=H(client, "alice")).json()
    typed = ask(client, "alice", "What is my next class?")
    assert dash["cards"]["next"]["results"] == typed["results"]
    structured = ask(client, "alice", None, intent="NEXT_CLASS")
    assert structured["results"] == typed["results"]


def test_remember_last_selection_and_domain_switch(client, db):
    from app.models import InstitutionalTimetable

    tid = str(db.scalar(select(InstitutionalTimetable.timetable_id)))
    sel = {"type": "EXPLICIT_ARCHIVE", "timetable_id": tid}
    j = ask(client, "chitra", "Show my timetable", selection=sel)
    assert j["context"]["selection_type"] == "EXPLICIT_ARCHIVE"
    j = ask(client, "chitra", "Show my timetable")  # REMEMBER_LAST: restored, still explicit archive (API-08)
    assert j["context"]["selection_type"] == "EXPLICIT_ARCHIVE" and j["context"]["timetable_id"] == tid
    p = ask(client, "chitra", "Show my timetable", domain="PERSONAL")  # T05: does not carry into personal
    assert p["status"] == "NO_TIMETABLE_SELECTED"
    client.patch("/api/v1/me/preferences", headers=H(client, "chitra"), json={"selection_mode": "ALWAYS_USE_PRIMARY"})
    j = ask(client, "chitra", "Show my timetable")
    assert j["context"]["selection_type"] == "PRIMARY"


def test_search_history_and_saved_searches(client):
    h = H(client, "dev")
    ask(client, "dev", "What is my next class?")
    hist = client.get("/api/v1/search/history", headers=h).json()
    assert hist["items"][0]["query"] == "What is my next class?"
    r = client.post("/api/v1/saved-searches", headers=h, json={"name": "Next", "intent": "NEXT_CLASS"})
    assert r.status_code == 201
    run = client.post(f"/api/v1/saved-searches/{r.json()['saved_search_id']}/run", headers=h, params={"domain": "INSTITUTIONAL"})
    assert run.json()["intent"] == "NEXT_CLASS"
    bad = client.post("/api/v1/saved-searches", headers=h, json={"name": "x", "intent": "NEXT_CLASS", "parameters": {"sql": "1"}})
    assert bad.status_code == 400


def test_registry_lists_all_intents_and_templates(client):
    reg = client.get("/api/v1/search/registry", headers=H(client, "alice")).json()
    assert [i["id"] for i in reg["intents"]] == [f"Q{n:02d}" for n in range(1, 31)]
    assert [t["id"] for t in reg["templates"]] == [f"QT{n:02d}" for n in range(1, 23)]
