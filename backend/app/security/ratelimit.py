"""Simple per-process sliding-window rate limiter.

Adequate for a single API process. For multiple API replicas, swap the store for Redis or
Postgres; the call sites (`check(bucket, key, limit)`) stay the same.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.errors import AppError, Code

_lock = threading.Lock()
_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_enabled = True


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = value


def reset() -> None:
    with _lock:
        _hits.clear()


def check(bucket: str, key: str, limit_per_minute: int) -> None:
    if not _enabled:
        return
    now = time.monotonic()
    with _lock:
        q = _hits[(bucket, key)]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit_per_minute:
            retry = int(60 - (now - q[0])) + 1
            raise AppError(Code.RATE_LIMITED, "Too many requests. Please wait and try again.", {"retry_after_seconds": retry})
        q.append(now)
