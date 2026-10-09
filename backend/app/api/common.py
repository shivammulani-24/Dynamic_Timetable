from __future__ import annotations

from typing import Any

from fastapi import Query

from app.errors import AppError, Code

MAX_LIMIT = 100


class Page:
    """limit + opaque cursor pagination (cursor encodes an offset; clients treat it as opaque)."""

    def __init__(self, limit: int = Query(25, ge=1, le=MAX_LIMIT), cursor: str | None = Query(None, max_length=20)):
        self.limit = limit
        try:
            self.offset = int(cursor) if cursor else 0
        except ValueError:
            raise AppError(Code.INVALID_REQUEST, "Invalid cursor.", {"field": "cursor"})
        if self.offset < 0:
            raise AppError(Code.INVALID_REQUEST, "Invalid cursor.", {"field": "cursor"})

    def envelope(self, items: list[Any], total: int) -> dict:
        nxt = self.offset + self.limit
        return {
            "items": items,
            "pagination": {
                "limit": self.limit,
                "total": total,
                "next_cursor": str(nxt) if nxt < total else None,
            },
        }
