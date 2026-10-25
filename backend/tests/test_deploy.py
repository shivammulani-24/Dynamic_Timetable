"""Single-service hosting: web app served by the API, HEAD for the app's connectivity check,
database URL formats from hosting providers, and the guards around demo data in production."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings


@pytest.fixture
def web_client(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html><div id=\"root\"></div></html>")
    (tmp_path / "_expo" / "static").mkdir(parents=True)
    (tmp_path / "_expo" / "static" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(get_settings(), "web_dist_dir", tmp_path)
    from app.main import create_app

    return TestClient(create_app())


def test_web_app_served_with_spa_fallback(web_client):
    r = web_client.get("/")
    assert r.status_code == 200 and 'id="root"' in r.text
    assert 'id="root"' in web_client.get("/timetable/deep/link").text           # refresh on any app page
    js = web_client.get("/_expo/static/app.js")
    assert js.status_code == 200 and "immutable" in js.headers["cache-control"]


def test_head_root_answers_for_connectivity_check(web_client):
    assert web_client.head("/").status_code == 200   # 405 here made the web app think it was offline


def test_api_paths_never_fall_through_to_the_app(web_client):
    r = web_client.get("/api/v1/does-not-exist")
    assert r.status_code == 404 and r.json()["status"] == "NOT_FOUND"
    assert web_client.get("/healthz").json() == {"status": "OK"}


def test_files_outside_the_web_app_are_not_served(web_client):
    r = web_client.get("/../../../../etc/passwd")
    assert "root:x:0" not in r.text


@pytest.mark.parametrize("url", ["postgres://u:p@h:5432/d", "postgresql://u:p@h:5432/d"])
def test_hosting_database_urls_get_the_driver(url):
    assert Settings(database_url=url).database_url == "postgresql+psycopg://u:p@h:5432/d"


def _prod(**kw) -> Settings:
    base = dict(environment="production", jwt_secret="x" * 40, cors_origins=[])
    return Settings(**{**base, **kw})


def test_production_demo_seed_needs_a_private_password():
    for bad in (None, "short", "Demo@12345"):
        with pytest.raises(RuntimeError):
            _prod(allow_demo_seed=True, demo_password=bad).validate_for_production()
    _prod(allow_demo_seed=True, demo_password="Pilot#Demo2026").validate_for_production()


def test_production_without_email_never_logs_reset_codes():
    s = _prod()
    assert s.reset_codes_in_server_log is False and s.invitation_codes_shown_to_admin is True
