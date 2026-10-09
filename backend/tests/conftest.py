from __future__ import annotations

import os
import tempfile
import uuid
from datetime import date

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://timetable:timetable_dev@localhost:5432/timetable_test"
)
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="tt-storage-")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import get_engine, session_factory  # noqa: E402
from app.enums import AccountStatus, HistoryStatus, RoleCode  # noqa: E402
from app.models import (  # noqa: E402
    AcademicYear,
    Batch,
    Department,
    Role,
    Staff,
    Student,
    StudentAcademicHistory,
    UserAccount,
    UserPreference,
    UserRole,
)
from app.security import ratelimit  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402
from app.security.tokens import create_access_token  # noqa: E402
from app.services.context import Clock  # noqa: E402

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP = {"role", "alembic_version"}
PASSWORD = "Password123"


@pytest.fixture(scope="session", autouse=True)
def _schema():
    with get_engine().begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(os.path.join(BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND, "alembic"))
    command.upgrade(cfg, "head")
    yield


def truncate_all() -> None:
    with get_engine().begin() as c:
        tables = [r[0] for r in c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'"))]
        c.execute(text("TRUNCATE " + ", ".join(t for t in tables if t not in KEEP) + " RESTART IDENTITY CASCADE"))
        c.execute(text("INSERT INTO institutional_timetable_settings (settings_id, version) VALUES (1, 1)"))
        c.execute(text("INSERT INTO institution_config (config_id, next_class_lookahead_days) VALUES (1, 7)"))


@pytest.fixture(autouse=True)
def _clean(request):
    """Fresh database per test, except modules that declare SHARED_DB = True (they seed once)."""
    ratelimit.reset()
    if not getattr(request.module, "SHARED_DB", False):
        Clock.freeze(None)
        truncate_all()
    yield
    if not getattr(request.module, "SHARED_DB", False):
        Clock.freeze(None)


@pytest.fixture(scope="session")
def fx():
    """Generated SYNTHETIC fixtures (see tests/fixtures/make_fixtures.py)."""
    from app.devdata.synthetic import main

    out = main(tempfile.mkdtemp(prefix="tt-fixtures-"))

    def path(name: str) -> str:
        return os.path.join(out, name)

    return path


@pytest.fixture
def db():
    s = session_factory()()
    yield s
    s.close()


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


class Factory:
    def __init__(self, db):
        self.db = db
        self._n = 0

    def dept(self, code="CE", name="Computer Engineering") -> Department:
        d = Department(code=code, name=name)
        self.db.add(d)
        self.db.commit()
        return d

    def year(self, label="2026-2027", status="ACTIVE") -> AcademicYear:
        y = AcademicYear(label=label, start_date=date(2026, 7, 1), end_date=date(2027, 6, 30), status=status)
        self.db.add(y)
        self.db.commit()
        return y

    def batch(self, dept: Department, code: str, parent: Batch | None = None, year=2) -> Batch:
        b = Batch(department_id=dept.department_id, code=code, cohort_label=code.split("-")[0] + "-2025",
                  division_label=code.split("-")[-1], program_year=year, parent_batch_id=parent.batch_id if parent else None)
        self.db.add(b)
        self.db.commit()
        return b

    def user(self, *roles: RoleCode, email: str | None = None, name: str | None = None, status=AccountStatus.ACTIVE,
             tz="Asia/Kolkata") -> UserAccount:
        self._n += 1
        u = UserAccount(college_email=email or f"user{self._n}-{uuid.uuid4().hex[:6]}@college.edu",
                        display_name=name or f"User {self._n}", password_hash=hash_password(PASSWORD),
                        account_status=status, timezone_id=tz)
        self.db.add(u)
        self.db.flush()
        for r in roles:
            rid = self.db.query(Role).filter(Role.code == r.value).one().role_id
            self.db.add(UserRole(user_id=u.user_id, role_id=rid))
        self.db.add(UserPreference(user_id=u.user_id))
        self.db.commit()
        return u

    def staff(self, *roles: RoleCode, dept: Department | None = None, short_code=None, name=None, **kw) -> tuple[UserAccount, Staff]:
        u = self.user(*roles, name=name, **kw)
        s = Staff(user_id=u.user_id, department_id=dept.department_id if dept else None, short_code=short_code)
        self.db.add(s)
        self.db.commit()
        return u, s

    def student(self, dept: Department, year: AcademicYear, batch: Batch | None, uid=None, **kw) -> tuple[UserAccount, Student]:
        u = self.user(RoleCode.STUDENT, **kw)
        st = Student(user_id=u.user_id, uid=uid or f"UID{self._n}", department_id=dept.department_id)
        self.db.add(st)
        self.db.flush()
        self.db.add(StudentAcademicHistory(student_id=st.student_id, academic_year_id=year.academic_year_id,
                                           year_of_study=2, semester=3, department_id=dept.department_id,
                                           batch_id=batch.batch_id if batch else None, status=HistoryStatus.ACTIVE,
                                           effective_from=date(2026, 7, 1)))
        self.db.commit()
        return u, st

    @staticmethod
    def auth(user: UserAccount) -> dict:
        tok, _ = create_access_token(user.user_id, user.token_version)
        return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def f(db):
    return Factory(db)
