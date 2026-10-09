from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.errors import AppError, Code
from app.logging_setup import configure_logging
from app.services.audit import request_id_var

log = logging.getLogger("api")


def error_body(code: Code | str, message: str, details: dict | None = None) -> dict:
    return {"status": str(code), "message": message, "details": details or {}, "request_id": request_id_var.get()}


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="Dynamic Timetable API",
        version="1.0.0",
        description="Role-based dynamic timetable monitoring system. All endpoints are under /api/v1.",
        openapi_url="/api/v1/openapi.json",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id")
        rid = rid if rid and len(rid) <= 64 and rid.replace("-", "").isalnum() else uuid.uuid4().hex
        token = request_id_var.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                "user_id": str(getattr(request.state, "user_id", "") or "") or None,
            },
        )
        return response

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        fields = [
            {"field": ".".join(str(x) for x in e.get("loc", [])[1:]), "message": e.get("msg", "invalid")}
            for e in exc.errors()
        ]
        return JSONResponse(error_body(Code.INVALID_REQUEST, "Some fields are invalid.", {"fields": fields}), status_code=400)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            error_body(Code.INTERNAL_ERROR, "Something went wrong. Please try again; quote the request ID if it persists."),
            status_code=500,
        )

    from app.api.v1 import router as v1

    app.include_router(v1, prefix="/api/v1")

    @app.get("/healthz", tags=["health"])
    def health():
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
        return {"status": "OK"}

    return app


app = create_app()
