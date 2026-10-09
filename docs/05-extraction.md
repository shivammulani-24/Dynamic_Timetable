# Timetable extraction & validation

## Supported inputs

| Format | Adapter | How |
|---|---|---|
| PDF (text) | `extraction/pdf.py` | PyMuPDF `find_tables` on ruled tables (keeps merged-cell spans, e.g. 2-hour labs); geometric fallback from word positions |
| PDF (scanned) / JPG / PNG | `ocr.py` + `geometric.py` | Tesseract OCR at native resolution, several page-segmentation modes; columns from whitespace gutters, rows from time labels |
| XLSX / CSV | `office.py` | openpyxl (merged ranges → spans) / csv sniffer |
| DOCX | `office.py` | python-docx tables (merged cells → spans) with preceding paragraphs as headings |
| XLS / DOC (legacy) | `office.py` | converted with LibreOffice headless (isolated profile, timeout), then as above |

The documents specify *PDF only* for V1; the other formats were added on explicit user request
(decision C-01). All formats become the same **Grid** model, so validation and storage are shared.

## Stages (PDF spec §3)

1. **Receive** — extension allowlist, content-signature detection, ≤15 MB, PDF parseable and ≤30 pages
   (configurable). Rejections create nothing.
2. **Archive** — original stored privately (atomic write, 0600) + SHA-256; a new archive row every
   time (duplicates are flagged, not merged); idempotent with `client_request_id`.
3. **Queue** — `PROCESSING_JOB` row; worker claims it.
4–6. **Inspect / extract / OCR fallback** per page; page status `PARSED | NO_TABLE | FAILED`, method `TEXT | TEXT_GEOMETRIC | OCR`.
7. **Sections** — heading text above each table → level (FE/SE/TE/BE), divisions, *Tentative*,
   W.E.F. date, academic year, term. One section per table, page provenance kept.
8. **Time rows** — `timeparse.resolve_sequence`: literal a.m./p.m. honoured only if the interval is
   plausible and fits the row sequence; otherwise `TIME_LABEL_INCONSISTENT` with a *suggested*
   reading marked `time_uncertain`; unmarked labels resolved only if exactly one reading fits.
9. **Cells** — `cellparse`: slash-separated components, stacked lab rows → separate entries,
   sub-groups (`A1`), elective groups (`Batch1`), rooms with suffixes (`702-B`, `509 old`), inline
   time ranges (conflicts with the row are flagged), breaks/activities classified separately.
10. **Normalise / map** — legend expansions only for abbreviations present on that page; institutional
    labels linked to master records only on a unique exact match (code/name/alias), restricted to
    the timetable's department. Personal entries are never mapped.
11. **Validate** — required fields, duplicates (same cell → `REJECTED`; repeated class → warning),
    possible batch overlaps (parallel lab groups and elective groups are allowed).
12. **Persist** — entries with raw text, page/region, method, parser version, confidence, status.
13. **Summarise** — counts, page coverage, issue counts → status.
14. **Review** — Admin (institutional) or owner (personal) verifies, edits or rejects entries; every
    change is stored in `ENTRY_CORRECTION` (before/after) and audited.

## Entry status

| Status | Assigned when |
|---|---|
| VERIFIED | day, time and scope present; no warnings; text (not OCR); not tentative; for institutional entries, labels linked to master data — or confirmed by a reviewer |
| UNVERIFIED | usable but something is uncertain (warning, OCR, geometric layout, tentative section, uncertain time) |
| INCOMPLETE | missing day/time, or (institutional) section/division scope unknown |
| REJECTED | extraction artifact (or reviewer rejection) — kept for audit, excluded from search |

The numeric confidence is an **uncalibrated heuristic** for sorting. No accuracy figure is claimed:
precision/recall must be measured against a hand-labelled sample of the real timetable.

## Timetable status (decision D-08)

* `UNUSABLE` — no usable class entries, or fewer than 25 % usable, or a blocking finding.
* `NEEDS_REVIEW` — usable, but unverified/incomplete/rejected entries, warnings, page errors or a
  tentative section exist. Searchable and eligible for primary (warnings don't block selection).
* `READY` — everything verified.
* `FAILED` — the file could not be read/converted, or processing crashed after all retries.

## Regression fixtures

`app/devdata/synthetic.py` generates SYNTHETIC files reproducing the traits listed in the spec
(3 sections, Tentative division, combined BE A–D, legends, stacked labs, merged 2-hour lab, breaks,
the inconsistent `12.15 a.m. to 01.15 p.m.` row, `509 old`, `702-B`, missing room) in PDF, scanned
PDF, PNG, XLSX, CSV and DOCX, plus corrupt and no-table files. Tests PDF-01…PDF-16 run on them.

## Real-PDF tuning (parser 1.1.0)

What the college PDF showed, and the generic rule each case led to (no file-specific code):

| Observed in the real PDF | Rule added |
|---|---|
| Whole page is ONE ruled table: title row (`W.E.F. … / AY … / SE BTech (Division-A)`) above the weekday row, legend below the last time row | `extraction/layout.py` splits every grid into heading rows (→ section heading), body, and legend rows (from the first `Faculties:` / `Subjects:` marker) |
| Legend cells are `ABBR: Name` in one cell; the marker row decides which columns are faculty vs subject | Column-aware legend parsing; merged legend cells with several pairs on one line are split |
| A page's legend omits codes used on it (e.g. `PJB`, `GS` on page 1) | Other pages of the *same document* are a fallback, marked `LEGEND_FROM_OTHER_PAGE` (INFO) |
| `Open Elective` heading line over several options; `OE`/`PE`/`MDM` electives in parallel | Options get `PARALLEL_OPTION`; they are not reported as batch clashes; items stacked in one cell aren't either |
| `PE III-TSDA -A`, `PE III-GenAI-E`, `AISC` vs legend `AI&SC` | Exactly one legend code inside a longer label → name filled, `COURSE_CODE_WITHIN_LABEL` (INFO); punctuation-only differences match; several/none → not guessed |
| `(10:00 - 11:00 am)` inside a 9–11 merged cell | A cell time *inside* the cell's own rows is used (`TIME_FROM_CELL_WITHIN_SPAN`); outside it stays `EXPLICIT_TIME_CONFLICT` |
| `Batch 2`, `Batch D`, `S.N. 1 to 60`, wrapped `…/AT/Batch` + `1/505`, `Data Sci.Lab` + `D4/ARN/…` | Group tokens and wrapped lines recognised |
| `606-4 &5`, `703-A&B`, `HSS(609)`, `AT(Math)`, `LLC ()`, `MDM Lab()` | Multi-room labels, course(room), faculty(note), empty details kept as missing |

Result on that file (10 pages, all parsed, text layer): **NEEDS_REVIEW**, 453 class entries,
293 VERIFIED / 159 UNVERIFIED / 1 INCOMPLETE. What remains flagged is real: the `12.15 a.m.`
noon row (86 entries, time uncertain), codes absent from every legend (`LA`, `ALA`, `HSS`, `MDM`,
`IOT`, `PD`, `VM`), blank `LLC ()` / `MDM Lab()` cells, two cell times contradicting their rows,
the different W.E.F. date on the M.Tech page, the combined BE A–D scope, and one M.Tech cell with
no time label. These counts describe this one document — they are not an accuracy measurement.

## Known parser limits (be honest about these)

* Tuned on the synthetic fixtures **and one real document** (the college's 10-page ODD-2026
  timetable, `backend/tests/fixtures/reference/college_timetable.pdf`). No labelled-sample
  precision/recall has been measured yet, so no accuracy figure is claimed.
* OCR and borderless layouts can't recover merged-cell spans and may misplace multi-line cells;
  such entries are always UNVERIFIED and should be reviewed.
* Transposed layouts (days as rows) are supported in the grid parser but only lightly tested.
* Handwritten timetables and photos with strong perspective distortion are not supported.
* Day/month order in numeric effective dates is not guessed (flagged for review).
