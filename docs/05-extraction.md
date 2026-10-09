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

## Known parser limits (be honest about these)

* Only the synthetic layout has been tested. The real college PDF has not been processed yet;
  expect tuning once it is added as a fixture.
* OCR and borderless layouts can't recover merged-cell spans and may misplace multi-line cells;
  such entries are always UNVERIFIED and should be reviewed.
* Transposed layouts (days as rows) are supported in the grid parser but only lightly tested.
* Handwritten timetables and photos with strong perspective distortion are not supported.
* Day/month order in numeric effective dates is not guessed (flagged for review).
