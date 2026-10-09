# Natural-language query engine

**What it is:** a deterministic, rule-based interpreter (tokenisation, controlled synonyms, ordered
regular-expression rules, vocabulary matching). It is *not* a trained machine-learning model and it
does not use an LLM. Its only outputs are a registered intent name and typed parameters; everything
else (identity, role, domain, timetable, timezone, *now*) is resolved by the server.

## Pipeline (`app/query/engine.py`)

1. Validate request shape; reject unknown parameters / unregistered intents.
2. Parse text (`nlp.parse`): relative/explicit dates (`today`, `tomorrow`, `12 Oct`, ISO; `5/6` is
   flagged as ambiguous), weekdays (`next monday`), week references, times (`2 pm`, `14:00`,
   ranges `between 10 and 12`), `now`, `after lunch`, and keyword-anchored mentions
   (`prof X`, `room 508`, `5th floor`, `batch SE-A`).
3. **Q30 pre-check** — a cross-domain comparison is rejected *before* any timetable is resolved.
4. Archive/primary meta intents (Q27–Q29) run without requiring a usable timetable.
5. `resolve_context` → domain + timetable + timezone (see architecture doc).
6. Load the vocabulary of **this timetable only** and find unanchored mentions by exact n-gram
   match (`find all dbms classes` → course `DBMS`).
7. Classify (`nlp.classify`) — ordered rules using keywords and which entity types were found.
8. Enforce: intent supported in this domain (else `UNSUPPORTED_INTENT` with reason), role allowed
   (`security/policy.py`), student/staff scope set up (else `SETUP_REQUIRED` clarification).
9. Handler validates required parameters and raises a **clarification** when something is missing
   or ambiguous; otherwise calls one approved template.
10. Envelope: `OK` / `NO_MATCH` / `DATA_UNVERIFIED`, warnings (excluded uncertain times, unmapped
    rooms, effective-date issues), results, pagination. History/log written without free text in logs.

## Entity resolution (`app/query/vocab.py`)

Order: exact normalised label/id/alias → **unique** whole-word match (`desai` → *Prof. Kiran K. Desai*)
→ fuzzy *suggestions* (`dessai`) which are **always asked**, never auto-selected. A course also
matches its session variants (`DS` → `DS`, `DS Lab`). Choices are returned as opaque keys
(`id:…`/`label:…`) that must still exist in the same timetable when sent back.

## Rules enforced

| Rule | Implementation |
|---|---|
| Interval convention | start inclusive, end exclusive (`start <= t < end`; overlap `a.start < b.end && b.start < a.end`) |
| AM/PM | bare `2`, `7:00` → `CLARIFICATION_REQUIRED (AMPM)`; `14:00`, `2 pm`, `2 in the afternoon` accepted |
| Dates | `today`/`tomorrow` in the user's timezone; ambiguous numeric dates asked; weekdays → recurring view (Q02/Q24) or next occurrence for availability (echoed as a warning) |
| Week | uses `INSTITUTION_CONFIG.week_start_day`; if unset, asks with explicit Monday/Sunday ranges |
| Lunch / working hours | from config; lunch can be supplied in the clarification; free time refused if hours unset |
| Next class | today after *now*, then following days up to `next_class_lookahead_days` (default 7) |
| Uncertain data | time-dependent templates exclude `time_uncertain`/missing-time entries and say how many; listing templates include them marked unverified |
| No broadening | empty result → `NO_MATCH` for the selected timetable only |
| Personal domain | labels only; free rooms / floor / rooms-after-time / professor free time → unsupported |
| "My" | personal: whole timetable; institutional: student → own batch (+ parent division); professor → own staff id; HOD/Principal/Admin → their scope |
| Scope-free intents | room schedules/availability, professor free time and scheduled location use the full selected timetable (they describe facilities or busy/free only; other batches' details are withheld in Q13) |

## Intent → template map

| ID | Intent | Template(s) | Domains | Notes |
|---|---|---|---|---|
| Q01 | SHOW_MY_TIMETABLE | QT01 | both | no date → today |
| Q02 | SHOW_DAY_TIMETABLE | QT03 (weekday) / QT01 (date) | both | |
| Q03 | SHOW_TIMETABLE_FOR_DATE | QT01 | both | |
| Q04 | SHOW_WEEK_TIMETABLE | QT02 | both | ≤31 days |
| Q05 | SHOW_BATCH_TIMETABLE | QT03 / QT01 | both | division includes its lab sub-groups |
| Q06 | FIND_COURSE_CLASSES | QT05 | both | |
| Q07 | FILTER_CLASSES_BY_TIME | QT04 (overlap) | both | date required |
| Q08 | SHOW_CLASS_DETAILS | QT06 | both | entry must belong to the timetable and scope |
| Q09 | CURRENT_CLASS | QT07 | both | |
| Q10 | NEXT_CLASS | QT08 | both | |
| Q11 | CLASSES_AFTER_TIME | QT04 (starts within) | both | lunch from config or user |
| Q12 | TIME_UNTIL_NEXT_CLASS | QT08 | both | |
| Q13 | CHECK_SCHEDULE_FREE | QT04 (instant) | both | FREE / SCHEDULED / UNCERTAIN |
| Q14 | REMAINING_CLASSES_TODAY | QT09 | both | in-progress marked |
| Q15 | PROFESSOR_SCHEDULE | QT10 | both | |
| Q16 | PROFESSOR_SCHEDULED_LOCATION | QT11 | both | "scheduled, not tracked" wording |
| Q17 | PROFESSOR_COURSE | QT12 | both | |
| Q18 | PROFESSOR_FREE_TIME | QT13 | institutional | uncertain classes treated as busy |
| Q19 | PROFESSORS_FOR_BATCH | QT14 | both | |
| Q20 | ROOM_SCHEDULE | QT15 | both | |
| Q21 | ROOM_FREE_NOW | QT16 | both | explicit time → date required |
| Q22 | FIND_FREE_ROOMS | QT17 | institutional | needs room inventory; incomplete mapping flagged |
| Q23 | FLOOR_ACTIVITY | QT18 | institutional | HOD/Principal/Admin |
| Q24 | ROOM_SCHEDULE_FOR_DAY | QT15 + day | both | |
| Q25 | ROOMS_WITH_CLASSES_AFTER_TIME | QT19 | institutional | HOD/Principal/Admin |
| Q26 | SEARCH_SELECTED_ARCHIVE | QT20 + inner intent | both | requires an explicit non-primary archive |
| Q27 | SHOW_PRIMARY_TIMETABLE | QT20 | both | |
| Q28 | MAKE_TIMETABLE_PRIMARY | QT22 | both | confirmation step; Admin-only for institutional |
| Q29 | LIST_TIMETABLE_ARCHIVES | QT21 | both | personal = owner only |
| Q30 | CROSS_DOMAIN_COMPARE | — | none | always rejected, no domain queried |

Template definitions (required/optional parameters, result fields, empty-result and uncertainty
behaviour) are in `app/query/registry.py` and exported to `docs/query-registry.json`.

## Adding a new question type

1. Add an `IntentSpec` (and a `TemplateSpec` if a new operation is needed) to `registry.py`.
2. Implement the template in `templates.py` using `Q.base()` (keeps timetable, domain and scope).
3. Add a handler in `engine.py` and a classification rule in `nlp.py`.
4. Add tests in `tests/test_query_engine.py` (valid, missing parameter, ambiguity, scope, empty).
