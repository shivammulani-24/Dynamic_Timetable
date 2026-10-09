# Interview guide — explaining the design

Short, defensible answers to the questions you are likely to get.

**Why React Native + Expo?** One TypeScript codebase for Android and iOS; Expo gives managed native
modules (secure storage, document picker, notifications) and cloud builds without maintaining
Xcode/Gradle projects. Expo Router gives file-based navigation that mirrors the screen map.

**Why FastAPI and a single backend service?** The extraction pipeline (PyMuPDF, Tesseract) and the
query engine are Python, so one Python service avoids cross-language glue. Pydantic validates every
request; OpenAPI is generated automatically. Only the worker is a separate *process* because OCR is
CPU-heavy — but it shares the codebase, so there is one deployable artifact.

**Why a Postgres job table instead of Celery/Redis?** Fewer moving parts. `SELECT … FOR UPDATE SKIP
LOCKED` lets several workers pull jobs safely, and job state lives in the same transaction as the
timetable status. Retries, stale-job recovery and failure states are explicit columns.

**How is authentication done?** College email + Argon2id password hashes; Admin-created accounts
activate via a single-use invitation code. Short-lived JWT access tokens (15 min) plus opaque
refresh tokens stored only as SHA-256 hashes, rotated on every use; reusing an old refresh token
revokes the whole family (theft detection). A `token_version` column lets us invalidate all access
tokens instantly on suspension, password or role change. SSO could replace the password step by
filling `auth_subject` from the provider and issuing the same tokens.

**How is RBAC enforced?** Roles are rows in `USER_ROLE`, loaded on every request into a `Principal`.
Endpoints declare required roles; data scope (student → own batch, HOD → department, Principal/Admin →
college) is applied *inside the SQL* by `scope_condition`. The UI hides buttons, but that is never
the control — tests call admin endpoints as every role.

**Why is the schema shaped this way (normalisation)?** One identity table (`USER_ACCOUNT`) with
separate STUDENT and STAFF profiles avoids polymorphic owner columns. Academic placement lives in
`STUDENT_ACADEMIC_HISTORY` (one row per period) instead of columns on STUDENT, so promotions append
history instead of overwriting it; a partial unique index guarantees a single open placement.

**How are institutional and personal data isolated?** Physically separate tables for metadata,
sections and entries; a domain adapter hands code exactly one domain's models; the search context
resolves a single timetable in a single domain; composite foreign keys ensure a user's personal
primary is their own; non-owners get 404. There is no SQL anywhere that touches both entry tables.

**How does the PDF pipeline handle messy timetables?** Everything becomes a grid; time labels are
resolved as a *sequence* (rows must increase), so the source's "12.15 a.m." row is detected as
inconsistent, kept with a suggested reading but marked uncertain — never silently fixed. Cells are
parsed by token shape plus the page's own legend, so `DS Lab A1/AVN/604` becomes course DS (lab),
faculty AVN, room 604, sub-group SE-A1. Uncertain entries are UNVERIFIED and excluded from
"now/next/free" answers but still shown, flagged, in listings.

**What is OCR fallback?** Pages with too little selectable text are rasterised (or their embedded
scan used at native resolution) and read with Tesseract; columns come from whitespace gutters
under the weekday headers. OCR entries are capped at UNVERIFIED.

**Confidence vs verification?** Verification status is the rule-based truth used by queries;
the numeric confidence is an uncalibrated heuristic for sorting the review queue. We do not claim
an accuracy percentage until it is measured on a labelled sample.

**How does the natural-language engine work?** It is rule-based, not ML: regexes extract dates,
times and anchored entities; unanchored mentions are matched against the selected timetable's own
vocabulary; ordered rules pick one of 30 registered intents. Each intent maps to fixed,
parameterised templates. Ambiguity produces a structured clarification with typed choices.

**How do you prevent SQL injection with natural language?** Text can only choose an intent and fill
typed parameters; templates are pre-written SQLAlchemy expressions with bound values; unknown
parameter names are rejected; no table/column names are ever taken from input. A test sends
`'; DROP TABLE …` and checks nothing changed.

**How are times handled?** The user's IANA timezone is stored on the account; "today/now" are
computed from server time in that zone (an injectable clock makes tests deterministic). Intervals
are start-inclusive/end-exclusive, so back-to-back classes don't conflict.

**How does conflict detection work?** Group timed entries by resource identity (staff/room/batch id,
or normalised label) and day, then check true interval overlap. Division vs its own lab sub-group
counts; two parallel sub-groups don't. A conflict is only "CONFIRMED" when both entries are
verified, time-certain and mapped to master records; otherwise "POSSIBLE".

**Transactions and races?** Activation locks the single settings row; promotions lock students in
id order; uploads are idempotent via a unique (uploader, client_request_id) index. Two tests fire
concurrent activations/promotions from threads and assert one consistent outcome.

**Caching and invalidation?** TanStack Query caches reads with short stale times; activation sends a
notification and bumps a settings version; the app invalidates timetable queries on activation,
primary change and processing completion. Only institutional reads are persisted for offline use,
always shown with an "offline, last saved at …" banner; logout wipes the cache.

**Testing strategy?** Pure functions (time parsing, cell grammar) unit-tested; the pipeline tested on
generated fixtures that reproduce the spec's layout traits; API integration tests run against a real
Postgres; every intent has positive and negative tests; mobile client logic and components tested
with Jest; a Playwright script drives the real UI against the real API.

**Performance?** Indexes on (timetable, day, start) and per-resource columns; vocabulary loaded with
one query per entity type (removed an N+1 found by profiling); multiple API processes. We measured
behaviour under concurrency but do not quote a user capacity without testing on real hardware.

**What would you do next?** See `docs/10-limitations-and-next-steps.md` — tune the parser on the real
PDF with a labelled sample, institutional SSO, Redis-backed rate limiting for multiple replicas,
device testing matrix, and an optional LLM *only* as an intent/entity suggester behind the same validator.
