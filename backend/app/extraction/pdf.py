"""PDF adapter (PyMuPDF). Every page is processed independently and keeps its page number.

Strategy per page:
1. Enough selectable text → detect ruled tables with PyMuPDF `find_tables` (keeps merged-cell
   spans such as two-hour labs). Tables with a weekday header are timetable grids; other tables
   are treated as possible legends.
2. No ruled timetable found → geometric fallback from word positions.
3. Too little text (scanned page) → OCR fallback (Tesseract) + geometric grid; OCR provenance kept.
"""
from __future__ import annotations

import logging

import pymupdf as fitz  # PyMuPDF

from app.config import get_settings
from app.extraction.geometric import build_grid_from_words
from app.extraction.model import Finding, Grid, GridCell, Word
from app.extraction.ocr import ocr_available, ocr_grid
from app.extraction.timeparse import parse_day

log = logging.getLogger(__name__)


class PdfOpenError(Exception):
    pass


def open_pdf(data: bytes) -> fitz.Document:
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001
        raise PdfOpenError(f"The PDF could not be opened: {e.__class__.__name__}") from e
    if doc.needs_pass:
        raise PdfOpenError("The PDF is password-protected.")
    if doc.page_count == 0:
        raise PdfOpenError("The PDF has no pages.")
    return doc


def _boundaries(values: list[float], tol: float = 2.0) -> list[float]:
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _is_timetable(rows: list[list[str | None]]) -> bool:
    for row in rows[:4]:
        if len({parse_day(c or "") for c in row if c and parse_day(c)}) >= 3:
            return True
    # transposed: days down the first columns
    for c in range(min(2, max((len(r) for r in rows), default=0))):
        if len({parse_day(r[c] or "") for r in rows if c < len(r) and r[c] and parse_day(r[c])}) >= 3:
            return True
    return False


def _table_to_grid(t, page_no: int) -> Grid:
    data = t.extract()
    xs: list[float] = []
    for row in t.rows:
        for bb in row.cells:
            if bb:
                xs.append(bb[0])
    xs.append(t.bbox[2])
    col_bounds = _boundaries(xs)
    row_bounds = [row.bbox[1] for row in t.rows] + [t.bbox[3]]
    cells: list[GridCell] = []
    for r, row in enumerate(t.rows):
        for c, bb in enumerate(row.cells):
            if not bb:
                continue
            text = (data[r][c] if r < len(data) and c < len(data[r]) else None) or ""
            rowspan = sum(1 for i in range(len(row_bounds) - 1)
                          if bb[1] - 1 <= (row_bounds[i] + row_bounds[i + 1]) / 2 <= bb[3] + 1) or 1
            col_idx = next((i for i in range(len(col_bounds) - 1) if abs(col_bounds[i] - bb[0]) <= 2.5), c)
            colspan = sum(1 for i in range(len(col_bounds) - 1)
                          if bb[0] - 1 <= (col_bounds[i] + col_bounds[i + 1]) / 2 <= bb[2] + 1) or 1
            cells.append(GridCell(r, col_idx, text.strip(), rowspan, colspan, tuple(round(v, 1) for v in bb)))
    return Grid(page=page_no, method="TEXT", n_rows=len(t.rows), n_cols=max(len(col_bounds) - 1, 1), cells=cells)


def _page_image(doc, page) -> bytes:
    """A scanned page usually holds one full-page image: OCR it at native resolution.
    Otherwise render at 200 dpi (higher re-sampling of a low-dpi scan hurts recognition)."""
    imgs = page.get_images(full=True)
    if len(imgs) == 1:
        try:
            pix = fitz.Pixmap(doc, imgs[0][0])
            if pix.width >= 1000:
                if pix.n - pix.alpha >= 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                return pix.tobytes("png")
        except Exception:  # noqa: BLE001
            pass
    return page.get_pixmap(dpi=200).tobytes("png")


def _words(page: fitz.Page) -> list[Word]:
    return [Word(w[4], w[0], w[1], w[2], w[3]) for w in page.get_text("words")]


def _text_in(page: fitz.Page, rect: fitz.Rect) -> str:
    return page.get_text("text", clip=rect).strip()


def extract_pdf(data: bytes) -> tuple[list[Grid], list[dict], list[Finding], int]:
    s = get_settings()
    doc = open_pdf(data)
    if doc.page_count > s.max_pages:
        raise PdfOpenError(f"The PDF has {doc.page_count} pages; the limit is {s.max_pages}.")
    grids: list[Grid] = []
    pages: list[dict] = []
    findings: list[Finding] = []
    for pno in range(doc.page_count):
        page = doc[pno]
        n = pno + 1
        rect = page.rect
        text = page.get_text("text")
        info = {"page": n, "width": round(rect.width, 1), "height": round(rect.height, 1), "rotation": page.rotation,
                "text_chars": len(text.strip()), "method": "TEXT", "status": "NO_TABLE", "grids": 0}
        try:
            if len(text.strip()) < s.ocr_min_chars_per_page:
                if not ocr_available():
                    info["status"] = "FAILED"
                    findings.append(Finding("PAGE_ERROR", "PAGE_NO_TEXT_OCR_UNAVAILABLE",
                                            "Page has no selectable text and OCR is not available.", n))
                    pages.append(info)
                    continue
                info["method"] = "OCR"
                g, words, extra = ocr_grid(_page_image(doc, page), n, scale_to=(rect.width, rect.height))
                info.update(extra)
                if g:
                    grids.append(g)
                    info.update(status="PARSED", grids=1)
                    confs = [w.conf for w in words if w.conf is not None]
                    info["ocr_mean_confidence"] = round(sum(confs) / len(confs), 1) if confs else None
                else:
                    info["status"] = "FAILED"
                    findings.append(Finding("PAGE_ERROR", "OCR_NO_TIMETABLE_FOUND",
                                            "OCR ran but no weekday/time grid could be recognised on this page.", n))
                pages.append(info)
                continue

            found = page.find_tables()
            tt_tables, legend_rows = [], []
            for t in found.tables:
                rows = t.extract()
                if _is_timetable(rows):
                    tt_tables.append(t)
                else:
                    legend_rows += [[c or "" for c in r] for r in rows]
            page_grids: list[Grid] = []
            prev_bottom = rect.y0
            for t in sorted(tt_tables, key=lambda t: t.bbox[1]):
                g = _table_to_grid(t, n)
                g.header_text = _text_in(page, fitz.Rect(rect.x0, prev_bottom, rect.x1, t.bbox[1]))
                prev_bottom = t.bbox[3]
                g.page_size = (rect.width, rect.height)
                page_grids.append(g)
            if not page_grids:
                g = build_grid_from_words(_words(page), n, "TEXT", (rect.width, rect.height))
                if g:
                    g.method = "TEXT_GEOMETRIC"
                    page_grids.append(g)
            # Context (legends, notes) = text outside timetable tables.
            outside = text
            for t in tt_tables:
                inside = _text_in(page, fitz.Rect(t.bbox))
                if inside:
                    outside = outside.replace(inside, "")
            for g in page_grids:
                g.context_text = g.context_text or outside
                g.legend_rows = legend_rows
                if not g.header_text:
                    g.header_text = "\n".join(text.strip().splitlines()[:6])
            grids += page_grids
            if page_grids:
                info.update(status="PARSED", grids=len(page_grids), method=page_grids[0].method)
            else:
                findings.append(Finding("PAGE_ERROR", "NO_TIMETABLE_GRID",
                                        "No weekday/time timetable grid was detected on this page.", n))
        except Exception as e:  # noqa: BLE001 — one bad page must not kill the document
            log.exception("page %s failed", n)
            info["status"] = "FAILED"
            findings.append(Finding("PAGE_ERROR", "PAGE_PROCESSING_FAILED", f"Page could not be processed ({e.__class__.__name__}).", n))
        pages.append(info)
    page_count = doc.page_count
    doc.close()
    return grids, pages, findings, page_count

