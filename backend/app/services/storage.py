"""Private file storage. Keys are opaque; files are never served by a public URL — only streamed
through endpoints that repeat the domain/ownership checks."""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from app.config import get_settings


class StorageError(Exception):
    pass


def _root() -> Path:
    root = Path(get_settings().storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(key: str) -> Path:
    p = (_root() / key).resolve()
    if _root() not in p.parents:
        raise StorageError("invalid storage key")
    return p


def new_key(domain: str, scope: str, ext: str) -> str:
    safe_ext = ext if ext and len(ext) <= 6 and ext[1:].isalnum() else ".bin"
    return f"{domain.lower()}/{scope}/{uuid.uuid4().hex}{safe_ext}"


def put(key: str, data: bytes) -> None:
    p = _path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".part")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)  # atomic: a half-written file is never visible under the real key
        os.chmod(p, 0o600)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise StorageError("could not store file") from e


def get(key: str) -> bytes:
    try:
        return _path(key).read_bytes()
    except OSError as e:
        raise StorageError("stored file is missing") from e


def delete(key: str) -> None:
    try:
        _path(key).unlink(missing_ok=True)
    except OSError:
        pass
