"""SQLAlchemy models — implements Database Schema Specification V1 (+ documented additions).

Institutional and personal timetables live in separate metadata and entry tables. Shared
column definitions are declared once in mixins, but each domain has its own physical tables,
so no query can accidentally mix them.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.db import Base
from app.enums import (
    AcademicYearStatus,
    AccountStatus,
    AliasEntity,
    Domain,
    EntryKind,
    HistoryStatus,
    JobStatus,
    ProcessingStatus,
    RoleCode,
    SelectionMode,
    StaffStatus,
    StudentStatus,
    TokenPurpose,
    VerificationStatus,
    check_in,
)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def _now_col(**kw: Any) -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), **kw)


# --------------------------------------------------------------------------- identity


class Role(Base):
    __tablename__ = "role"
    __table_args__ = (CheckConstraint(check_in("code", RoleCode), name="ck_role_code"),)

    role_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False)


class UserAccount(Base):
    __tablename__ = "user_account"
    __table_args__ = (
        CheckConstraint(check_in("account_status", AccountStatus), name="ck_user_status"),
        CheckConstraint("college_email = lower(college_email)", name="ck_user_email_normalized"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    college_email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    auth_subject: Mapped[str | None] = mapped_column(String(255), unique=True)
    timezone_id: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Asia/Kolkata")
    account_status: Mapped[str] = mapped_column(String(20), nullable=False, default=AccountStatus.INVITED)
    # Incremented on suspension/password change/logout-all: invalidates outstanding access tokens.
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = _now_col(onupdate=func.now())

    roles: Mapped[list["UserRole"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", foreign_keys="UserRole.user_id"
    )
    student: Mapped["Student | None"] = relationship(back_populates="user", uselist=False)
    staff: Mapped["Staff | None"] = relationship(back_populates="user", uselist=False)


class UserRole(Base):
    __tablename__ = "user_role"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.user_id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("role.role_id"), primary_key=True)
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.user_id")
    )
    assigned_at: Mapped[datetime] = _now_col()

    user: Mapped[UserAccount] = relationship(back_populates="roles", foreign_keys=[user_id])
    role: Mapped[Role] = relationship(lazy="joined")


class RefreshToken(Base):
    __tablename__ = "refresh_token"
    __table_args__ = (Index("ix_refresh_user", "user_id"),)

    token_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.user_id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    issued_at: Mapped[datetime] = _now_col()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    device_label: Mapped[str | None] = mapped_column(String(120))


class AccountToken(Base):
    """Single-use invitation / password-reset tokens (only a SHA-256 hash is stored)."""

    __tablename__ = "account_token"
    __table_args__ = (CheckConstraint(check_in("purpose", TokenPurpose), name="ck_token_purpose"),)

    token_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.user_id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(24), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now_col()


# --------------------------------------------------------------------------- academics


class Department(Base):
    __tablename__ = "department"

    department_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)


class AcademicYear(Base):
    __tablename__ = "academic_year"
    __table_args__ = (
        CheckConstraint("end_date >= start_date", name="ck_ay_dates"),
        CheckConstraint(check_in("status", AcademicYearStatus), name="ck_ay_status"),
        # The institution permits only one ACTIVE academic year at a time.
        Index("uq_ay_single_active", "status", unique=True, postgresql_where=text("status = 'ACTIVE'")),
    )

    academic_year_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    label: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=AcademicYearStatus.PLANNED)
    created_at: Mapped[datetime] = _now_col()


class Staff(Base):
    __tablename__ = "staff"
    __table_args__ = (CheckConstraint(check_in("staff_status", StaffStatus), name="ck_staff_status"),)

    staff_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.user_id"), unique=True, nullable=False
    )
    staff_status: Mapped[str] = mapped_column(String(24), nullable=False, default=StaffStatus.ACTIVE)
    department_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("department.department_id"))
    # Short code used in timetable legends (e.g. "KKD"); optional, also resolvable via ENTITY_ALIAS.
    short_code: Mapped[str | None] = mapped_column(String(20))
    designation: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = _now_col()

    user: Mapped[UserAccount] = relationship(back_populates="staff")
    department: Mapped[Department | None] = relationship()


class Student(Base):
    __tablename__ = "student"
    __table_args__ = (CheckConstraint(check_in("student_status", StudentStatus), name="ck_student_status"),)

    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.user_id"), unique=True, nullable=False
    )
    uid: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    department_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("department.department_id"))
    student_status: Mapped[str] = mapped_column(String(24), nullable=False, default=StudentStatus.ACTIVE)
    created_at: Mapped[datetime] = _now_col()

    user: Mapped[UserAccount] = relationship(back_populates="student")
    history: Mapped[list["StudentAcademicHistory"]] = relationship(
        back_populates="student", order_by="StudentAcademicHistory.effective_from.desc()"
    )


class Batch(Base):
    __tablename__ = "batch"
    __table_args__ = (
        UniqueConstraint("department_id", "cohort_label", "division_label", name="uq_batch_cohort_div"),
        UniqueConstraint("department_id", "code", name="uq_batch_code"),
        CheckConstraint("program_year > 0", name="ck_batch_year"),
        CheckConstraint("parent_batch_id IS NULL OR parent_batch_id <> batch_id", name="ck_batch_parent"),
    )

    batch_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    department_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("department.department_id"), nullable=False)
    # Addition (C-05): human label used in timetables, e.g. "SE-A" or "SE-A1".
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    cohort_label: Mapped[str] = mapped_column(String(40), nullable=False)
    division_label: Mapped[str] = mapped_column(String(20), nullable=False)
    program_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Addition (C-05): lab sub-group (A1) -> division (A); students in A1 also attend A's classes.
    parent_batch_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("batch.batch_id"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)

    department: Mapped[Department] = relationship()
    parent: Mapped["Batch | None"] = relationship(remote_side=[batch_id])


class StudentAcademicHistory(Base):
    __tablename__ = "student_academic_history"
    __table_args__ = (
        CheckConstraint("year_of_study > 0", name="ck_sah_year"),
        CheckConstraint("semester IS NULL OR semester > 0", name="ck_sah_sem"),
        CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_sah_dates"),
        CheckConstraint(check_in("status", HistoryStatus), name="ck_sah_status"),
        Index("ix_sah_student_from", "student_id", text("effective_from DESC")),
        # At most one open placement per student (partial unique index).
        Index(
            "uq_sah_one_open",
            "student_id",
            unique=True,
            postgresql_where=text("effective_to IS NULL"),
        ),
    )

    history_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("student.student_id"), nullable=False)
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_year.academic_year_id"), nullable=False
    )
    year_of_study: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    semester: Mapped[int | None] = mapped_column(SmallInteger)
    department_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("department.department_id"), nullable=False)
    batch_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("batch.batch_id"))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    confirmed_by_staff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("staff.staff_id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _now_col()

    student: Mapped[Student] = relationship(back_populates="history")
    academic_year: Mapped[AcademicYear] = relationship()
    department: Mapped[Department] = relationship()
    batch: Mapped[Batch | None] = relationship()


class Course(Base):
    __tablename__ = "course"

    course_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    department_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("department.department_id"))
    course_code: Mapped[str | None] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)


class Room(Base):
    __tablename__ = "room"
    __table_args__ = (CheckConstraint("capacity IS NULL OR capacity > 0", name="ck_room_capacity"),)

    room_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    room_code: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    building: Mapped[str | None] = mapped_column(String(100))
    floor_label: Mapped[str | None] = mapped_column(String(40))
    room_type: Mapped[str | None] = mapped_column(String(40))
    capacity: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)


class EntityAlias(Base):
    """Editable alias dictionary (Intent spec §5.3). entity_id is text to hold BIGINT or UUID ids."""

    __tablename__ = "entity_alias"
    __table_args__ = (
        CheckConstraint(check_in("entity_type", AliasEntity), name="ck_alias_type"),
        UniqueConstraint("entity_type", "alias_normalized", "entity_id", name="uq_alias"),
        Index("ix_alias_lookup", "entity_type", "alias_normalized"),
    )

    alias_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    alias: Mapped[str] = mapped_column(String(120), nullable=False)
    alias_normalized: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user_account.user_id"))
    created_at: Mapped[datetime] = _now_col()


class InstitutionConfig(Base):
    """Single-row institution-wide configuration. Nullable values mean 'not configured'."""

    __tablename__ = "institution_config"
    __table_args__ = (
        CheckConstraint("config_id = 1", name="ck_config_single_row"),
        CheckConstraint("week_start_day IS NULL OR week_start_day BETWEEN 1 AND 7", name="ck_config_week"),
        CheckConstraint(
            "working_hours_start IS NULL OR working_hours_end IS NULL OR working_hours_end > working_hours_start",
            name="ck_config_hours",
        ),
        CheckConstraint("next_class_lookahead_days BETWEEN 0 AND 14", name="ck_config_lookahead"),
    )

    config_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    institution_name: Mapped[str | None] = mapped_column(String(200))
    week_start_day: Mapped[int | None] = mapped_column(SmallInteger)
    lunch_boundary: Mapped[time | None] = mapped_column(Time)
    working_hours_start: Mapped[time | None] = mapped_column(Time)
    working_hours_end: Mapped[time | None] = mapped_column(Time)
    next_class_lookahead_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="7", default=7)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user_account.user_id"))
    updated_at: Mapped[datetime] = _now_col(onupdate=func.now())


# --------------------------------------------------------------------------- timetable mixins


class _TimetableMeta:
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    original_file_key: Mapped[str] = mapped_column(String(500), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_format: Mapped[str] = mapped_column(String(16), nullable=False)  # PDF, XLSX, DOCX, IMAGE, ...
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_at: Mapped[datetime] = _now_col()
    processing_status: Mapped[str] = mapped_column(String(24), nullable=False, default=ProcessingStatus.QUEUED)
    validation_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}", default=dict)
    parser_version: Mapped[str | None] = mapped_column(String(80))
    page_count: Mapped[int | None] = mapped_column(Integer)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    effective_from_raw: Mapped[str | None] = mapped_column(String(120))
    term_label: Mapped[str | None] = mapped_column(String(80))
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_request_id: Mapped[str | None] = mapped_column(String(64))
    # Bumped whenever entries change (review/correction); used for client cache invalidation.
    data_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)
    created_at: Mapped[datetime] = _now_col()


class _SectionCols:
    section_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    source_page: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str | None] = mapped_column(String(300))
    program_level: Mapped[str | None] = mapped_column(String(40))   # SE / TE / BE / FE
    divisions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]", default=list)
    is_tentative: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    header_raw: Mapped[str | None] = mapped_column(Text)
    legend: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}", default=dict)
    extraction_method: Mapped[str] = mapped_column(String(20), nullable=False, default="TEXT")


class _EntryCols:
    entry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    entry_kind: Mapped[str] = mapped_column(String(16), nullable=False, default=EntryKind.CLASS)
    day_of_week: Mapped[int | None] = mapped_column(SmallInteger)
    class_date: Mapped[date | None] = mapped_column(Date)
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    time_label_raw: Mapped[str | None] = mapped_column(String(120))
    course_name_resolved: Mapped[str | None] = mapped_column(String(200))
    staff_name_resolved: Mapped[str | None] = mapped_column(String(200))
    raw_extracted_text: Mapped[str | None] = mapped_column(Text)
    source_page: Mapped[int | None] = mapped_column(Integer)
    source_region: Mapped[dict | None] = mapped_column(JSONB)
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    verification_status: Mapped[str] = mapped_column(String(24), nullable=False)
    validation_messages: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]", default=list)
    is_tentative: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    extraction_method: Mapped[str] = mapped_column(String(20), nullable=False, default="TEXT")
    is_corrected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    created_at: Mapped[datetime] = _now_col()
    updated_at: Mapped[datetime] = _now_col(onupdate=func.now())


def _entry_checks(prefix: str) -> tuple:
    return (
        CheckConstraint("day_of_week IS NULL OR day_of_week BETWEEN 1 AND 7", name=f"ck_{prefix}_dow"),
        CheckConstraint(
            "start_time IS NULL OR end_time IS NULL OR end_time > start_time", name=f"ck_{prefix}_times"
        ),
        CheckConstraint("source_page IS NULL OR source_page > 0", name=f"ck_{prefix}_page"),
        CheckConstraint(
            "confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)",
            name=f"ck_{prefix}_conf",
        ),
        CheckConstraint(check_in("verification_status", VerificationStatus), name=f"ck_{prefix}_vstatus"),
        CheckConstraint(check_in("entry_kind", EntryKind), name=f"ck_{prefix}_kind"),
    )


# --------------------------------------------------------------------------- institutional domain


class InstitutionalTimetable(_TimetableMeta, Base):
    __tablename__ = "institutional_timetable"
    __table_args__ = (
        CheckConstraint(check_in("processing_status", ProcessingStatus), name="ck_itt_status"),
        Index("ix_itt_year_uploaded", "academic_year_id", text("uploaded_at DESC")),
        Index("ix_itt_status", "processing_status"),
        Index(
            "uq_itt_client_req", "uploaded_by_user_id", "client_request_id", unique=True,
            postgresql_where=text("client_request_id IS NOT NULL"),
        ),
    )

    timetable_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    academic_year_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("academic_year.academic_year_id"), nullable=False
    )
    department_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("department.department_id"))
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.user_id"), nullable=False
    )

    academic_year: Mapped[AcademicYear] = relationship()
    department: Mapped[Department | None] = relationship()


class InstitutionalTimetableSection(_SectionCols, Base):
    __tablename__ = "institutional_timetable_section"

    timetable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institutional_timetable.timetable_id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


class InstitutionalTimetableEntry(_EntryCols, Base):
    __tablename__ = "institutional_timetable_entry"

    @declared_attr.directive
    def __table_args__(cls) -> tuple:  # noqa: N805
        return _entry_checks("ite") + (
            Index("ix_ite_tt_dow_start", "timetable_id", "day_of_week", "start_time"),
            Index("ix_ite_tt_date_start", "timetable_id", "class_date", "start_time"),
            Index("ix_ite_tt_course", "timetable_id", "course_id"),
            Index("ix_ite_tt_batch", "timetable_id", "batch_id"),
            Index("ix_ite_tt_staff", "timetable_id", "staff_id"),
            Index("ix_ite_tt_room", "timetable_id", "room_id"),
        )

    timetable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institutional_timetable.timetable_id", ondelete="RESTRICT"),
        nullable=False,
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutional_timetable_section.section_id")
    )
    course_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("course.course_id"))
    batch_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("batch.batch_id"))
    staff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("staff.staff_id"))
    room_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("room.room_id"))
    course_label_raw: Mapped[str | None] = mapped_column(String(200))
    batch_label_raw: Mapped[str | None] = mapped_column(String(100))
    staff_label_raw: Mapped[str | None] = mapped_column(String(200))
    room_label_raw: Mapped[str | None] = mapped_column(String(100))

    course: Mapped[Course | None] = relationship(lazy="joined")
    batch: Mapped[Batch | None] = relationship(lazy="joined")
    staff: Mapped[Staff | None] = relationship(lazy="joined")
    room: Mapped[Room | None] = relationship(lazy="joined")
    section: Mapped[InstitutionalTimetableSection | None] = relationship(lazy="joined")


class InstitutionalTimetableSettings(Base):
    __tablename__ = "institutional_timetable_settings"
    __table_args__ = (CheckConstraint("settings_id = 1", name="ck_its_single_row"),)

    settings_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    default_timetable_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutional_timetable.timetable_id")
    )
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user_account.user_id"))
    updated_at: Mapped[datetime] = _now_col(onupdate=func.now())
    # Monotonic version; clients compare it to detect that the official default changed.
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", default=1)


# --------------------------------------------------------------------------- personal domain


class PersonalTimetable(_TimetableMeta, Base):
    __tablename__ = "personal_timetable"
    __table_args__ = (
        CheckConstraint(check_in("processing_status", ProcessingStatus), name="ck_ptt_status"),
        Index("ix_ptt_owner_uploaded", "owner_user_id", text("uploaded_at DESC")),
        Index("ix_ptt_status", "processing_status"),
        # Composite target for the owner-checked FK on user_preference.
        UniqueConstraint("timetable_id", "owner_user_id", name="uq_ptt_id_owner"),
        Index(
            "uq_ptt_client_req", "owner_user_id", "client_request_id", unique=True,
            postgresql_where=text("client_request_id IS NOT NULL"),
        ),
    )

    timetable_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.user_id"), nullable=False
    )


class PersonalTimetableSection(_SectionCols, Base):
    __tablename__ = "personal_timetable_section"

    timetable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("personal_timetable.timetable_id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )


class PersonalTimetableEntry(_EntryCols, Base):
    __tablename__ = "personal_timetable_entry"

    @declared_attr.directive
    def __table_args__(cls) -> tuple:  # noqa: N805
        return _entry_checks("pte") + (
            Index("ix_pte_tt_dow_start", "timetable_id", "day_of_week", "start_time"),
            Index("ix_pte_tt_date_start", "timetable_id", "class_date", "start_time"),
        )

    timetable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("personal_timetable.timetable_id", ondelete="RESTRICT"), nullable=False
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("personal_timetable_section.section_id")
    )
    course_label: Mapped[str | None] = mapped_column(String(200))
    batch_label: Mapped[str | None] = mapped_column(String(100))
    professor_label: Mapped[str | None] = mapped_column(String(200))
    room_label: Mapped[str | None] = mapped_column(String(100))

    section: Mapped[PersonalTimetableSection | None] = relationship(lazy="joined")


class UserPreference(Base):
    __tablename__ = "user_preference"
    __table_args__ = (
        CheckConstraint(check_in("selection_mode", SelectionMode), name="ck_pref_mode"),
        CheckConstraint(
            "last_active_domain IS NULL OR " + check_in("last_active_domain", Domain), name="ck_pref_domain"
        ),
        # Composite FKs guarantee that a referenced personal timetable belongs to this same user.
        ForeignKeyConstraint(
            ["personal_primary_timetable_id", "user_id"],
            ["personal_timetable.timetable_id", "personal_timetable.owner_user_id"],
            name="fk_pref_primary_owned",
        ),
        ForeignKeyConstraint(
            ["last_personal_timetable_id", "user_id"],
            ["personal_timetable.timetable_id", "personal_timetable.owner_user_id"],
            name="fk_pref_last_personal_owned",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.user_id", ondelete="CASCADE"), primary_key=True
    )
    personal_primary_timetable_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    selection_mode: Mapped[str] = mapped_column(
        String(24), nullable=False, default=SelectionMode.REMEMBER_LAST, server_default="REMEMBER_LAST"
    )
    last_active_domain: Mapped[str | None] = mapped_column(String(20))
    last_personal_timetable_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    last_institutional_timetable_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutional_timetable.timetable_id")
    )
    notify_official_timetable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    notify_processing: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    search_history_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"), default=True)
    theme: Mapped[str] = mapped_column(String(10), nullable=False, server_default="system", default="system")
    time_format_24h: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"), default=False)
    updated_at: Mapped[datetime] = _now_col(onupdate=func.now())


# --------------------------------------------------------------------------- processing


class ProcessingJob(Base):
    """One extraction job. Exactly one of the two domain FKs is set, matching `domain`."""

    __tablename__ = "processing_job"
    __table_args__ = (
        CheckConstraint(check_in("status", JobStatus), name="ck_job_status"),
        CheckConstraint(check_in("domain", Domain), name="ck_job_domain"),
        CheckConstraint(
            "(domain = 'INSTITUTIONAL' AND institutional_timetable_id IS NOT NULL AND personal_timetable_id IS NULL)"
            " OR (domain = 'PERSONAL' AND personal_timetable_id IS NOT NULL AND institutional_timetable_id IS NULL)",
            name="ck_job_one_target",
        ),
        Index("ix_job_status_created", "status", "created_at"),
        Index("ix_job_requested_by", "requested_by_user_id", text("created_at DESC")),
    )

    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    domain: Mapped[str] = mapped_column(String(20), nullable=False)
    institutional_timetable_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutional_timetable.timetable_id")
    )
    personal_timetable_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("personal_timetable.timetable_id")
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.user_id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=JobStatus.QUEUED)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3", default=3)
    worker_id: Mapped[str | None] = mapped_column(String(80))
    error_code: Mapped[str | None] = mapped_column(String(60))
    error_message: Mapped[str | None] = mapped_column(String(500))
    progress: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}", default=dict)
    created_at: Mapped[datetime] = _now_col()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ValidationFinding(Base):
    __tablename__ = "validation_finding"
    __table_args__ = (
        CheckConstraint(check_in("domain", Domain), name="ck_vf_domain"),
        CheckConstraint(
            "severity IN ('BLOCKING','PAGE_ERROR','CRITICAL','WARNING','INFO','SECTION_FLAG','METADATA_WARNING')",
            name="ck_vf_severity",
        ),
        CheckConstraint(
            "(domain = 'INSTITUTIONAL' AND institutional_timetable_id IS NOT NULL AND personal_timetable_id IS NULL)"
            " OR (domain = 'PERSONAL' AND personal_timetable_id IS NOT NULL AND institutional_timetable_id IS NULL)",
            name="ck_vf_one_target",
        ),
        Index("ix_vf_itt", "institutional_timetable_id"),
        Index("ix_vf_ptt", "personal_timetable_id"),
    )

    finding_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    domain: Mapped[str] = mapped_column(String(20), nullable=False)
    institutional_timetable_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutional_timetable.timetable_id")
    )
    personal_timetable_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("personal_timetable.timetable_id")
    )
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    code: Mapped[str] = mapped_column(String(60), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    source_page: Mapped[int | None] = mapped_column(Integer)
    entry_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}", default=dict)
    created_at: Mapped[datetime] = _now_col()


class EntryCorrection(Base):
    """Auditable correction of an extracted entry; original values are preserved in `before`."""

    __tablename__ = "entry_correction"
    __table_args__ = (
        CheckConstraint(check_in("domain", Domain), name="ck_ec_domain"),
        CheckConstraint(
            "(domain = 'INSTITUTIONAL' AND institutional_entry_id IS NOT NULL AND personal_entry_id IS NULL)"
            " OR (domain = 'PERSONAL' AND personal_entry_id IS NOT NULL AND institutional_entry_id IS NULL)",
            name="ck_ec_one_target",
        ),
    )

    correction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    domain: Mapped[str] = mapped_column(String(20), nullable=False)
    institutional_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institutional_timetable_entry.entry_id"), index=True
    )
    personal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("personal_timetable_entry.entry_id"), index=True
    )
    corrected_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.user_id"), nullable=False
    )
    corrected_at: Mapped[datetime] = _now_col()
    before: Mapped[dict] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300))


# --------------------------------------------------------------------------- audit / notifications / search


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_occurred", text("occurred_at DESC")),
        Index("ix_audit_actor", "actor_user_id", text("occurred_at DESC")),
    )

    audit_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user_account.user_id"))
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(80))
    target_id: Mapped[str | None] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = _now_col()
    request_id: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}", default=dict)


class Notification(Base):
    __tablename__ = "notification"
    __table_args__ = (Index("ix_notif_user_created", "user_id", text("created_at DESC")),)

    notification_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.user_id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(String(1000), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}", default=dict)
    created_at: Mapped[datetime] = _now_col()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PushDevice(Base):
    __tablename__ = "push_device"

    device_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    expo_push_token: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = _now_col()
    last_seen_at: Mapped[datetime] = _now_col()


class SavedSearch(Base):
    """Stores intent + typed parameters (never a timetable/domain/user) — re-run in current context."""

    __tablename__ = "saved_search"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_saved_search_name"),)

    saved_search_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    query_text: Mapped[str | None] = mapped_column(String(300))
    intent: Mapped[str | None] = mapped_column(String(40))
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}", default=dict)
    created_at: Mapped[datetime] = _now_col()


class SearchHistory(Base):
    __tablename__ = "search_history"
    __table_args__ = (Index("ix_sh_user_created", "user_id", text("created_at DESC")),)

    search_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_account.user_id", ondelete="CASCADE"), nullable=False
    )
    query_text: Mapped[str] = mapped_column(String(300), nullable=False)
    intent: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    domain: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _now_col()
