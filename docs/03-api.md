# API (v1)

Base path `/api/v1`. Interactive docs at `/api/docs` (Swagger) and `/api/redoc`; the full machine
spec is exported to `docs/openapi.json` (65 paths). All endpoints except `/auth/login`,
`/auth/refresh`, `/auth/activate`, `/auth/password-reset/*` require `Authorization: Bearer <access>`.

## Conventions

* **Errors** — `{"status": CODE, "message": str, "details": {}, "request_id": str}`. Clients branch
  on `status`, never on `message`. Every response carries `X-Request-ID`.
* **Pagination** — `?limit=` (≤100) and `?cursor=`; responses `{"items": [...], "pagination": {"limit", "total", "next_cursor"}}`.
* **Domains** — every timetable endpoint takes `domain=INSTITUTIONAL|PERSONAL`; IDs are looked up only
  in that domain's tables.
* **Times** — dates ISO `YYYY-MM-DD`; times `HH:MM` 24-hour, interpreted in the user's saved IANA timezone.

## Status codes (API contract §7, reconciled)

| HTTP | `status` | When |
|---|---|---|
| 200 | `OK` | success |
| 200 | `NO_MATCH` | valid search, nothing in the selected timetable (never broadened) |
| 200 | `DATA_UNVERIFIED` | results include unverified/uncertain values (marked per item) |
| 400 | `INVALID_REQUEST` | malformed body, invalid parameter, unknown parameter |
| 401 | `UNAUTHENTICATED` | missing/expired/revoked token; `details.reason` = `TOKEN_EXPIRED`, `TOKEN_REVOKED`, `ACCOUNT_SUSPENDED`, … |
| 403 | `ACCESS_DENIED` | role not permitted |
| 404 | `TIMETABLE_NOT_FOUND` / `NOT_FOUND` | not visible in that domain (also used for other users' personal IDs) |
| 409 | `PRIMARY_SELECTION_CONFLICT` / `CONFLICT` | state conflict (already primary, not eligible, duplicate record) |
| 413 / 415 | `FILE_TOO_LARGE` / `UNSUPPORTED_FILE` | upload limits / signature mismatch |
| 422 | `CLARIFICATION_REQUIRED` | missing/ambiguous value; `clarification` has `kind`, `question`, `parameter`, `choices` |
| 422 | `UNSUPPORTED_INTENT` | outside the catalogue, cross-domain compare, domain-unsupported, missing configuration |
| 422 | `NO_TIMETABLE_SELECTED` / `TIMETABLE_UNUSABLE` / `TIMETABLE_NOT_READY` | selection state |
| 429 | `RATE_LIMITED` | `details.retry_after_seconds` |
| 500 | `INTERNAL_ERROR` | generic message + request id |

## Endpoints

| Area | Endpoints |
|---|---|
| Auth | `POST /auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/logout-all`, `/auth/activate`, `/auth/password-reset/request`, `/auth/password-reset/confirm`, `/auth/change-password` |
| Me | `GET /me`, `GET/PATCH /me/preferences`, `PUT /me/selection`, `POST/DELETE /me/push-devices` |
| Timetables | `GET /timetable-context`, `GET /timetables`, `POST /timetables/uploads`, `GET /timetables/{id}`, `GET /timetables/{id}/entries`, `GET /timetables/{id}/findings`, `GET /timetables/{id}/review-summary`, `GET /timetables/{id}/conflicts`, `GET /timetables/{id}/file`, `POST /timetables/{id}/make-primary`, `POST /timetables/{id}/reprocess`, `DELETE /timetables/{id}`, `PATCH /timetables/{id}/entries/{entry}`, `GET …/entries/{entry}/corrections`, `POST /timetables/{id}/entries/bulk-review`, `GET /jobs` |
| Search | `POST /search`, `GET /search/registry`, `GET/DELETE /search/history`, `GET/POST /saved-searches`, `DELETE /saved-searches/{id}`, `POST /saved-searches/{id}/run`, `GET /dashboard` |
| Notifications | `GET /notifications`, `GET /notifications/unread-count`, `POST /notifications/{id}/read`, `POST /notifications/read-all` |
| Admin | departments, academic-years, batches, courses, rooms, aliases (CRUD), `GET/PUT /admin/config`, users (list/detail/roles/status/reinvite), `POST /admin/students`, `POST /admin/staff`, `PATCH /admin/staff/{id}`, `GET /admin/students/eligible`, `POST /admin/promotions/preview`, `POST /admin/promotions/confirm`, `GET /admin/audit`, `POST /admin/timetables/{id}/remap` |

## Search request / response

```json
POST /api/v1/search
{ "query": "Is room 508 free at 2 pm?", "domain": "INSTITUTIONAL",
  "selection": {"type": "PRIMARY"}, "parameters": {"date": "2026-10-12"} }
```
`parameters` carries typed answers to a previous clarification (allowed keys only: `date`, `time`,
`start_time`, `end_time`, `start_date`, `end_date`, `day_of_week`, `course`, `professor`, `batch`,
`room`, `floor`, `entry_id`, `timetable_id`, `confirm`, `lunch_time`). A structured request may
send `intent` instead of `query`. `user_id`, roles, SQL, table or column names are never accepted.

```json
{ "status": "OK", "intent": "ROOM_FREE_NOW", "intent_id": "Q21",
  "context": {"domain": "INSTITUTIONAL", "selection_type": "PRIMARY", "timetable_id": "…",
              "timetable_title": "…", "timezone": "Asia/Kolkata", "now": "…"},
  "message": "Room 508 has no class scheduled at 14:00 (scheduled use only, not physical occupancy).",
  "clarification": null, "warnings": [], "result_type": "ROOM_STATUS", "results": [ … ],
  "pagination": null, "meta": {"duration_ms": 31}, "details": {}, "request_id": "…" }
```
