"""OCR fallback using Tesseract (via pytesseract). OCR-derived values always carry OCR provenance
and are capped at UNVERIFIED by the validator."""
from __future__ import annotations

import io
import shutil

from app.config import get_settings
from app.extraction.model import Word


def ocr_available() -> bool:
    s = get_settings()
    return s.ocr_enabled and shutil.which(s.tesseract_cmd) is not None


PSM_ATTEMPTS = (11, 4, 3)  # sparse text, single column, automatic — tried in order until a grid is found


def ocr_image_bytes(data: bytes, scale_to: tuple[float, float] | None = None, psm: int = 11) -> tuple[list[Word], tuple[float, float]]:
    """Returns words (optionally scaled into the given page coordinate size) and the image size."""
    import pytesseract
    from PIL import Image, ImageOps

    pytesseract.pytesseract.tesseract_cmd = get_settings().tesseract_cmd
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img).convert("L")
    w, h = img.size
    if max(w, h) < 1600:  # upscale small photos for better recognition
        f = 1600 / max(w, h)
        img = img.resize((int(w * f), int(h * f)))
        w, h = img.size
    d = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, config=f"--psm {psm}")
    sx, sy = (scale_to[0] / w, scale_to[1] / h) if scale_to else (1.0, 1.0)
    words: list[Word] = []
    for i, txt in enumerate(d["text"]):
        t = (txt or "").strip()
        try:
            conf = float(d["conf"][i])
        except (TypeError, ValueError):
            conf = -1
        if not t or conf < 0:
            continue
        x, y, ww, hh = d["left"][i], d["top"][i], d["width"][i], d["height"][i]
        words.append(Word(t, x * sx, y * sy, (x + ww) * sx, (y + hh) * sy, conf))
    return words, (w * sx, h * sy)


def ocr_grid(data: bytes, page: int, scale_to: tuple[float, float] | None = None):
    """Run OCR with several segmentation modes; return (grid|None, words, info)."""
    from app.extraction.geometric import build_grid_from_words

    last_words: list[Word] = []
    size = scale_to
    for psm in PSM_ATTEMPTS:
        words, size = ocr_image_bytes(data, scale_to=scale_to, psm=psm)
        last_words = words
        grid = build_grid_from_words(words, page, "OCR", size)
        if grid:
            return grid, words, {"ocr_psm": psm}
    return None, last_words, {"ocr_psm": None}
