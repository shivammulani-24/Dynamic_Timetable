# Testing

## How to run

```bash
# Backend (needs PostgreSQL with a `timetable_test` database; the suite drops/recreates its schema)
cd backend && .venv/bin/python -m pytest -q
#   override the database with TEST_DATABASE_URL=postgresql+psycopg://…/timetable_test

# Mobile
cd mobile && npx tsc --noEmit && npx jest

# Native bundle compilation for both platforms (no device needed)
cd mobile && npm run export:check

# End-to-end (real UI against the real API)
scripts/dev.sh seed; scripts/dev.sh api & scripts/dev.sh worker &
cd mobile && EXPO_PUBLIC_API_URL=http://localhost:8000 npx expo export --platform web --output-dir dist-web
npx serve -s dist-web -l 8081 &
UPLOAD_FIXTURE=/path/to/synthetic_timetable.pdf npm run test:e2e -- http://localhost:8081 ./e2e-screens

# Concurrency smoke (seeded dev API running)
python scripts/load_smoke.py http://localhost:8000 24 15
```

## Latest results (recorded in the authoring environment, 2026-10-09)

| Suite | Result |
|---|---|
| Backend pytest | **119 passed** (≈30 s) |
| Mobile TypeScript (`strict`, `noUnusedLocals`) | clean |
| Mobile Jest | **13 passed** |
| Expo export Android + iOS (Hermes bytecode) | both bundles compiled (5.6 MB / 5.4 MB) |
| Playwright e2e (web target, 390×844 viewport) | **21/21 checks**, 0 page errors |
| Concurrency smoke, 4 API workers, 24 threads × 15 requests | 360/360 HTTP 200, 0 inconsistent answers, ≈32 req/s, p50 ≈0.42 s, p95 ≈1.3 s |

The concurrency figures come from a shared sandbox VM running Postgres, API, worker and the load
generator together. They demonstrate correctness under concurrent use only — **they are not a
supported-user or capacity claim**. A real capacity test must run on the deployment hardware.

## Coverage map

| Area | Tests | Spec IDs covered |
|---|---|---|
| Auth & sessions (`test_auth.py`, 13) | login, generic failure, suspended accounts, expired/garbage tokens, refresh rotation + reuse detection, logout, invitation activation, password reset, role change invalidates tokens, self-lockout prevention, timezone validation, login rate limit | role escalation, token expiry |
| Extraction (`test_extraction.py`, 23) | all pages + provenance, grid/legends, tentative, combined divisions, stacked labs, legend-only expansion, room suffixes, inconsistent noon label, merged 2-hour lab, breaks/activities, missing room, effective date, scanned PDF OCR, corrupt PDF, no-table PDF, XLSX/CSV/DOCX/PNG through the same pipeline, DOCX merged cells, signature detection, time rules, cell grammar | PDF-01…PDF-13 |
| Uploads & domains (`test_uploads_and_domains.py`, 13) | upload→worker→status, primary unchanged by upload, independent primaries, wrong-domain ID, IDOR incl. Admin, institutional upload Admin-only, activation + notification, unusable can't be primary, rejected files, idempotent upload + duplicate file, same file both domains, correction preserves original + audit, worker retry, soft-delete rules | API-03…06, PDF-14/15, T06, T09, T10 |
| Query engine (`test_query_engine.py`, 57) | every intent Q01–Q30 (valid + negative paths), clarifications (AM/PM, date, week range, lunch, entity choice, confirmation, setup), working hours missing, inventory incomplete, unverified room, role restrictions, explicit archive, selection memory and domain switch, cross-domain rejection without querying, no fallback, disjoint results, SQL-injection text, raw SQL/unknown parameters, dashboard = typed query, history, saved searches, registry completeness | API-01, 02, 07–16; T01–T16 |
| Academics & admin (`test_academics_admin.py`, 13) | fresher registration without duplicates, promotion preview/confirm with preserved history, transition rules (pause/resume/repeat/withdraw/re-enter/graduate), all-or-nothing batches, **concurrent promotions** (one wins), single active year, master-data validation, role matrix for admin endpoints, conflict detection (end-exclusive, POSSIBLE vs CONFIRMED, access), **concurrent activations**, notifications ownership, OpenAPI, validation envelope | FR-03, FR-20, FR-24 |
| Mobile (`__tests__`, 13) | client: bearer header, **single-flight refresh** under concurrent 401s, refresh rejection clears session, error codes preserved, 4xx search envelopes returned, network errors; offline cache never persists personal/notification data; formatting/date helpers; result renderer: clarification choices, unverified markers, no-broadening note, Q30 message | |
| E2E (`mobile/e2e/smoke.e2e.mjs`) | login → dashboard → week → NL search → AM/PM + date clarification → Q30 → personal view + archives → sign-out → admin dashboard/hub/rooms → **file upload through the picker → worker processing → validation summary → activation offered** | |

## Not tested here (and why)

* Running on physical Android/iOS devices and simulators — no emulator, simulator or macOS in the
  authoring environment. Native compilation of the JS bundles was verified; UI was exercised on the
  web target of the same codebase. Device testing steps: `docs/07-deployment.md`.
* Push delivery through Expo's service — needs an EAS project and devices.
* Android hardware back button / iOS safe-area on notched devices — handled by React Navigation and
  `react-native-safe-area-context`, but not observed on hardware.
* SMTP email delivery — no mail server configured.
* Docker image build — no Docker daemon available (compose file syntax validated).
* Extraction accuracy on the **real** college PDF — not yet supplied.
