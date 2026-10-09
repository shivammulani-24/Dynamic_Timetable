"""DEVELOPMENT-ONLY seed built from the college's own timetable PDF. Refuses to run in production.

It reads the timetable with the normal extraction pipeline and creates the master data that the
document itself names, so the app can be tried end to end with real classes:

* department "CE"; academic year 2026-2027 (ACTIVE) — from the PDF's "AY 2026-27"
* batches: every class/division on the pages (SE/TE/BE A–D), every lab sub-group that appears
  (SE-A1 …), a parent "BE" batch for the combined BE A–D page, and "MTECH"
* courses: every subject in the page legends, plus codes printed without a legend entry (kept as
  printed, e.g. "LA", "MDM Lab")
* staff: every faculty code in the legends (name as printed) plus codes used without a legend
  entry; SND is the HOD (the PDF's "Head of The Department" signature)
* rooms: every room label printed; the floor is taken from the room number's hundreds digit
  (508 → 5, 002 → 0). That numbering rule is an ASSUMPTION for development only — correct the
  floors in Admin → Rooms if your building differs.
* demo login accounts (password below) and the PDF uploaded + activated as the official timetable.

Usage:
    python -m app.seed_college --reset                 # DROP everything, migrate, seed from the PDF
    python -m app.seed_college --reset --pdf other.pdf
"""
from __future__ import annotations

import argparse
import os
import re
from datetime import date, time

from sqlalchemy import select

from app.enums import AccountStatus, Domain, HistoryStatus, RoleCode, VerificationStatus
from app.extraction.pipeline import run_extraction
from app.models import (
    AcademicYear,
    Batch,
    Course,
    Department,
    InstitutionalTimetableEntry,
    InstitutionConfig,
    Role,
    Room,
    Staff,
    Student,
    StudentAcademicHistory,
    UserAccount,
    UserPreference,
    UserRole,
)
from app.security.passwords import hash_password
from app.security.principal import load_principal
from app.seed import DEMO_PASSWORD, DOMAIN, _guard, reset_database
from app.services.mapping import GROUP_SUFFIX, course_keys
from app.services.matching import normalize_label

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PDF = os.path.join(HERE, "tests", "fixtures", "reference", "college_timetable.pdf")
YEAR_OF = {"FE": 1, "SE": 2, "TE": 3, "BE": 4, "MTECH": 1}
HOD_CODE = "SND"

DEMO_STUDENTS = [  # (login, batch)
    ("se.a1", "SE-A1"), ("se.a2", "SE-A2"), ("se.b1", "SE-B1"), ("se.c3", "SE-C3"), ("se.d4", "SE-D4"),
    ("te.a1", "TE-A1"), ("te.b2", "TE-B2"), ("te.c1", "TE-C1"), ("te.d3", "TE-D3"),
    ("be.a", "BE-A"), ("be.c", "BE-C"), ("mtech", "MTECH"), ("newbie", None),
]


def _floor(room: str) -> str | None:
    m = re.search(r"(?<!\d)(\d)\d\d(?!\d)", room)
    return m.group(1) if m else None


def seed(pdf_path: str) -> dict:
    from app.db import session_factory
    from app.services.timetables import set_primary
    from app.services.uploads import create_upload
    from app.worker import drain

    _guard()
    data = open(pdf_path, "rb").read()
    result = run_extraction(data, "PDF", require_scope=True)
    classes = [e for e in result.entries if e.entry_kind == "CLASS"]

    with session_factory()() as db:
        if db.scalar(select(UserAccount).where(UserAccount.college_email == f"admin@{DOMAIN}")):
            raise SystemExit("Seed data already present. Use --reset to start over.")
        roles = {RoleCode(r.code): r.role_id for r in db.scalars(select(Role))}
        cfg = db.get(InstitutionConfig, 1)
        cfg.institution_name = "College timetable (development seed)"
        cfg.week_start_day = 1
        cfg.working_hours_start, cfg.working_hours_end = time(9, 0), time(18, 15)
        cfg.lunch_boundary = None  # lunch differs by year; each section's own LONG BREAK is used

        ay_label = result.academic_year_label or "2026-2027"
        y0 = int(ay_label[:4])
        ay_old = AcademicYear(label=f"{y0 - 1}-{y0}", start_date=date(y0 - 1, 7, 1), end_date=date(y0, 6, 30), status="CLOSED")
        ay = AcademicYear(label=ay_label, start_date=date(y0, 7, 1), end_date=date(y0 + 1, 6, 30), status="ACTIVE")
        ce = Department(code="CE", name="Computer Engineering")
        db.add_all([ay_old, ay, ce])
        db.flush()

        # ---------------------------------------------------------------- batches
        batches: dict[str, Batch] = {}

        def batch(code: str, level: str, division: str, parent: Batch | None = None) -> Batch:
            year = YEAR_OF.get(level, 1)
            b = Batch(department_id=ce.department_id, code=code, cohort_label=f"{level}-{y0 + 1 + 4 - year}",
                      division_label=division, program_year=year, parent_batch_id=parent.batch_id if parent else None)
            db.add(b)
            db.flush()
            batches[code] = b
            return b

        for s in result.sections:
            lvl = s.program_level
            if not lvl:
                continue
            if not s.divisions:
                if lvl not in batches:
                    batch(lvl, lvl, "ALL")
                continue
            parent = None
            if len(s.divisions) > 1:  # combined page (BE A–D): one parent shared by those divisions
                parent = batches.get(lvl) or batch(lvl, lvl, "ALL")
            for d in s.divisions:
                if f"{lvl}-{d}" not in batches:
                    batch(f"{lvl}-{d}", lvl, d, parent)
        for e in classes:
            m = re.fullmatch(r"([A-Z]+)-([A-H])([1-9])", e.batch_label or "")
            if m and e.batch_label not in batches and f"{m[1]}-{m[2]}" in batches:
                batch(e.batch_label, m[1], m[2] + m[3], batches[f"{m[1]}-{m[2]}"])

        # ---------------------------------------------------------------- courses
        course_index: dict[str, Course] = {}

        def course(code: str, name: str) -> None:
            key = normalize_label(code)
            if not key or key in course_index:
                return
            c = Course(department_id=ce.department_id, course_code=code[:40], name=name[:160])
            db.add(c)
            course_index[key] = c
            course_index.setdefault(normalize_label(name), c)

        for s in result.sections:
            for code, name in s.legend.get("subject", {}).items():
                course(code, name)
        for e in classes:
            if e.course_label and not any(k in course_index for k in course_keys(e)):
                printed = GROUP_SUFFIX.sub("", e.course_label).strip()
                course(printed, printed)

        # ---------------------------------------------------------------- staff
        def account(login: str, name: str, *role_codes: RoleCode) -> UserAccount:
            u = UserAccount(college_email=f"{login}@{DOMAIN}", display_name=name[:120],
                            password_hash=hash_password(DEMO_PASSWORD), account_status=AccountStatus.ACTIVE,
                            timezone_id="Asia/Kolkata")
            db.add(u)
            db.flush()
            for r in role_codes:
                db.add(UserRole(user_id=u.user_id, role_id=roles[r]))
            db.add(UserPreference(user_id=u.user_id))
            return u

        admin = account("admin", "Admin (dev seed)", RoleCode.ADMIN)
        admin_staff = Staff(user_id=admin.user_id, designation="Timetable office")
        db.add(admin_staff)
        db.add(Staff(user_id=account("principal", "Principal (dev seed)", RoleCode.PRINCIPAL).user_id, designation="Principal"))

        faculty: dict[str, str] = {}
        for s in result.sections:
            for code, name in s.legend.get("faculty", {}).items():
                faculty.setdefault(code, name)
        for e in classes:
            for code in (e.staff_label or "").split("+"):
                if code and code not in faculty:
                    faculty[code] = f"{code} (not in the timetable legend)"
        for code, name in sorted(faculty.items()):
            if not re.fullmatch(r"[A-Z][A-Z0-9]{0,9}", code):
                continue
            rc = (RoleCode.HOD, RoleCode.PROFESSOR) if code == HOD_CODE else (RoleCode.PROFESSOR,)
            u = account(code.lower(), name, *rc)
            db.add(Staff(user_id=u.user_id, department_id=ce.department_id, short_code=code,
                         designation="Head of Department" if code == HOD_CODE else "Faculty"))

        # ---------------------------------------------------------------- rooms
        rooms: set[str] = set()
        for e in classes:
            r = e.room_label
            if r and normalize_label(r) not in rooms:
                rooms.add(normalize_label(r))
                lab = bool(re.search(r"\blab\b|-\d$", r, re.I)) or "lab" in (e.course_label or "").lower()
                db.add(Room(room_code=r[:40], building="Main Building", floor_label=_floor(r),
                            room_type="LAB" if lab else "CLASSROOM"))

        # ---------------------------------------------------------------- demo students
        for login, code in DEMO_STUDENTS:
            if code and code not in batches:
                continue
            u = account(f"student.{login}", f"Demo student ({code or 'no batch yet'})", RoleCode.STUDENT)
            st = Student(user_id=u.user_id, uid=f"DEV-{login.upper()}", department_id=ce.department_id)
            db.add(st)
            db.flush()
            b = batches.get(code) if code else None
            db.add(StudentAcademicHistory(student_id=st.student_id, academic_year_id=ay.academic_year_id,
                                          year_of_study=b.program_year if b else 2, semester=3 if not b else b.program_year * 2 - 1,
                                          department_id=ce.department_id, batch_id=b.batch_id if b else None,
                                          status=HistoryStatus.ACTIVE, effective_from=date(y0, 7, 1),
                                          confirmed_by_staff_id=admin_staff.staff_id))
        db.commit()

        # ---------------------------------------------------------------- the timetable itself
        ap = load_principal(db, admin)
        tt, _, _, _ = create_upload(db, ap, Domain.INSTITUTIONAL, data, os.path.basename(pdf_path),
                                    f"CE timetable AY {ay_label} (from {os.path.basename(pdf_path)})",
                                    ay.academic_year_id, ce.department_id)
        drain()
        db.expire_all()
        set_primary(db, ap, Domain.INSTITUTIONAL, tt.timetable_id)
        db.commit()
        counts: dict[str, int] = {}
        for (st,) in db.execute(select(InstitutionalTimetableEntry.verification_status).where(
                InstitutionalTimetableEntry.timetable_id == tt.timetable_id,
                InstitutionalTimetableEntry.entry_kind == "CLASS")):
            counts[st] = counts.get(st, 0) + 1
        return {"timetable_id": tt.timetable_id, "counts": counts, "staff": len(faculty), "rooms": len(rooms),
                "courses": len({id(c) for c in course_index.values()}), "batches": len(batches)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="drop and recreate the schema first (DESTROYS DATA)")
    ap.add_argument("--pdf", default=DEFAULT_PDF, help="timetable PDF to load (default: the college reference PDF)")
    args = ap.parse_args()
    _guard()
    if args.reset:
        reset_database()
    info = seed(args.pdf)
    verified = info["counts"].get(VerificationStatus.VERIFIED, 0)
    total = sum(info["counts"].values())
    print(f"Loaded {args.pdf}: {total} classes ({verified} verified) — statuses {info['counts']}")
    print(f"Master data: {info['batches']} batches, {info['courses']} courses, {info['staff']} faculty, {info['rooms']} rooms.")
    print(f"Accounts (password {DEMO_PASSWORD!r}, development only):")
    print(f"  admin@{DOMAIN}            Admin")
    print(f"  principal@{DOMAIN}        Principal")
    print(f"  snd@{DOMAIN}              HOD + Professor (SND)   — every faculty code works: kkd@, avn@, js@ …")
    for login, code in DEMO_STUDENTS:
        print(f"  student.{login}@{DOMAIN}".ljust(34) + f"Student {code or '(no batch yet)'}")


if __name__ == "__main__":
    main()
