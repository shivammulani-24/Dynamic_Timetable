# Phase 1 — Requirements, Architecture and Decisions

Sources inspected (primary source of truth):

| Ref | Document |
|-----|----------|
| SRS | Role-Based Dynamic Timetable Monitoring System — SRS Working Draft: Data Model & Search Foundation v0.1 |
| DB  | Database Schema Specification V1 |
| API | API Contract and Approved Query Templates V1 |
| PDF | PDF Extraction and Validation Specification V1 |
| INT | Intent and Entity Schema V1 (Updated) |

The "Phase 1 and 2" document referred to in the master prompt was **not supplied** in this
session. Nothing in this implementation depends on it; if it is provided later it must be
reconciled against this file.

---

## 1. Functional requirements checklist

| ID | Requirement | Source | Implemented in |
|----|-------------|--------|----------------|
| FR-01 | Common `USER_ACCOUNT` identity with separate `STUDENT` / `STAFF` profiles | DB §1, §3.2–3.5 | `backend/app/models.py` |
| FR-02 | Roles STUDENT, PROFESSOR, HOD, PRINCIPAL, ADMIN via `USER_ROLE`; never from client | DB §3.1, §3.3; API §2 | `app/security/deps.py` |
| FR-03 | Admin-confirmed student promotion, transactional, historised | SRS §2, §3.2; DB §6.4 | `app/services/academics.py` |
| FR-04 | Fresher registration without duplicating existing students | SRS §2 | `POST /admin/students` (UID + email unique) |
| FR-05 | Separate institutional and personal metadata + entry tables | SRS §3.3–3.4; DB §3.12–3.15 | models + `services/timetables.py` |
| FR-06 | Upload never changes primary; primary is a separate action | SRS §4; DB §6.1 | `services/uploads.py` |
| FR-07 | Institutional default: single-row settings, Admin only | DB §3.17, §6.3 | `services/timetables.py::set_primary` |
| FR-08 | Personal primary per user in `USER_PREFERENCE`, owner-validated | DB §3.16, §6.2 | same |
| FR-09 | Selection modes REMEMBER_LAST / ALWAYS_USE_PRIMARY persisted across logins | API §8; INT §13 | `services/context.py` |
| FR-10 | Server-resolved search context (user, role, domain, timetable, timezone, now) | API §3; INT §2 | `services/context.py` |
| FR-11 | No cross-domain search, union, or fallback; no broadening on no-match | all | query engine + tests |
| FR-12 | Same extraction pipeline for both domains; data written to domain tables | PDF §1 | `app/extraction/` |
| FR-13 | Keep raw text, page/region provenance, parser version, confidence, status | PDF §8 | entry columns |
| FR-14 | Verification states VERIFIED / UNVERIFIED / INCOMPLETE / REJECTED | PDF §5 | enum + check constraint |
| FR-15 | Processing states QUEUED / PROCESSING / NEEDS_REVIEW / READY / FAILED / UNUSABLE | DB §3.12; PDF §7 | enum + worker |
| FR-16 | Per-page legends, stacked/multi-line cells, lab subgroups, room suffixes, breaks, tentative flag | PDF §2, §4 | `extraction/grid_parser.py` |
| FR-17 | Ambiguous AM/PM never silently corrected | PDF §2, §4.2 | `extraction/timeparse.py` |
| FR-18 | OCR fallback for pages with insufficient text | PDF §3 stage 6 | `extraction/ocr.py` |
| FR-19 | Validation summary, review, auditable correction preserving originals | PDF §3 stage 14, §9 | `ENTRY_CORRECTION` table, review screens |
| FR-20 | Conflict detection: professor / room / batch overlaps on real intervals | prompt §9; PDF §6 | `services/conflicts.py` |
| FR-21 | Intent registry Q01–Q30 and template catalogue QT01–QT22 | INT §3; API §9 | `app/query/` |
| FR-22 | Clarification for ambiguous AM/PM, date, entities, missing lunch/working hours | API §12; INT §7 | `app/query/engine.py` |
| FR-23 | Response envelope + stable status codes | API §6–7 | `app/query/envelope.py` |
| FR-24 | Audit uploads, validation, default changes, promotions, access-denied events | SRS §7; API §11 | `services/audit.py` |
| FR-25 | Editable alias dictionary for course / staff / room / batch | INT §5.3 | `ENTITY_ALIAS` table + admin screen |
| FR-26 | User-supplied validated IANA timezone | INT §11 | `PATCH /me/preferences` |
| FR-27 | "Show my timetable" defaults to today | INT §13 | Q01 handler |
| FR-28 | Professor free time and room availability in V1 with prerequisites | INT §13 | Q18 / Q21 / Q22 |
| FR-29 | Multi-format input (PDF, Excel, Word, images) | **User instruction (this session)** | see Decision D-01 |

## 2. Role–permission matrix (server enforced)

`✔` allowed, `✖` denied, `scope` = data scope applied by the backend.

| Capability | STUDENT | PROFESSOR | HOD | PRINCIPAL | ADMIN |
|---|---|---|---|---|---|
| Read own profile/preferences | ✔ | ✔ | ✔ | ✔ | ✔ |
| Personal timetable upload/list/primary (own only) | ✔ | ✔ | ✔ | ✔ | ✔ |
| Read another user's personal timetable | ✖ | ✖ | ✖ | ✖ | ✖ (no app permission) |
| View institutional archives & entries | ✔ (batch scope) | ✔ (department scope + own) | ✔ (department) | ✔ (college) | ✔ (college) |
| Institutional upload / review / correction | ✖ | ✖ | ✖ | ✖ | ✔ |
| Set institutional default (activation) | ✖ | ✖ | ✖ | ✖ | ✔ |
| Conflict overview | ✖ | ✖ | ✔ (department) | ✔ | ✔ |
| Floor activity / rooms-after-time (Q23, Q25) | ✖ | ✖ | ✔ | ✔ | ✔ |
| Free-room search (Q22), room schedule (Q20/Q21/Q24) | ✔ | ✔ | ✔ | ✔ | ✔ |
| Professor free time (Q18) | ✔ (professors teaching own batch) | ✔ (department) | ✔ | ✔ | ✔ |
| Master data (departments, years, batches, courses, rooms, aliases) | ✖ | ✖ | ✖ | ✖ | ✔ |
| User/role/account-status management | ✖ | ✖ | ✖ | ✖ | ✔ |
| Student promotion | ✖ | ✖ | ✖ | ✖ | ✔ |
| Audit log | ✖ | ✖ | ✖ | ✖ | ✔ |
| Processing-job monitor | own personal jobs | own | own | own | own + institutional |

The scope rules are a **proposed default policy** (see D-09) defined in one place:
`backend/app/security/policy.py`. A user holding several roles receives the union of scopes.

## 3. Entity-relationship model

```
ROLE 1─* USER_ROLE *─1 USER_ACCOUNT 1─0..1 STUDENT 1─* STUDENT_ACADEMIC_HISTORY *─1 ACADEMIC_YEAR
                                    1─0..1 STAFF ──(confirmed_by)──┘          *─1 BATCH *─1 DEPARTMENT
                                    1─1 USER_PREFERENCE                       *─1 DEPARTMENT
                                    1─* PERSONAL_TIMETABLE 1─* PERSONAL_TIMETABLE_ENTRY
                                    1─* REFRESH_TOKEN / ACCOUNT_TOKEN / NOTIFICATION / PUSH_DEVICE
DEPARTMENT 1─* BATCH (BATCH 0..1 parent BATCH for lab sub-groups), 1─* COURSE, 1─* STAFF
ACADEMIC_YEAR 1─* INSTITUTIONAL_TIMETABLE 1─* INSTITUTIONAL_TIMETABLE_ENTRY *─0..1 COURSE/BATCH/STAFF/ROOM
INSTITUTIONAL_TIMETABLE_SETTINGS (single row) ─0..1 INSTITUTIONAL_TIMETABLE (default)
INSTITUTION_CONFIG (single row: week start, lunch boundary, working hours, next-class look-ahead)
PROCESSING_JOB *─1 (institutional | personal) timetable  [domain + timetable_id, never joined across]
TIMETABLE_SECTION *─1 timetable (per domain table)  — page/section provenance, tentative flag
ENTRY_CORRECTION — auditable before/after of institutional entry corrections
ENTITY_ALIAS — alias dictionary (COURSE/STAFF/ROOM/BATCH)
AUDIT_EVENT, SAVED_SEARCH, SEARCH_HISTORY
```

## 4. Conflicts between documents and the master prompt — resolutions

| # | Conflict | Resolution implemented |
|---|----------|------------------------|
| C-01 | All docs: **PDF only** in V1. User (this session): "allow pdfs, excel, jpg, doc". | User instruction wins for this build. PDF remains the reference path (geometry-aware). XLSX/XLS/CSV, DOCX/DOC and JPG/PNG are converted to the **same intermediate grid** and go through the same normalisation, validation and status pipeline. `.xls`/`.doc` are converted with LibreOffice headless; images use Tesseract OCR and all OCR-derived entries are capped at `UNVERIFIED`. |
| C-02 | Prompt status list has `UPLOADED`; DB/PDF specs use `QUEUED`. | Use the spec enum: `QUEUED, PROCESSING, NEEDS_REVIEW, READY, FAILED, UNUSABLE`. |
| C-03 | DB spec verification enum lacks `REJECTED`; PDF spec defines it. | Enum = `VERIFIED, UNVERIFIED, INCOMPLETE, REJECTED`. |
| C-04 | SRS: Student/Staff ownership fields; DB: common `USER_ACCOUNT`. | DB spec (later, more specific) wins: `USER_ACCOUNT` + profiles. |
| C-05 | SRS `BATCH` has `academic_year`; DB spec says do not use academic year as cohort identity. | DB spec wins. Added `code` (e.g. `SE-A`, `SE-A1`) and nullable `parent_batch_id` so lab sub-groups (A1) inherit division-level (A) classes. |
| C-06 | Intents without explicit templates (Q01, Q05, Q09→QT07 only, Q11, Q13, Q26). | Q01→QT01; Q05→QT03/QT01 + batch filter; Q11→QT04 (boundary→end of day); Q13→QT04 overlap at instant; Q26→QT20 + inner template. Full map in `docs/03-query-engine.md`. |
| C-07 | QT01 lists Q14 and QT09 is for Q14. | Q14 uses QT09 (remaining after *now*); QT01 is its date source. |
| C-08 | Search preference names: SRS `REMEMBER_LAST_SELECTION/USE_DOMAIN_PRIMARY`, DB/API `REMEMBER_LAST/ALWAYS_USE_PRIMARY`. | Use DB/API names. |
| C-09 | Selection type: SRS `PRIMARY/ARCHIVE`, API/INT `PRIMARY/EXPLICIT_ARCHIVE`. | `PRIMARY/EXPLICIT_ARCHIVE`. |
| C-10 | `is_archived DEFAULT TRUE` in DB spec while timetables are also "active". | Every upload is an archive record (`is_archived` kept for spec parity and meaning "retained in archive"); soft-delete uses separate `deleted_at`. Primary status is derived only from settings/preferences. |

## 5. Decisions taken where the documents leave questions open

| # | Open item | Decision (documented default, changeable) |
|---|-----------|------------------------------------------|
| D-01 | Supported formats | See C-01. Limits: 15 MB, 30 pages (`MAX_UPLOAD_MB`, `MAX_PAGES`). |
| D-02 | Interval semantics | `start <= t < end` (start-inclusive, end-exclusive), INT §6 recommendation. |
| D-03 | Week start day | **Not assumed.** `INSTITUTION_CONFIG.week_start_day` is nullable; "this week" asks for a range until Admin configures it. Dev seed sets Monday and says so. |
| D-04 | Lunch boundary / working hours | Nullable in `INSTITUTION_CONFIG`; Q11/Q18 return `CLARIFICATION_REQUIRED` / explicit unavailable status when missing. |
| D-05 | Next-class date scope | Today's remaining entries, then following days up to `next_class_lookahead_days` (default 7 = one weekly cycle). Same rule for Q10, Q12 and the dashboard card. |
| D-06 | Recurrence model | Both: `day_of_week` (weekly recurring, ISO Mon=1) and optional `class_date`. A date query matches `class_date = d` or (`class_date IS NULL` and `day_of_week = isodow(d)`) within the timetable's `effective_from/effective_to` if set. |
| D-07 | REMEMBER_LAST target no longer accessible | Fall back to the **same-domain** primary with a warning; if none, `NO_TIMETABLE_SELECTED`. Never cross-domain. |
| D-08 | Usability threshold | `UNUSABLE` when 0 usable class entries (valid section/day/time, not INCOMPLETE/REJECTED) or usable < 25 % of candidates. `NEEDS_REVIEW` when any warning, UNVERIFIED/INCOMPLETE entry or tentative section exists. Otherwise `READY`. Primary allowed for `READY`/`NEEDS_REVIEW` only. |
| D-09 | Role scope policy | Matrix in §2. Rationale: least privilege while keeping dashboards in the prompt functional. Must be confirmed by the college. |
| D-10 | Institutional "my" | Student → active academic-history batch (+ parent batch). Professor → entries mapped to their `staff_id`. If mapping missing → `CLARIFICATION_REQUIRED` with "setup required" text; never guessed. |
| D-11 | Combined-division pages (BE A–D) | Section scope kept; entries get `batch_label_raw` from the cell only. No division is assigned unless cell text names it. |
| D-12 | Breaks / activity slots | Stored as entries with `entry_kind = BREAK / ACTIVITY` and excluded from class queries (PDF §12 open decision: class-entry type chosen). |
| D-13 | Correction workflow | In V1 for institutional entries (Admin). Original values kept in `ENTRY_CORRECTION`; entry becomes VERIFIED only by explicit reviewer action. Personal owners can correct their own entries the same way. |
| D-14 | Personal domain room/floor aggregates | Q22, Q23, Q25, Q18 → `UNSUPPORTED_INTENT` in PERSONAL (API §10). Q20/Q21/Q24 work label-based. |
| D-15 | Authentication | Local college-email + password (Argon2id) with Admin-issued invitations; JWT access (15 min) + rotating hashed refresh tokens (30 days). SSO integration point documented. |
| D-16 | Primary change confirmation | UI always confirms; Q28 via search returns a confirmation step instead of acting immediately. |
| D-17 | Background processing | Postgres-backed job table (`SELECT … FOR UPDATE SKIP LOCKED`) and a worker process — no extra broker needed. Max 3 attempts. |
| D-18 | NO_MATCH / DATA_UNVERIFIED HTTP | HTTP 200 with application status (API §7 allows). Clients branch on `status`. |
| D-19 | Date range max | 31 days. |
| D-20 | Weekday without date ("Show Monday") | Treated as the recurring weekday view (no date needed) for Q02/Q24; for availability (Q13/Q21/Q22) a weekday resolves to its **next** occurrence and the resolved date is echoed in the response. |

## 6. Security requirements (summary)

Argon2id hashing; JWT signed with server secret; refresh-token rotation + revocation; account
status checked on every request; roles loaded from DB per request; rate limiting (login and search);
Pydantic validation on every input; parameterised SQLAlchemy only (no string SQL from input);
private file storage served only through authorised endpoints; magic-byte file-type checks;
IDOR protection — personal resources return 404 to non-owners (no existence leak) and log
`ACCESS_DENIED`; audit log for sensitive actions; no secrets in the mobile bundle.

## 7. Acceptance tests

API-01…API-16, T01…T16, PDF-01…PDF-16 are mapped to automated tests in `backend/tests/`
(see `docs/05-testing.md`).
