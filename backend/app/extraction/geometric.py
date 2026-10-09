"""Build a Grid from positioned words when no ruled table is detectable (borderless PDFs, OCR).

Columns come from the x-positions of weekday headers; rows from the vertical positions of time
labels in the left-hand column. Cell spans cannot be recovered reliably this way, so the
validator lowers confidence for grids produced here.
"""
from __future__ import annotations

from statistics import median

from app.extraction.model import Grid, GridCell, Word
from app.extraction.timeparse import BREAK_WORDS_RE, parse_day, parse_time_label


def _lines(words: list[Word]) -> list[list[Word]]:
    out: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.yc, w.x0)):
        if out:
            last = out[-1]
            ref = median([x.yc for x in last])
            h = median([x.y1 - x.y0 for x in last]) or 1
            if abs(w.yc - ref) <= 0.5 * h:
                last.append(w)
                continue
        out.append([w])
    return [sorted(ln, key=lambda w: w.x0) for ln in out]


def _text(words: list[Word]) -> str:
    return "\n".join(" ".join(w.text for w in ln) for ln in _lines(words))


def _gutter(body_lines: list[list[Word]], lo: float, hi: float) -> float:
    """Middle of the widest x-range in [lo, hi] that (almost) no body line covers — the column
    separator. A few full-width lines (legends, notes) are tolerated. Falls back to the midpoint."""
    if hi <= lo:
        return (lo + hi) / 2
    step = max((hi - lo) / 200, 0.5)
    limit = max(1, int(0.1 * len(body_lines)))
    best_len, best_mid, run_start = 0.0, (lo + hi) / 2, None
    x = lo
    while x <= hi:
        covered = sum(1 for ln in body_lines if any(w.x0 <= x <= w.x1 for w in ln))
        if covered <= limit:
            run_start = x if run_start is None else run_start
            if x - run_start > best_len:
                best_len, best_mid = x - run_start, (x + run_start) / 2
        else:
            run_start = None
        x += step
    return best_mid


def build_grid_from_words(words: list[Word], page: int, method: str, page_size: tuple[float, float] | None) -> Grid | None:
    if not words:
        return None
    lines = _lines(words)
    header_idx, day_words = None, []
    for i, ln in enumerate(lines):
        days = [(w, parse_day(w.text)) for w in ln]
        days = [(w, d) for w, d in days if d]
        if len({d for _, d in days}) >= 3:
            header_idx, day_words = i, days
            break
    if header_idx is None:
        return None
    day_words.sort(key=lambda t: t[0].xc)
    header_bottom_pre = max(w.y1 for w in lines[header_idx])
    body = [w for w in words if w.y0 > header_bottom_pre]
    body_lines = _lines(body)
    left_header = [w for w in lines[header_idx] if w.x1 <= day_words[0][0].x0]
    bounds = [_gutter(body_lines, left_header[-1].x1 if left_header else min((w.x0 for w in body), default=0.0),
                      day_words[0][0].x0)]
    for (a, _), (b, _) in zip(day_words, day_words[1:]):
        bounds.append(_gutter(body_lines, a.x1, b.x0))
    bounds.append(float("inf"))
    header_bottom = max(w.y1 for w in lines[header_idx])
    time_col_right = bounds[0]

    # Time-label blocks in the left column, below the header.
    left_lines = [[w for w in ln if w.xc < time_col_right] for ln in lines[header_idx + 1:]]
    blocks: list[list[Word]] = []
    open_block = False
    for ln in left_lines:
        if not ln:
            continue
        if blocks and open_block:
            blocks[-1].extend(ln)
        else:
            blocks.append(list(ln))
        joined = " ".join(w.text for w in blocks[-1])
        open_block = parse_time_label(joined) is None and not BREAK_WORDS_RE.search(joined) and len(blocks[-1]) < 8
    blocks = [b for b in blocks if parse_time_label(" ".join(w.text for w in b)) or BREAK_WORDS_RE.search(" ".join(w.text for w in b))]
    if len(blocks) < 2:
        return None
    tops = [min(w.y0 for w in b) for b in blocks]
    bots = [max(w.y1 for w in b) for b in blocks]
    row_h = median([b - a for a, b in zip(tops, tops[1:])])
    row_bounds = [header_bottom] + [(bots[i] + tops[i + 1]) / 2 for i in range(len(blocks) - 1)] + [bots[-1] + row_h * 0.6]

    n_rows = len(blocks) + 1
    n_cols = len(day_words) + 1
    buckets: dict[tuple[int, int], list[Word]] = {}
    context: list[Word] = []
    header_words: list[Word] = []
    for w in words:
        if w.y1 <= header_bottom and w.yc < lines[header_idx][0].y0:
            header_words.append(w)
            continue
        if lines[header_idx][0].y0 <= w.yc <= header_bottom:
            continue  # the weekday header line itself
        r = next((i for i in range(len(row_bounds) - 1) if row_bounds[i] <= w.yc < row_bounds[i + 1]), None)
        if r is None:
            context.append(w)
            continue
        if w.xc < bounds[0]:
            c = 0
        else:
            c = next((i + 1 for i in range(len(bounds) - 1) if bounds[i] <= w.xc < bounds[i + 1]), None)
            if c is None:
                context.append(w)
                continue
        buckets.setdefault((r + 1, c), []).append(w)

    cells: list[GridCell] = [GridCell(0, 0, "")]
    for j, (w, _) in enumerate(day_words):
        cells.append(GridCell(0, j + 1, w.text))
    for (r, c), ws in buckets.items():
        confs = [w.conf for w in ws if w.conf is not None]
        cells.append(GridCell(r, c, _text(ws),
                              bbox=(min(w.x0 for w in ws), min(w.y0 for w in ws), max(w.x1 for w in ws), max(w.y1 for w in ws)),
                              ocr_conf=(sum(confs) / len(confs)) if confs else None))
    return Grid(page=page, method=method, n_rows=n_rows, n_cols=n_cols, cells=cells,
                header_text=_text(header_words), context_text=_text(context), page_size=page_size)
