# Architecture

## Components

```
┌──────────────── Mobile app (Expo / React Native, one codebase for Android + iOS) ───────────────┐
│ Expo Router screens · TanStack Query (cache, retries for reads only) · RHF + Zod forms           │
│ api/client.ts: typed fetch, timeouts, single-flight token refresh · SecureStore for the session  │
│ Offline: only institutional reads persisted (AsyncStorage) and shown with "last refreshed" time  │
└───────────────────────────────────────────────┬─────────────────────────────────────────────────┘
                                                │ HTTPS /api/v1 (JSON, multipart for uploads)
┌──────────────────────────────── FastAPI application (stateless, N processes) ───────────────────┐
│ middleware: request-id, structured JSON logs, CORS, error envelope                               │
│ security/  deps (JWT → user → Principal from DB), policy (role → data scope), ratelimit          │
│ api/v1/    auth · me · timetables · search · dashboard · notifications · admin                   │
│ services/  context (server-resolved search context) · timetables (archives, primary) · uploads   │
│            entries (scope filter, corrections) · conflicts · academics · users · mapping · audit │
│ query/     nlp (rules) → registry (Q01–Q30) → engine (validation, clarification) → templates    │
│ extraction/ pdf · ocr · office · geometric → grid → gridparse/cellparse → validate → pipeline    │
└───────────────┬────────────────────────────────────────────────────────────┬────────────────────┘
                │ SQLAlchemy 2 (bound parameters only)                       │ private file storage
        ┌───────▼────────┐        claims jobs FOR UPDATE SKIP LOCKED   ┌─────▼──────┐
        │ PostgreSQL 16  │◀──────────────── worker.py (N processes) ───│ var/storage│
        └────────────────┘                                             └────────────┘
```

Why this shape: one modular Python service keeps the PDF pipeline, query engine and API in one
language and one deployable unit (simple to run and to explain). The only separately-scaled piece
is the **worker**, because extraction/OCR is CPU-heavy and must not block API requests. A Postgres
job table replaces a message broker: one less moving part, transactional with the data it changes.

## Request lifecycle (search)

1. `get_current_user` decodes the JWT, loads the user, checks `token_version` and `account_status`.
2. `load_principal` loads **roles, staff profile and current academic placement from the DB** on
   every request (never from the token or the client).
3. `resolve_context` picks the domain (request hint → remembered → INSTITUTIONAL), the timetable
   (explicit archive → remembered archive → domain primary), verifies ownership/visibility and
   usability, and computes *now* in the user's saved timezone. It never crosses domains.
4. The engine classifies the text into a registered intent, resolves entities **only against that
   timetable's labels**, validates parameters, enforces role/domain rules, may ask for clarification,
   then runs one approved template. Results are scoped again by role in SQL.

## Data model highlights

* `USER_ACCOUNT` + `USER_ROLE` (many roles per user) + `STUDENT`/`STAFF` profiles.
* `STUDENT_ACADEMIC_HISTORY` is the source of truth for placement; a partial unique index
  (`uq_sah_one_open`) allows at most one open placement per student.
* Institutional and personal timetables have **separate metadata, section and entry tables**. The
  `services/domains.py` adapter hands code exactly one domain's models, so a union is not expressible.
* `INSTITUTIONAL_TIMETABLE_SETTINGS` is a single-row table (`CHECK settings_id = 1`) holding the
  official default and a monotonically increasing `version` for cache invalidation.
* `USER_PREFERENCE` uses **composite foreign keys** `(timetable_id, owner_user_id)` so a user's
  personal primary/remembered archive must be their own timetable — enforced by the database too.
* Entries keep raw text, raw labels, page/region provenance, parser version, confidence,
  `verification_status`, `time_uncertain` and validation messages; corrections are stored in
  `ENTRY_CORRECTION` with before/after snapshots.

## Security model

| Threat | Control |
|---|---|
| Role escalation | Roles only from `USER_ROLE`; only Admin endpoints change them; role change bumps `token_version` |
| Stolen refresh token | Rotation on every refresh; reuse of an old token revokes the whole token family |
| IDOR on personal data | Lookups scoped to the domain table + owner check; non-owners get 404 (no existence leak) and an `ACCESS_DENIED` audit row |
| Admin reading personal timetables | No application path exists — Admin endpoints never query personal tables; job monitor shows only institutional + own jobs |
| SQL injection | No string SQL from input; intents/templates are fixed; parameters are typed and bound; unknown parameters rejected |
| Malicious uploads | Extension allowlist + **content signature** check, size/page limits, private storage, parsing in the worker, LibreOffice run with an isolated profile and timeout |
| Brute force | Login rate limit per IP and per email; generic error message for bad email or password |
| Session after suspension | Every request re-checks account status; suspension revokes refresh tokens and bumps `token_version` |
| Secrets in app | Only `EXPO_PUBLIC_API_URL` reaches the bundle; tokens in SecureStore (Keychain/Keystore) |
| Information leaks | Uniform error envelope with request id; no stack traces or SQL in responses; no tokens/passwords in logs |

## Consistency and concurrency

* Primary/default changes lock the settings or preference row (`SELECT … FOR UPDATE`); concurrent
  activations serialise (tested). Promotions lock student rows in a stable order to avoid deadlocks.
* Uploads accept a `client_request_id`; a partial unique index per uploader makes retries idempotent.
* Workers claim jobs with `FOR UPDATE SKIP LOCKED`; stale RUNNING jobs (no heartbeat for 10 min)
  are re-claimed; unexpected errors retry up to `JOB_MAX_ATTEMPTS`; deterministic failures don't.
* Each request runs in its own session/transaction, so an in-flight search uses one consistent
  snapshot; after activation every subsequent request resolves to the new default. Clients see the
  change via the `institutional_settings_version` and `data_version` fields, the activation
  notification (which invalidates caches) and short stale times.

## Mobile app structure

* `src/app/(auth)` — welcome, login, activation, password reset.
* `src/app/(app)/(tabs)` — Home (role dashboard), Ask (NL search), Timetable (week), Archives,
  Admin (Admins only — hiding is cosmetic, the server enforces), Profile.
* Stack screens — class details, timetable detail, review & correction, upload, notifications,
  conflicts, monitoring, admin tools.
* The **dashboard and the weekly view call the same engine intents** as typed questions
  (`NEXT_CLASS`, `CURRENT_CLASS`, `REMAINING_CLASSES_TODAY`, `SHOW_TIMETABLE_FOR_DATE`), so
  "Next class" on Home and "what is my next class?" cannot disagree (tested).
