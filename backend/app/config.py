"""Environment-based configuration. All secrets come from environment variables / .env."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = Field("development", description="development | test | production")
    database_url: str = "postgresql+psycopg://timetable:timetable_dev@localhost:5432/timetable"

    # Auth
    jwt_secret: str = "dev-only-insecure-secret-change-me-please-0123456789"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    invitation_token_hours: int = 72
    password_reset_minutes: int = 30

    # Files / extraction
    storage_dir: Path = Path("./var/storage")
    max_upload_mb: int = 15
    max_pages: int = 30
    ocr_enabled: bool = True
    ocr_min_chars_per_page: int = 40
    soffice_path: str = "soffice"
    tesseract_cmd: str = "tesseract"

    # Worker
    worker_poll_seconds: float = 2.0
    job_max_attempts: int = 3

    # Rate limiting (per process, sliding window)
    rate_limit_login_per_minute: int = 10
    rate_limit_search_per_minute: int = 60
    rate_limit_upload_per_minute: int = 10

    # Query engine
    max_date_range_days: int = 31

    # Notifications
    expo_push_enabled: bool = False
    expo_push_url: str = "https://exp.host/--/api/v2/push/send"

    # Email (optional). When unset in development, tokens are returned in API responses
    # flagged dev_only so the flows can be demonstrated without an SMTP server.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None

    cors_origins: list[str] = ["*"]
    log_level: str = "INFO"

    @field_validator("environment")
    @classmethod
    def _env(cls, v: str) -> str:
        if v not in {"development", "test", "production"}:
            raise ValueError("environment must be development, test or production")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def dev_tokens_exposed(self) -> bool:
        """Expose invitation/reset tokens in responses only outside production when no SMTP."""
        return not self.is_production and not self.smtp_host

    def validate_for_production(self) -> None:
        if self.is_production:
            if self.jwt_secret.startswith("dev-only") or len(self.jwt_secret) < 32:
                raise RuntimeError("JWT_SECRET must be set to a strong secret in production")
            if "*" in self.cors_origins:
                raise RuntimeError("CORS_ORIGINS must be explicit in production")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.validate_for_production()
    return s
