"""Uploads, worker, archives, primary selection and institutional/personal isolation."""
from __future__ import annotations

from app.enums import RoleCode
from app.models import InstitutionalTimetableEntry, PersonalTimetableEntry, ProcessingJob
from tests.helpers import upload, upload_and_process


def test_personal_upload_processing_and_primary_unchanged(client, f, fx, db):
    u = f.user(RoleCode.STUDENT)
    h = f.auth(u)
    tt = upload_and_process(client, h, fx("synthetic_timetable.pdf"))
    assert tt["processing_status"] == "NEEDS_REVIEW"
    assert tt["is_primary"] is False  # API-06 / PDF-15: upload never changes primary
    assert tt["validation_summary"]["class_entries"] > 0
    assert len(tt["sections"]) == 3 and tt["sections"][1]["is_tentative"] is True
    assert db.query(PersonalTimetableEntry).count() > 0
    assert db.query(InstitutionalTimetableEntry).count() == 0  # personal data only in personal tables
    pref = client.get("/api/v1/me/preferences", headers=h).json()
    assert pref["personal_primary_timetable_id"] is None
    # notification of completion
    notes = client.get("/api/v1/notifications", headers=h).json()
    assert notes["items"][0]["kind"] == "PROCESSING_COMPLETED"


def test_make_personal_primary_only_changes_personal(client, f, fx):
    dept = f.dept()
    year = f.year()
    admin, _ = f.staff(RoleCode.ADMIN, dept=dept)
    ah = f.auth(admin)
    inst = upload_and_process(client, ah, fx("synthetic_timetable.pdf"), "INSTITUTIONAL", academic_year_id=year.academic_year_id)
    assert client.post(f"/api/v1/timetables/{inst['timetable_id']}/make-primary", params={"domain": "INSTITUTIONAL"},
                       headers=ah).status_code == 200
    u = f.user(RoleCode.STUDENT)
    h = f.auth(u)
    pers = upload_and_process(client, h, fx("synthetic_timetable.xlsx"))
    r = client.post(f"/api/v1/timetables/{pers['timetable_id']}/make-primary", params={"domain": "PERSONAL"}, headers=h)
    assert r.status_code == 200, r.text
    ictx = client.get("/api/v1/timetable-context", params={"domain": "INSTITUTIONAL"}, headers=h).json()
    pctx = client.get("/api/v1/timetable-context", params={"domain": "PERSONAL"}, headers=h).json()
    assert ictx["primary"]["timetable_id"] == inst["timetable_id"]  # API-04 / T09
    assert pctx["primary"]["timetable_id"] == pers["timetable_id"]
    again = client.post(f"/api/v1/timetables/{pers['timetable_id']}/make-primary", params={"domain": "PERSONAL"}, headers=h)
    assert again.status_code == 409 and again.json()["status"] == "PRIMARY_SELECTION_CONFLICT"


def test_wrong_domain_id_is_not_found(client, f, fx):
    u = f.user(RoleCode.STUDENT)
    h = f.auth(u)
    pers = upload_and_process(client, h, fx("synthetic_timetable.csv"))
    r = client.get(f"/api/v1/timetables/{pers['timetable_id']}", params={"domain": "INSTITUTIONAL"}, headers=h)
    assert r.status_code == 404 and r.json()["status"] == "TIMETABLE_NOT_FOUND"


def test_idor_other_users_personal_timetable(client, f, fx, db):
    owner = f.user(RoleCode.STUDENT)
    other = f.user(RoleCode.STUDENT)
    admin, _ = f.staff(RoleCode.ADMIN)
    tt = upload_and_process(client, f.auth(owner), fx("synthetic_timetable.csv"))
    tid = tt["timetable_id"]
    for who in (other, admin):  # API-03: not even Admin gets application access to personal content
        h = f.auth(who)
        for path in (f"/api/v1/timetables/{tid}", f"/api/v1/timetables/{tid}/entries", f"/api/v1/timetables/{tid}/file"):
            r = client.get(path, params={"domain": "PERSONAL"}, headers=h)
            assert r.status_code == 404, path
        assert client.post(f"/api/v1/timetables/{tid}/make-primary", params={"domain": "PERSONAL"}, headers=h).status_code == 404
        assert client.get("/api/v1/timetables", params={"domain": "PERSONAL"}, headers=h).json()["pagination"]["total"] == 0
    from app.models import AuditEvent

    assert db.query(AuditEvent).filter(AuditEvent.event_type == "ACCESS_DENIED").count() >= 1


def test_institutional_upload_admin_only(client, f, fx):
    year = f.year()
    for role in (RoleCode.STUDENT, RoleCode.PROFESSOR, RoleCode.HOD, RoleCode.PRINCIPAL):
        u, _ = f.staff(role) if role != RoleCode.STUDENT else (f.user(role), None)
        r = upload(client, f.auth(u), fx("synthetic_timetable.pdf"), "INSTITUTIONAL", academic_year_id=year.academic_year_id)
        assert r.status_code == 403, role


def test_activation_requires_admin_and_notifies(client, f, fx):
    dept, year = f.dept(), f.year()
    admin, _ = f.staff(RoleCode.ADMIN, dept=dept)
    hod, _ = f.staff(RoleCode.HOD, dept=dept)
    ah = f.auth(admin)
    inst = upload_and_process(client, ah, fx("synthetic_timetable.pdf"), "INSTITUTIONAL", academic_year_id=year.academic_year_id)
    r = client.post(f"/api/v1/timetables/{inst['timetable_id']}/make-primary", params={"domain": "INSTITUTIONAL"}, headers=f.auth(hod))
    assert r.status_code == 403  # T10
    ver0 = client.get("/api/v1/timetable-context", params={"domain": "INSTITUTIONAL"}, headers=ah).json()["institutional_settings_version"]
    r = client.post(f"/api/v1/timetables/{inst['timetable_id']}/make-primary", params={"domain": "INSTITUTIONAL"}, headers=ah)
    assert r.status_code == 200 and r.json()["settings_version"] == ver0 + 1
    notes = client.get("/api/v1/notifications", headers=f.auth(hod)).json()
    assert any(n["kind"] == "OFFICIAL_TIMETABLE_ACTIVATED" for n in notes["items"])


def test_failed_and_unusable_cannot_be_primary(client, f, fx):
    u = f.user(RoleCode.STUDENT)
    h = f.auth(u)
    tt = upload_and_process(client, h, fx("no_timetable.pdf"))
    assert tt["processing_status"] == "UNUSABLE"
    r = client.post(f"/api/v1/timetables/{tt['timetable_id']}/make-primary", params={"domain": "PERSONAL"}, headers=h)
    assert r.status_code == 409


def test_corrupt_and_wrong_type_rejected_at_upload(client, f, fx):
    h = f.auth(f.user(RoleCode.STUDENT))
    r = upload(client, h, fx("corrupt.pdf"))
    assert r.status_code == 415 and r.json()["status"] == "UNSUPPORTED_FILE"
    r = upload(client, h, fx("not_a_timetable.txt"))
    assert r.status_code == 415
    r = client.post("/api/v1/timetables/uploads", headers=h, data={"domain": "PERSONAL"},
                    files={"file": ("fake.pdf", b"MZ\x90\x00 not a pdf")})
    assert r.status_code == 415 and r.json()["details"]["reason"] == "SIGNATURE"


def test_idempotent_upload_and_duplicate_file(client, f, fx, db):
    h = f.auth(f.user(RoleCode.STUDENT))
    a = upload(client, h, fx("synthetic_timetable.csv"), client_request_id="req-123")
    b = upload(client, h, fx("synthetic_timetable.csv"), client_request_id="req-123")
    assert a.status_code == b.status_code == 201
    assert a.json()["timetable_id"] == b.json()["timetable_id"] and b.json()["created"] is False
    c = upload(client, h, fx("synthetic_timetable.csv"), client_request_id="req-456")
    assert c.json()["timetable_id"] != a.json()["timetable_id"]  # re-upload = separate archive
    assert c.json()["warnings"][0]["code"] == "DUPLICATE_FILE"
    assert db.query(ProcessingJob).count() == 2


def test_same_file_both_domains_stays_separate(client, f, fx, db):
    """PDF-14: same pipeline, separate records, different access scopes."""
    year = f.year()
    admin, _ = f.staff(RoleCode.ADMIN)
    ah = f.auth(admin)
    i = upload_and_process(client, ah, fx("synthetic_timetable.pdf"), "INSTITUTIONAL", academic_year_id=year.academic_year_id)
    p = upload_and_process(client, ah, fx("synthetic_timetable.pdf"), "PERSONAL")
    assert i["timetable_id"] != p["timetable_id"]
    ni = db.query(InstitutionalTimetableEntry).count()
    np_ = db.query(PersonalTimetableEntry).count()
    assert ni == np_ > 0


def test_review_correction_preserves_original_and_is_audited(client, f, fx, db):
    year = f.year()
    admin, _ = f.staff(RoleCode.ADMIN)
    ah = f.auth(admin)
    inst = upload_and_process(client, ah, fx("synthetic_timetable.pdf"), "INSTITUTIONAL", academic_year_id=year.academic_year_id)
    tid = inst["timetable_id"]
    rs = client.get(f"/api/v1/timetables/{tid}/review-summary", params={"domain": "INSTITUTIONAL"}, headers=ah).json()
    assert rs["ambiguous_time_labels"] > 0 and rs["tentative_sections"] == 1 and "conflicts" in rs
    flagged = client.get(f"/api/v1/timetables/{tid}/entries", headers=ah,
                         params={"domain": "INSTITUTIONAL", "needs_review": True, "review": True, "limit": 100}).json()["items"]
    noon = next(e for e in flagged if any(w["code"] == "TIME_LABEL_INCONSISTENT" for w in e["warnings"]))
    r = client.patch(f"/api/v1/timetables/{tid}/entries/{noon['entry_id']}", params={"domain": "INSTITUTIONAL"}, headers=ah,
                     json={"start_time": "12:15", "end_time": "13:15", "verification_status": "VERIFIED", "reason": "Checked with office"})
    assert r.status_code == 200, r.text
    assert r.json()["verification_status"] == "VERIFIED" and r.json()["time_uncertain"] is False and r.json()["is_corrected"]
    hist = client.get(f"/api/v1/timetables/{tid}/entries/{noon['entry_id']}/corrections", params={"domain": "INSTITUTIONAL"}, headers=ah).json()
    assert hist["items"][0]["before"]["time_uncertain"] is True
    student = f.user(RoleCode.STUDENT)
    r = client.patch(f"/api/v1/timetables/{tid}/entries/{noon['entry_id']}", params={"domain": "INSTITUTIONAL"},
                     headers=f.auth(student), json={"room": "999"})
    assert r.status_code == 403
    from app.models import AuditEvent

    assert db.query(AuditEvent).filter(AuditEvent.event_type == "INSTITUTIONAL_ENTRY_CORRECTED").count() == 1


def test_worker_retry_on_unexpected_error(client, f, fx, db, monkeypatch):
    h = f.auth(f.user(RoleCode.STUDENT))
    r = upload(client, h, fx("synthetic_timetable.csv"))
    import app.worker as w

    calls = {"n": 0}
    real = w.run_extraction

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return real(*a, **k)

    monkeypatch.setattr(w, "run_extraction", flaky)
    w.drain()
    job = db.query(ProcessingJob).one()
    db.refresh(job)
    assert job.status == "SUCCEEDED" and job.attempts == 2
    tt = client.get(f"/api/v1/timetables/{r.json()['timetable_id']}", params={"domain": "PERSONAL"}, headers=h).json()
    assert tt["processing_status"] in ("READY", "NEEDS_REVIEW")


def test_archive_soft_delete_rules(client, f, fx):
    h = f.auth(f.user(RoleCode.STUDENT))
    a = upload_and_process(client, h, fx("synthetic_timetable.csv"))
    client.post(f"/api/v1/timetables/{a['timetable_id']}/make-primary", params={"domain": "PERSONAL"}, headers=h)
    r = client.delete(f"/api/v1/timetables/{a['timetable_id']}", params={"domain": "PERSONAL"}, headers=h)
    assert r.status_code == 409  # cannot delete current primary
    b = upload_and_process(client, h, fx("synthetic_timetable.xlsx"))
    assert client.delete(f"/api/v1/timetables/{b['timetable_id']}", params={"domain": "PERSONAL"}, headers=h).status_code == 200
    lst = client.get("/api/v1/timetables", params={"domain": "PERSONAL"}, headers=h).json()
    assert [t["timetable_id"] for t in lst["items"]] == [a["timetable_id"]]
