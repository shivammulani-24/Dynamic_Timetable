# Dynamic Timetable — Role-Based Timetable Monitoring System

A cross-platform (Android / iOS) mobile app with a centralised backend for a college timetable:
role-based dashboards, **separate Institutional and Personal timetables**, timetable upload and
extraction (PDF, Excel, CSV, Word, JPG/PNG with OCR), an auditable review/correction workflow, and a
**deterministic natural-language query engine** that maps English questions to approved intents
(Q01–Q30) and parameterised query templates (QT01–QT22) — never to free-form SQL.

```
React Native (Expo SDK 57, TypeScript strict)  ──HTTPS──▶  FastAPI (Python 3.13)
  Expo Router · TanStack Query · RHF + Zod                    ├─ Auth & RBAC (Argon2id, JWT + rotating refresh tokens)
  SecureStore for credentials                                 ├─ Search-context resolver (domain / timetable / timezone)
                                                              ├─ Query engine: rule-based NLP → intent registry → QT templates
                                                              ├─ Extraction pipeline (PyMuPDF · Tesseract · openpyxl · python-docx)
                                                              └─ PostgreSQL 16 ◀── background worker (job table, SKIP LOCKED)
```

## Repository layout

| Path | What it is |
|---|---|
| `backend/app/` | FastAPI app: `api/v1` routers, `security` (auth, RBAC policy), `services`, `extraction`, `query`, `worker.py`, `seed.py` (synthetic demo), `seed_college.py` (the college's real PDF) |
| `backend/alembic/` | Database migrations (`0001` schema, `0002` reference data, `0003` time-uncertainty flag) |
| `backend/tests/` | 145 pytest tests (auth, extraction spec PDF-01…16, real college PDF regression + end-to-end on it, domains/isolation, Q01–Q30, academics, concurrency) |
| `mobile/src/app/` | Expo Router screens (auth, role tabs, search, timetable, archives, upload, review, admin) |
| `mobile/src/{api,state,components,theme,lib}` | Typed API client, auth/domain state, design system, helpers |
| `mobile/__tests__/`, `mobile/e2e/` | Jest unit/component tests; Playwright end-to-end runs against the real API (synthetic demo + real college timetable) |
| `docs/` | Requirements & decisions, architecture, API, query engine, extraction, testing, deployment, interview guide, demo script |
| `scripts/` | `dev.sh` (setup/run), `load_smoke.py` (concurrency smoke) |

## Quick start (development)

Prerequisites: Python 3.12+ (tested 3.13), PostgreSQL 14+ (tested 16), Node 20+ (tested 22),
Tesseract (OCR) and optionally LibreOffice (only for legacy `.xls`/`.doc`).

```bash
# 1. Backend: venv, dependencies, database user/dbs, migrations, mobile npm install
scripts/dev.sh setup            # or follow the manual steps in docs/07-deployment.md

# 2. Data (DEVELOPMENT ONLY — refuses to run when ENVIRONMENT=production; both RESET the dev DB)
scripts/dev.sh seed-college     # the college's real timetable PDF + matching master data and logins
scripts/dev.sh seed             # …or the small SYNTHETIC demo used by the tests

# 3. Run the API and the worker (two terminals)
scripts/dev.sh api              # http://0.0.0.0:8000  · API docs: http://localhost:8000/api/docs
scripts/dev.sh worker           # processes uploads in the background

# 4. Run the app
cd mobile && npx expo start     # press a (Android emulator), i (iOS simulator) or scan the QR in Expo Go
```

Alternative: `docker compose up --build` runs Postgres + API + worker (see `docs/07-deployment.md`;
the compose file is syntax-validated, but the image was not built in the authoring sandbox, which
has no Docker daemon).

**Testing on your phone:** step-by-step guide in [`docs/11-run-on-phone.md`](docs/11-run-on-phone.md).

### Accounts after `scripts/dev.sh seed-college` (real timetable)

Password **`Demo@12345`**, domain `@demo.college.edu`: `admin@`, `principal@`, `snd@` (HOD + Professor),
every faculty code from the PDF (`kkd@`, `avn@`, `js@`, `aag@` …), and students
`student.se.a1@`, `student.se.a2@`, `student.se.b1@`, `student.se.c3@`, `student.se.d4@`, `student.te.a1@`,
`student.te.b2@`, `student.te.c1@`, `student.te.d3@`, `student.be.a@`, `student.be.c@`, `student.mtech@`,
`student.newbie@` (no batch yet). What to try with each: `docs/11-run-on-phone.md` §7.

### Demo accounts after `scripts/dev.sh seed` (synthetic sample)

All use the password **`Demo@12345`** and the domain `@demo.college.edu`. They exist only after
`scripts/dev.sh seed`; production databases never receive them.

| Login | Role(s) | What to try |
|---|---|---|
| `alice@…` | Student, SE-A lab group A1 | Next class, weekly view, personal timetable (has a personal primary) |
| `bob@…` | Student, SE-A2 | Personal view with **no** upload → explicit upload prompt, no fallback |
| `newbie@…` | Student, no batch yet | "Setup required" message instead of an invented assignment |
| `kkd@…` | HOD + Professor (code KKD) | Own teaching schedule, free periods, conflicts, floor activity |
| `avn@` `pjb@` `rhs@…` | Professor | Teaching schedule |
| `principal@…` | Principal | College-wide monitoring |
| `admin@…` | Admin | Upload/review/activate, master data, users, promotion, audit |

The seeded timetable is **synthetic sample data** generated by `app/devdata/synthetic.py` to mimic the
layout traits described in the PDF specification. It is not the college's real timetable.

### Connecting a phone, emulator or simulator to the development API

The app finds the API automatically in development: it reads the Metro dev-server host and uses
port 8000 on the same machine (`mobile/src/lib/config.ts`). Run the API on `0.0.0.0`.

| Target | Works out of the box? | Notes |
|---|---|---|
| Physical phone (Expo Go / dev build) | Yes, on the same Wi-Fi | Firewall must allow port 8000 |
| Android emulator | Yes | Falls back to `10.0.2.2:8000` if the host can't be detected |
| iOS simulator | Yes | Uses the Mac's address |
| Any build outside development | Set `EXPO_PUBLIC_API_URL=https://…` | Builds without it fail fast — no localhost is baked in |

## Tests (results from the latest run)

```bash
cd backend && .venv/bin/python -m pytest -q          # 145 passed
cd mobile  && npx tsc --noEmit && npx jest            # typecheck clean · 14 passed
cd mobile  && npm run test:e2e -- http://localhost:8081 ./e2e-screens            # 21/21 (after `seed`)
cd mobile  && npm run test:e2e:college -- http://localhost:8081 ./e2e-college    # 22/22 (after `seed-college`)
python scripts/load_smoke.py http://localhost:8000 24 15                 # concurrency smoke (not a benchmark)
```

Details, what each suite covers and the exact numbers: `docs/06-testing.md`.

## Builds

| Kind | Command | Verified here? |
|---|---|---|
| JS bundles (both platforms) | `npm run export:check` in `mobile/` | **Yes** — Android and iOS Hermes bundles compile |
| Development build (custom native client) | `npx eas-cli build --profile development --platform android|ios` | No (needs an Expo account / Apple account) |
| iOS simulator build | `npx eas-cli build --profile simulator --platform ios` or `npx expo run:ios` on a Mac | No (no macOS/Xcode in this environment) |
| Store builds | `npx eas-cli build --profile production` then `eas submit` | No |

Push notifications additionally require an EAS project id (`extra.eas.projectId`) and
`EXPO_PUBLIC_API_URL`; without them the app still shows in-app notifications fetched from the server.

## Documentation

1. `docs/01-requirements-and-decisions.md` — requirement matrix, role matrix, ERD, document conflicts and decisions
2. `docs/02-architecture.md` — components, data flow, security model, consistency
3. `docs/03-api.md` — endpoint overview, envelopes, status codes (full spec: `docs/openapi.json`, live at `/api/docs`)
4. `docs/04-query-engine.md` — pipeline, intent → template map, clarification rules (`docs/query-registry.json`)
5. `docs/05-extraction.md` — formats, pipeline stages, statuses, validation rules, known parser limits
6. `docs/06-testing.md` — suites, coverage map to spec test IDs, latest results
7. `docs/07-deployment.md` — configuration, production checklist, Docker, backups, troubleshooting
8. `docs/08-interview-guide.md` — design rationale explained for interviews
9. `docs/09-demo-script.md` — a 10-minute walkthrough
10. `docs/10-limitations-and-next-steps.md` — honest list of what is not done / not verified
11. `docs/11-run-on-phone.md` — run the backend + app on your phone with the real timetable, test checklist

## The college's real timetable

The current timetable (10 pages: SE A–D, TE A–D, BE A–D combined, M.Tech) is a regression fixture
(`backend/tests/fixtures/reference/college_timetable.pdf`) and the dev seed. With the college's rules
applied (see "Real-PDF tuning" in `docs/05-extraction.md`) it extracts **452 of 453 classes verified**:

* the "12.15 a.m." noon row is read as midday because the rows around it prove it (raw label kept);
* LLC / MDM / HSS slots without teacher or room are valid: the app shows just the course;
* codes missing from a legend are shown as printed; the W.E.F. date most pages state is used;
* the combined BE A–D page applies to every BE division;
* lunch is taken from each class's own LONG BREAK (12:15 for some years, 1:15 for others).

What remains is in the PDF itself: one M.Tech class with no time label (fix it in Review & correct)
and two real clashes (Prof. SP on Friday 2:15, room 603-2 on Tuesday 2:15), listed on the Conflicts
screen. Accuracy has not been measured against a hand-labelled sample yet.
