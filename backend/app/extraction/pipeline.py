"""Extraction pipeline: file bytes → grids → sections → candidate entries → validation.

Pure function of its inputs (no DB access) so it can be unit-tested and run in the worker.
"""
from __future__ import annotations

from collections import Counter

from app.extraction import office, pdf
from app.extraction.gridparse import parse_grid
from app.extraction.layout import split_layout
from app.extraction.model import ExtractionResult, Finding, SectionInfo
from app.extraction.sections import parse_heading, parse_legend
from app.extraction.validate import assign_status, document_checks


class ExtractionFailed(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _adapter(fmt: str, data: bytes):
    try:
        if fmt == "PDF":
            return pdf.extract_pdf(data)
        if fmt == "XLSX":
            return office.extract_xlsx(data)
        if fmt == "XLS":
            return office.extract_xlsx(office.convert_with_soffice(data, ".xls", "xlsx"))
        if fmt == "CSV":
            return office.extract_csv(data)
        if fmt == "DOCX":
            return office.extract_docx(data)
        if fmt == "DOC":
            return office.extract_docx(office.convert_with_soffice(data, ".doc", "docx"))
        if fmt == "IMAGE":
            return office.extract_image(data)
    except pdf.PdfOpenError as e:
        raise ExtractionFailed("FILE_UNREADABLE", str(e)) from e
    except office.ConversionError as e:
        raise ExtractionFailed("CONVERSION_FAILED", str(e)) from e
    except ExtractionFailed:
        raise
    except Exception as e:  # noqa: BLE001
        raise ExtractionFailed("FILE_UNREADABLE", f"The file could not be read ({e.__class__.__name__}).") from e
    raise ExtractionFailed("UNSUPPORTED_FORMAT", f"Unsupported format {fmt}.")


def run_extraction(data: bytes, fmt: str, *, require_scope: bool, known_rooms: set[str] | None = None) -> ExtractionResult:
    grids, pages, findings, page_count = _adapter(fmt, data)
    known_rooms = known_rooms or set()
    sections: list[SectionInfo] = []
    entries = []
    prepared = []
    for key, g in enumerate(grids):
        g = split_layout(g)
        head = parse_heading(g.header_text)
        legend = parse_legend("\n".join([g.context_text, g.header_text]), g.legend_rows)
        sec = SectionInfo(
            key=key, page=g.page, title=head["title"], program_level=head["program_level"], divisions=head["divisions"],
            is_tentative=head["is_tentative"], header_raw=g.header_text[:2000], legend=legend, method=g.method,
            effective_from=head["effective_from"], effective_from_raw=head["effective_from_raw"],
            academic_year_label=head["academic_year_label"], term_label=head["term_label"],
        )
        sections.append(sec)
        prepared.append((g, sec, head))
    # Legends of the document's other pages: a labelled fallback when a page's own legend omits a code.
    doc_legend: dict[str, dict[str, str]] = {"faculty": {}, "subject": {}}
    for sec in sections:
        for kind in ("faculty", "subject"):
            for code, name in sec.legend.get(kind, {}).items():
                doc_legend[kind].setdefault(code, name)
    # A legend cell clipped at its border ("Graph Theo") is completed from another page of the same
    # document that prints the same code with a longer text starting the same way ("Graph Theory").
    for kind in ("faculty", "subject"):
        for sec in sections:
            for code, name in sec.legend.get(kind, {}).items():
                best = doc_legend[kind].get(code, name)
                if len(name) > len(best) and name.lower().startswith(best.lower()):
                    doc_legend[kind][code] = name
        for sec in sections:
            table = sec.legend.get(kind, {})
            for code, name in list(table.items()):
                full = doc_legend[kind].get(code, name)
                if len(full) > len(name) and full.lower().startswith(name.lower()):
                    table[code] = full

    for g, sec, head in prepared:
        if sec.is_tentative:
            findings.append(Finding("SECTION_FLAG", "TENTATIVE_SECTION",
                                    f"Section '{sec.title or 'page ' + str(g.page)}' is marked Tentative.", g.page))
        if head["effective_from_ambiguous"]:
            findings.append(Finding("METADATA_WARNING", "EFFECTIVE_DATE_AMBIGUOUS",
                                    f"Effective date '{head['effective_from_raw']}' is ambiguous (day/month order).", g.page))
        if require_scope and not sec.program_level and not sec.divisions:
            findings.append(Finding("CRITICAL", "SECTION_HEADING_UNREADABLE",
                                    "The section heading (class/division) could not be read for this table.", g.page))
        cell_legend = {**sec.legend, "doc_faculty": doc_legend["faculty"], "doc_subject": doc_legend["subject"]}
        es, fs = parse_grid(g, sec, require_scope=require_scope, known_rooms=known_rooms, legend=cell_legend)
        entries += es
        findings += fs

    if not grids and not any(f.severity == "BLOCKING" for f in findings):
        findings.append(Finding("BLOCKING", "NO_TIMETABLE_FOUND", "No timetable grid was found anywhere in the file."))

    for e in entries:
        assign_status(e)
    findings += document_checks(entries)

    # Pages may state different W.E.F. dates. The document's date is the one most pages state
    # (earliest on a tie); every section keeps its own date and the difference is reported.
    eff_counts = Counter(s.effective_from for s in sections if s.effective_from)
    doc_eff = min(eff_counts, key=lambda d: (-eff_counts[d], d)) if eff_counts else None
    raw_effs = [s.effective_from_raw for s in sections if s.effective_from_raw and s.effective_from == doc_eff]
    if len(eff_counts) > 1:
        others = ", ".join(f"{d.isoformat()} (page {', '.join(str(s.page) for s in sections if s.effective_from == d)})"
                           for d in sorted(eff_counts) if d != doc_eff)
        findings.append(Finding("INFO", "EFFECTIVE_DATE_VARIES",
                                f"Most pages are effective from {doc_eff.isoformat()}, which is used for the document; "
                                f"also stated: {others}."))
    elif sections and not eff_counts:
        findings.append(Finding("METADATA_WARNING", "EFFECTIVE_DATE_MISSING", "No 'W.E.F.' / effective date was found."))
    ays = {s.academic_year_label for s in sections if s.academic_year_label}
    terms = {s.term_label for s in sections if s.term_label}
    return ExtractionResult(
        page_count=page_count, pages=pages, sections=sections, entries=entries, findings=findings, file_format=fmt,
        effective_from=doc_eff,
        effective_from_raw=raw_effs[0] if raw_effs else None,
        term_label=next(iter(terms)) if len(terms) == 1 else None,
        academic_year_label=next(iter(ays)) if len(ays) == 1 else None,
    )
