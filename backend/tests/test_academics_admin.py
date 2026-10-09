"""Academic history, promotion transitions, master data, role matrix, conflicts and concurrency."""
from __future__ import annotations

import threading
from datetime import date

from sqlalchemy import select

from app.enums import RoleCode
from app.models import AuditEvent, Student, StudentAcademicHistory
from tests.helpers import upload_and_process


def _setup(f):
    dept = f.dept()
    y1 = f.year("2025-2026", "CLOSED")
    y2 = f.year("2026-2027", "ACTIVE")
    se_a = f.batch(dept, "SE-A", year=2)
    te_a = f.batch(dept, "TE-A", year=3)
    admin, _ = f.staff(RoleCode.ADMIN, dept=dept)
    return dept, y1, y2, se_a, te_a, admin


def test_fresher_registration_no_duplicates(client, f):
    dept, _, y2, se_a, _, admin = _setup(f)
    h = f.auth(admin)
    body = {"email": "fresh@college.edu", "display_name": "Fresh One", "uid": "2026CE001", "department_id": dept.department_id,
            "academic_year_id": y2.academic_year_id, "year_of_study": 1, "semester": 1, "batch_id": se_a.batch_id,
            "effective_from": "2026-07-15"}
    assert client.post("/api/v1/admin/students", headers=h, json=body).status_code == 201
    dup_uid = client.post("/api/v1/admin/students", headers=h, json={**body, "email": "other@college.edu"})
    assert dup_uid.status_code == 409 and dup_uid.json()["details"]["field"] == "uid"
    dup_email = client.post("/api/v1/admin/students", headers=h, json={**body, "uid": "2026CE002"})
    assert dup_email.status_code == 409


def test_promotion_preview_confirm_preserves_history(client, f, db):
    dept, _, y2, se_a, te_a, admin = _setup(f)
    _, st = f.student(dept, y2, se_a)
    h = f.auth(admin)
    item = {"student_id": str(st.student_id), "outcome": "PROMOTE", "effective_date": "2027-07-01",
            "academic_year_id": y2.academic_year_id, "year_of_study": 3, "semester": 5, "batch_id": te_a.batch_id}
    pv = client.post("/api/v1/admin/promotions/preview", headers=h, json={"items": [item]}).json()
    assert pv["can_confirm"] and pv["items"][0]["close_current_as"] == "PROMOTED"
    assert db.query(StudentAcademicHistory).count() == 1  # preview writes nothing
    r = client.post("/api/v1/admin/promotions/confirm", headers=h, json={"items": [item]})
    assert r.status_code == 200, r.text
    db.expire_all()
    rows = db.scalars(select(StudentAcademicHistory).order_by(StudentAcademicHistory.effective_from)).all()
    assert [(x.status, x.batch_id, x.effective_to) for x in rows] == [
        ("PROMOTED", se_a.batch_id, date(2027, 7, 1)), ("ACTIVE", te_a.batch_id, None)]
    assert rows[1].confirmed_by_staff_id is not None and rows[1].confirmed_at is not None
    assert db.query(AuditEvent).filter_by(event_type="ACADEMIC_TRANSITION_CONFIRMED").count() == 1
    # promoting again from the closed record is impossible; promotion must move forward
    back = {**item, "year_of_study": 2}
    assert not client.post("/api/v1/admin/promotions/preview", headers=h, json={"items": [back]}).json()["can_confirm"]


def test_transition_rules_repeat_pause_resume_withdraw_reenter_graduate(client, f, db):
    dept, _, y2, se_a, _, admin = _setup(f)
    _, st = f.student(dept, y2, se_a)
    h = f.auth(admin)
    sid = str(st.student_id)

    def do(outcome, eff, **kw):
        return client.post("/api/v1/admin/promotions/confirm", headers=h,
                           json={"items": [{"student_id": sid, "outcome": outcome, "effective_date": eff, **kw}]})

    assert do("RESUME", "2026-08-01").status_code == 409          # not paused
    assert do("PAUSE", "2026-08-01").status_code == 200
    assert do("PROMOTE", "2026-09-01", academic_year_id=y2.academic_year_id, year_of_study=3).status_code == 409  # paused
    assert do("RESUME", "2026-09-01").status_code == 200
    assert do("REPEAT", "2027-07-01", academic_year_id=y2.academic_year_id).status_code == 200
    assert do("WITHDRAW", "2027-08-01").status_code == 200
    db.expire_all()
    assert db.get(Student, st.student_id).student_status == "WITHDRAWN"
    assert do("RE_ENTER", "2027-09-01", academic_year_id=y2.academic_year_id, year_of_study=2,
              department_id=dept.department_id).status_code == 200
    assert do("GRADUATE", "2028-06-30").status_code == 200
    assert do("RE_ENTER", "2028-07-01", academic_year_id=y2.academic_year_id, year_of_study=2).status_code == 409
    db.expire_all()
    rows = db.scalars(select(StudentAcademicHistory).where(StudentAcademicHistory.student_id == st.student_id)).all()
    # initial, pause, resume, repeat, re-entry open rows; withdraw and graduate only close one
    assert len(rows) == 5 and sum(1 for r in rows if r.effective_to is None) == 0  # graduated: nothing open


def test_batch_confirmation_is_all_or_nothing(client, f, db):
    dept, _, y2, se_a, te_a, admin = _setup(f)
    _, ok = f.student(dept, y2, se_a)
    _, other = f.student(dept, y2, se_a)
    h = f.auth(admin)
    items = [{"student_id": str(ok.student_id), "outcome": "PROMOTE", "effective_date": "2027-07-01",
              "academic_year_id": y2.academic_year_id, "year_of_study": 3},
             {"student_id": str(other.student_id), "outcome": "RESUME", "effective_date": "2027-07-01"}]  # invalid
    assert client.post("/api/v1/admin/promotions/confirm", headers=h, json={"items": items}).status_code == 409
    db.expire_all()
    assert db.query(StudentAcademicHistory).filter(StudentAcademicHistory.effective_to.is_(None)).count() == 2


def test_concurrent_promotions_cannot_create_two_open_placements(f, db):
    """Two Admins confirm the same promotion at once: row locks serialise them; one fails."""
    from app.db import session_factory
    from app.errors import AppError
    from app.security.principal import load_principal
    from app.services import academics

    dept, _, y2, se_a, te_a, admin = _setup(f)
    _, st = f.student(dept, y2, se_a)
    outcomes = []

    def worker():
        with session_factory()() as s:
            p = load_principal(s, s.get(type(admin), admin.user_id))
            req = academics.TransitionRequest(st.student_id, academics.Outcome.PROMOTE, date(2027, 7, 1), y2.academic_year_id, 3,
                                              batch_id=te_a.batch_id)
            try:
                academics.confirm(s, p, [req])
                outcomes.append("ok")
            except (AppError, Exception) as e:  # noqa: BLE001
                outcomes.append(type(e).__name__)

    ts = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert outcomes.count("ok") == 1
    db.expire_all()
    assert db.query(StudentAcademicHistory).filter(StudentAcademicHistory.effective_to.is_(None)).count() == 1


def test_single_active_academic_year(client, f, db):
    _, _, y2, _, _, admin = _setup(f)
    h = f.auth(admin)
    r = client.post("/api/v1/admin/academic-years", headers=h,
                    json={"label": "2027-2028", "start_date": "2027-07-01", "end_date": "2028-06-30", "status": "ACTIVE"})
    assert r.status_code == 201
    years = {y["label"]: y["status"] for y in client.get("/api/v1/admin/academic-years", headers=h).json()["items"]}
    assert years["2027-2028"] == "ACTIVE" and years["2026-2027"] == "CLOSED"


def test_master_data_crud_and_validation(client, f):
    dept, _, _, se_a, _, admin = _setup(f)
    h = f.auth(admin)
    r = client.post("/api/v1/admin/rooms", headers=h, json={"room_code": "R-204", "floor_label": "2", "capacity": 40})
    assert r.status_code == 201
    assert client.post("/api/v1/admin/rooms", headers=h, json={"room_code": "R-204"}).status_code == 409
    assert client.post("/api/v1/admin/rooms", headers=h, json={"room_code": "X", "capacity": -1}).status_code == 400
    sub = client.post("/api/v1/admin/batches", headers=h, json={"department_id": dept.department_id, "code": "se-a1", "cohort_label": "SE-2025",
                                                                "division_label": "A1", "program_year": 2, "parent_batch_id": se_a.batch_id})
    assert sub.status_code == 201 and sub.json()["code"] == "SE-A1"
    nested = client.post("/api/v1/admin/batches", headers=h, json={"department_id": dept.department_id, "code": "SE-A1X", "cohort_label": "SE-2025",
                                                                   "division_label": "A1X", "program_year": 2, "parent_batch_id": sub.json()["batch_id"]})
    assert nested.status_code == 400
    bad_alias = client.post("/api/v1/admin/aliases", headers=h, json={"entity_type": "ROOM", "alias": "204", "entity_id": "999"})
    assert bad_alias.status_code == 400
    cfg = client.put("/api/v1/admin/config", headers=h, json={"week_start_day": 1, "working_hours_start": "17:00", "working_hours_end": "09:00"})
    assert cfg.status_code == 400


def test_role_matrix_admin_endpoints(client, f):
    dept = f.dept()
    users = {
        "STUDENT": f.user(RoleCode.STUDENT),
        "PROFESSOR": f.staff(RoleCode.PROFESSOR, dept=dept)[0],
        "HOD": f.staff(RoleCode.HOD, dept=dept)[0],
        "PRINCIPAL": f.staff(RoleCode.PRINCIPAL)[0],
        "ADMIN": f.staff(RoleCode.ADMIN)[0],
    }
    for role, u in users.items():
        h = f.auth(u)
        for path in ("/api/v1/admin/users", "/api/v1/admin/audit", "/api/v1/admin/rooms", "/api/v1/admin/config"):
            code = client.get(path, headers=h).status_code
            assert code == (200 if role == "ADMIN" else 403), (role, path, code)


def test_conflict_detection_and_access(client, f, fx):
    dept, _, y2, _, _, admin = _setup(f)
    ah = f.auth(admin)
    tt = upload_and_process(client, ah, fx("synthetic_timetable.pdf"), "INSTITUTIONAL", academic_year_id=y2.academic_year_id)
    tid = tt["timetable_id"]
    c = client.get(f"/api/v1/timetables/{tid}/conflicts", headers=ah).json()
    # The synthetic BE page puts DS Lab B2 in room 604 on Monday 10:00 while SE-A1's DS Lab also uses 604 then.
    rooms = [x for x in c["conflicts"] if x["type"] == "ROOM_OVERLAP" and x["resource"] == "604"]
    assert rooms and all(len(x["entries"]) == 2 for x in rooms)
    assert all(x["confidence"] == "POSSIBLE" for x in rooms)  # unmapped/unverified data is never "confirmed"
    # back-to-back classes are not conflicts (end-exclusive)
    for x in c["conflicts"]:
        a, b = x["entries"]
        assert a["start_time"] < b["end_time"] and b["start_time"] < a["end_time"]
    student = f.user(RoleCode.STUDENT)
    assert client.get(f"/api/v1/timetables/{tid}/conflicts", headers=f.auth(student)).status_code == 403
    client.post(f"/api/v1/timetables/{tid}/make-primary", params={"domain": "INSTITUTIONAL"}, headers=ah)
    hod, _ = f.staff(RoleCode.HOD, dept=dept)
    assert client.get(f"/api/v1/timetables/{tid}/conflicts", headers=f.auth(hod)).status_code == 200


def test_concurrent_activation_single_default(client, f, fx, db):
    from app.db import session_factory
    from app.enums import Domain
    from app.security.principal import load_principal
    from app.services.timetables import institutional_default_id, set_primary

    _, _, y2, _, _, admin = _setup(f)
    ah = f.auth(admin)
    a = upload_and_process(client, ah, fx("synthetic_timetable.csv"), "INSTITUTIONAL", academic_year_id=y2.academic_year_id)
    b = upload_and_process(client, ah, fx("synthetic_timetable.xlsx"), "INSTITUTIONAL", academic_year_id=y2.academic_year_id)
    done = []

    def activate(tid):
        with session_factory()() as s:
            p = load_principal(s, s.get(type(admin), admin.user_id))
            try:
                set_primary(s, p, Domain.INSTITUTIONAL, tid)
                done.append(tid)
            except Exception as e:  # noqa: BLE001
                done.append(type(e).__name__)

    ts = [threading.Thread(target=activate, args=(t,)) for t in (a["timetable_id"], b["timetable_id"])]
    [t.start() for t in ts]
    [t.join() for t in ts]
    db.expire_all()
    final = str(institutional_default_id(db))
    assert final in (a["timetable_id"], b["timetable_id"])
    from app.models import InstitutionalTimetableSettings

    assert db.get(InstitutionalTimetableSettings, 1).version == 3  # both serialised updates applied in order


def test_notifications_read_flow(client, f, fx):
    u = f.user(RoleCode.STUDENT)
    h = f.auth(u)
    upload_and_process(client, h, fx("synthetic_timetable.csv"))
    assert client.get("/api/v1/notifications/unread-count", headers=h).json()["unread"] == 1
    other = f.user(RoleCode.STUDENT)
    nid = client.get("/api/v1/notifications", headers=h).json()["items"][0]["notification_id"]
    client.post(f"/api/v1/notifications/{nid}/read", headers=f.auth(other))  # someone else cannot mark it
    assert client.get("/api/v1/notifications/unread-count", headers=h).json()["unread"] == 1
    client.post(f"/api/v1/notifications/{nid}/read", headers=h)
    assert client.get("/api/v1/notifications/unread-count", headers=h).json()["unread"] == 0


def test_health_and_openapi(client):
    assert client.get("/healthz").json()["status"] == "OK"
    spec = client.get("/api/v1/openapi.json").json()
    assert "/api/v1/search" in spec["paths"] and "/api/v1/timetables/uploads" in spec["paths"]


def test_validation_error_envelope(client, f):
    u = f.user(RoleCode.STUDENT)
    r = client.patch("/api/v1/me/preferences", headers=f.auth(u), json={"selection_mode": "WHATEVER"})
    assert r.status_code == 400 and r.json()["status"] == "INVALID_REQUEST" and r.json()["details"]["fields"]
