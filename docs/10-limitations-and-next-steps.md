# Known limitations and next steps

## Not verified in the authoring environment

| Item | Status | Next step |
|---|---|---|
| Real college timetable PDF | Added as a regression fixture; parser tuned (NEEDS_REVIEW, 293/453 classes VERIFIED, remaining flags are genuine source issues — see `docs/05-extraction.md`) | Hand-label ≥2 pages field by field and measure precision/recall; add the codes missing from the legends (`LA`, `ALA`, `HSS`, `MDM`, `PD`, `VM`) as master data/aliases |
| Android device / emulator run | JS bundle compiles; UI exercised on the web target only | `npx expo start` → Android emulator; run through `docs/09-demo-script.md` |
| iOS simulator / device run | iOS JS bundle compiles; no macOS/Xcode available | `npx eas-cli build --profile simulator -p ios` or `npx expo run:ios` on a Mac |
| Push notifications | Code path implemented; not delivered (needs EAS project id + device) | `eas init`, set `extra.eas.projectId`, `EXPO_PUSH_ENABLED=true` |
| Docker image | Compose syntax validated; image not built (no daemon) | `docker compose up --build` |
| Email (invitations/reset) | SMTP path implemented, not exercised | Configure SMTP variables |
| Capacity | Concurrency correctness smoke only | Load test on deployment hardware |

## Functional limitations (by design or deferred)

* Cross-domain comparison is unsupported in V1 (per spec).
* Recurring weekly schedules are fully supported; date-specific entries (`class_date`) are supported
  in queries but no adapter currently produces them from documents.
* Combined-division pages (e.g. BE A–D) keep a combined scope; students of those divisions only see
  such entries after an Admin maps them (alias or correction) — deliberately not guessed.
* Free-room search is only as complete as the room inventory; unmapped room labels are reported.
* The NL engine understands the documented question families in English; unusual phrasings return
  `UNSUPPORTED_INTENT` with examples. An LLM could be added as a *suggester* that proposes an
  intent + parameters which then pass through the same validation — never generating SQL.
* Rate limiting is per API process (documented); use Redis/Postgres for multi-replica deployments.
* Role-scope policy (`security/policy.py`) is a proposed default — the college should confirm it
  (e.g. whether students may see other batches' timetables).
* Week start, lunch boundary and working hours must be configured by the Admin; they are never assumed.
* Archive deletion is soft-delete only; a retention policy (how long, who may purge) is still open.

## Suggested roadmap

1. Labelled sample of the real PDF; measure and publish per-field accuracy honestly.
2. Institutional SSO (OIDC) mapped onto `auth_subject`.
3. Device test matrix (small Android, large Android, iPhone SE, iPhone Pro Max; dark mode; large text).
4. Admin bulk import of students/staff/rooms from CSV.
5. Timetable diff between two institutional versions (same domain) to power "important changes" notifications.
6. Observability: export structured logs to a log store; metrics on search latency and extraction outcomes.
