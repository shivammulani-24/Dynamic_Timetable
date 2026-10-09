"""Stable application error codes (API Contract §7). Clients branch on `status`, never on message."""
from __future__ import annotations

from enum import StrEnum
from typing import Any


class Code(StrEnum):
    OK = "OK"
    NO_MATCH = "NO_MATCH"
    DATA_UNVERIFIED = "DATA_UNVERIFIED"
    INVALID_REQUEST = "INVALID_REQUEST"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    ACCESS_DENIED = "ACCESS_DENIED"
    TIMETABLE_NOT_FOUND = "TIMETABLE_NOT_FOUND"
    NOT_FOUND = "NOT_FOUND"
    PRIMARY_SELECTION_CONFLICT = "PRIMARY_SELECTION_CONFLICT"
    CONFLICT = "CONFLICT"
    CLARIFICATION_REQUIRED = "CLARIFICATION_REQUIRED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    UNSUPPORTED_INTENT = "UNSUPPORTED_INTENT"
    NO_TIMETABLE_SELECTED = "NO_TIMETABLE_SELECTED"
    TIMETABLE_UNUSABLE = "TIMETABLE_UNUSABLE"
    TIMETABLE_NOT_READY = "TIMETABLE_NOT_READY"
    UNSUPPORTED_FILE = "UNSUPPORTED_FILE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


HTTP_STATUS: dict[Code, int] = {
    Code.OK: 200,
    Code.NO_MATCH: 200,
    Code.DATA_UNVERIFIED: 200,
    Code.INVALID_REQUEST: 400,
    Code.UNAUTHENTICATED: 401,
    Code.ACCESS_DENIED: 403,
    Code.TIMETABLE_NOT_FOUND: 404,
    Code.NOT_FOUND: 404,
    Code.PRIMARY_SELECTION_CONFLICT: 409,
    Code.CONFLICT: 409,
    Code.CLARIFICATION_REQUIRED: 422,
    Code.CONFIRMATION_REQUIRED: 422,
    Code.UNSUPPORTED_INTENT: 422,
    Code.NO_TIMETABLE_SELECTED: 422,
    Code.TIMETABLE_UNUSABLE: 422,
    Code.TIMETABLE_NOT_READY: 422,
    Code.UNSUPPORTED_FILE: 415,
    Code.FILE_TOO_LARGE: 413,
    Code.RATE_LIMITED: 429,
    Code.INTERNAL_ERROR: 500,
}


class AppError(Exception):
    def __init__(self, code: Code, message: str, details: dict[str, Any] | None = None, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.http_status = http_status or HTTP_STATUS[code]


def not_found(what: str = "Resource") -> AppError:
    return AppError(Code.NOT_FOUND, f"{what} not found.")


def denied(message: str = "You do not have permission to perform this action.") -> AppError:
    return AppError(Code.ACCESS_DENIED, message)


def invalid(message: str, **details: Any) -> AppError:
    return AppError(Code.INVALID_REQUEST, message, details)
