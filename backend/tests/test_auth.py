from __future__ import annotations

from app.enums import AccountStatus, RoleCode
from tests.conftest import PASSWORD


def login(client, email, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_login_success_and_me(client, f):
    u = f.user(RoleCode.STUDENT, email="alice@college.edu")
    r = login(client, "ALICE@college.edu ")
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    me = client.get("/api/v1/me", headers={"Authorization": f"Bearer {tok}"})
    assert me.status_code == 200
    assert me.json()["roles"] == ["STUDENT"]
    assert me.json()["user_id"] == str(u.user_id)


def test_login_wrong_password_and_unknown_user_same_error(client, f):
    f.user(RoleCode.STUDENT, email="bob@college.edu")
    a = login(client, "bob@college.edu", "wrong-password1")
    b = login(client, "nobody@college.edu")
    assert a.status_code == b.status_code == 401
    assert a.json()["status"] == b.json()["status"] == "UNAUTHENTICATED"
    assert a.json()["message"] == b.json()["message"]


def test_suspended_account_cannot_login_or_use_token(client, f):
    u = f.user(RoleCode.PROFESSOR, email="sus@college.edu")
    headers = f.auth(u)
    assert client.get("/api/v1/me", headers=headers).status_code == 200
    f.db.query(type(u)).filter_by(user_id=u.user_id).update({"account_status": AccountStatus.SUSPENDED})
    f.db.commit()
    assert login(client, "sus@college.edu").status_code == 401
    r = client.get("/api/v1/me", headers=headers)
    assert r.status_code == 401 and r.json()["details"]["reason"] == "ACCOUNT_SUSPENDED"


def test_missing_and_garbage_token(client):
    assert client.get("/api/v1/me").json()["status"] == "UNAUTHENTICATED"
    r = client.get("/api/v1/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401


def test_expired_token(client, f, monkeypatch):
    import jwt
    from datetime import datetime, timedelta, timezone

    from app.config import get_settings

    u = f.user(RoleCode.STUDENT)
    s = get_settings()
    tok = jwt.encode({"sub": str(u.user_id), "ver": 0, "typ": "access",
                      "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}, s.jwt_secret, algorithm=s.jwt_algorithm)
    r = client.get("/api/v1/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401 and r.json()["details"]["reason"] == "TOKEN_EXPIRED"


def test_refresh_rotation_and_reuse_detection(client, f):
    f.user(RoleCode.STUDENT, email="rot@college.edu")
    first = login(client, "rot@college.edu").json()
    second = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert second.status_code == 200
    # Re-using the rotated token revokes the whole family, including the newest token.
    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert reuse.status_code == 401 and reuse.json()["details"]["reason"] == "REFRESH_REUSED"
    third = client.post("/api/v1/auth/refresh", json={"refresh_token": second.json()["refresh_token"]})
    assert third.status_code == 401


def test_logout_revokes_refresh(client, f):
    f.user(RoleCode.STUDENT, email="out@college.edu")
    t = login(client, "out@college.edu").json()
    h = {"Authorization": f"Bearer {t['access_token']}"}
    assert client.post("/api/v1/auth/logout", json={"refresh_token": t["refresh_token"]}, headers=h).status_code == 200
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code == 401


def test_role_escalation_not_possible_via_client(client, f):
    u = f.user(RoleCode.STUDENT)
    h = f.auth(u)
    # Admin endpoint denied even if the client claims a role in body/headers.
    r = client.get("/api/v1/admin/users", headers={**h, "X-Role": "ADMIN"})
    assert r.status_code == 403 and r.json()["status"] == "ACCESS_DENIED"
    r = client.put(f"/api/v1/admin/users/{u.user_id}/roles", json={"roles": ["ADMIN"]}, headers=h)
    assert r.status_code == 403


def test_invitation_activation_and_password_reset(client, f, caplog):
    dept = f.dept()
    admin_u, _ = f.staff(RoleCode.ADMIN, dept=dept)
    h = f.auth(admin_u)
    r = client.post("/api/v1/admin/staff", headers=h, json={
        "email": "newprof@college.edu", "display_name": "Prof. New", "roles": ["PROFESSOR"], "department_id": dept.department_id})
    assert r.status_code == 201, r.text
    token = r.json()["invitation_code"]  # shown to the Admin only because no email is configured
    assert login(client, "newprof@college.edu").status_code == 401  # not activated yet
    weak = client.post("/api/v1/auth/activate", json={"token": token, "password": "short"})
    assert weak.status_code == 400
    ok = client.post("/api/v1/auth/activate", json={"token": token, "password": "GoodPassword9", "timezone": "Asia/Kolkata"})
    assert ok.status_code == 200, ok.text
    again = client.post("/api/v1/auth/activate", json={"token": token, "password": "GoodPassword9"})
    assert again.status_code == 400  # single use
    assert login(client, "newprof@college.edu", "GoodPassword9").status_code == 200

    caplog.set_level("WARNING")
    rr = client.post("/api/v1/auth/password-reset/request", json={"email": "newprof@college.edu"})
    assert rr.status_code == 202
    # P0-1 regression: the unauthenticated response never carries the code (anyone could call it).
    assert set(rr.json()) == {"status", "message"}
    # Development without email: the code appears only in the server's own log.
    line = next(r.getMessage() for r in caplog.records if "password reset code" in r.getMessage())
    reset = line.rsplit(": ", 1)[1].strip()
    unknown = client.post("/api/v1/auth/password-reset/request", json={"email": "ghost@college.edu"})
    assert unknown.status_code == 202 and set(unknown.json()) == {"status", "message"}
    assert client.post("/api/v1/auth/password-reset/confirm", json={"token": reset, "password": "Another1Pass"}).status_code == 200
    assert login(client, "newprof@college.edu", "Another1Pass").status_code == 200


def test_role_change_invalidates_existing_tokens(client, f):
    dept = f.dept()
    admin_u, _ = f.staff(RoleCode.ADMIN, dept=dept)
    prof_u, _ = f.staff(RoleCode.PROFESSOR, dept=dept)
    ph = f.auth(prof_u)
    r = client.put(f"/api/v1/admin/users/{prof_u.user_id}/roles", json={"roles": ["PROFESSOR", "HOD"]}, headers=f.auth(admin_u))
    assert r.status_code == 200
    assert client.get("/api/v1/me", headers=ph).status_code == 401


def test_admin_cannot_remove_own_admin_or_suspend_self(client, f):
    admin_u, _ = f.staff(RoleCode.ADMIN)
    h = f.auth(admin_u)
    assert client.put(f"/api/v1/admin/users/{admin_u.user_id}/roles", json={"roles": ["PROFESSOR"]}, headers=h).status_code == 409
    assert client.put(f"/api/v1/admin/users/{admin_u.user_id}/status", json={"account_status": "SUSPENDED"}, headers=h).status_code == 409


def test_preferences_timezone_validation(client, f):
    u = f.user(RoleCode.STUDENT)
    h = f.auth(u)
    bad = client.patch("/api/v1/me/preferences", json={"timezone": "Mars/Olympus"}, headers=h)
    assert bad.status_code == 400
    ok = client.patch("/api/v1/me/preferences", json={"timezone": "Europe/London", "selection_mode": "ALWAYS_USE_PRIMARY"}, headers=h)
    assert ok.status_code == 200 and ok.json()["timezone"] == "Europe/London"
    assert client.get("/api/v1/me/preferences", headers=h).json()["selection_mode"] == "ALWAYS_USE_PRIMARY"


def test_login_rate_limited(client, f):
    f.user(RoleCode.STUDENT, email="rl@college.edu")
    codes = [login(client, "rl@college.edu", "bad-password1").status_code for _ in range(12)]
    assert 429 in codes


def test_reset_code_never_logged_in_production(client, f, caplog, monkeypatch):
    from app.config import get_settings

    u = f.user(RoleCode.STUDENT)
    monkeypatch.setattr(type(get_settings()), "is_production", property(lambda self: True))
    caplog.set_level("WARNING")
    r = client.post("/api/v1/auth/password-reset/request", json={"email": u.college_email})
    assert r.status_code == 202 and set(r.json()) == {"status", "message"}
    assert not any("password reset code" in x.getMessage() for x in caplog.records)


def test_admin_issued_access_code_resets_an_active_account(client, f):
    dept = f.dept()
    admin_u, _ = f.staff(RoleCode.ADMIN, dept=dept)
    student = f.user(RoleCode.STUDENT)
    old = login(client, student.college_email)
    assert old.status_code == 200
    r = client.post(f"/api/v1/admin/users/{student.user_id}/reinvite", headers=f.auth(admin_u))
    assert r.status_code == 200 and r.json()["invitation_code"]
    ok = client.post("/api/v1/auth/activate", json={"token": r.json()["invitation_code"], "password": "BrandNew9pass"})
    assert ok.status_code == 200
    assert login(client, student.college_email, "BrandNew9pass").status_code == 200
    # the session from before the reset is gone
    refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": old.json()["refresh_token"]})
    assert refresh.status_code == 401
    # only the Admin can issue it (fresh student login; the old one was revoked above)
    fresh = login(client, student.college_email, "BrandNew9pass").json()["access_token"]
    assert client.post(f"/api/v1/admin/users/{student.user_id}/reinvite",
                       headers={"Authorization": f"Bearer {fresh}"}).status_code == 403
