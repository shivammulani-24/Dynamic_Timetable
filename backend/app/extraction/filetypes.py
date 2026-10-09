"""Server-side file-type detection by *content signature* (never trusting the extension alone)."""
from __future__ import annotations

import io
import zipfile

SUPPORTED = {
    "PDF": ".pdf",
    "XLSX": ".xlsx",
    "XLS": ".xls",
    "CSV": ".csv",
    "DOCX": ".docx",
    "DOC": ".doc",
    "IMAGE": ".jpg/.jpeg/.png",
}
ACCEPT_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv", ".docx", ".doc", ".jpg", ".jpeg", ".png"}


def detect_format(data: bytes, filename: str) -> str | None:
    name = (filename or "").lower()
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ""
    if data.startswith(b"%PDF-"):
        return "PDF"
    if data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff"):
        return "IMAGE"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
        except zipfile.BadZipFile:
            return None
        if "word/document.xml" in names:
            return "DOCX"
        if "xl/workbook.xml" in names:
            return "XLSX"
        return None
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):  # OLE2 compound file: legacy Office
        if ext == ".xls":
            return "XLS"
        if ext == ".doc":
            return "DOC"
        return None
    if ext == ".csv":
        try:
            sample = data[:4096].decode("utf-8-sig")
        except UnicodeDecodeError:
            return None
        if "\x00" not in sample and ("," in sample or ";" in sample or "\t" in sample):
            return "CSV"
    return None
