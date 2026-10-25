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

    # Email (optional). Without it, activation codes are shown to the Admin who creates the account
    # (Admin-only response) and, in development only, reset codes are printed in the server log.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None

    cors_origins: list[str] = ["*"]
    log_level: str = "INFO"

    # Single-service hosting (e.g. a free cloud tier): serve the exported web app from this server
    # and process uploads in a background thread of the API process instead of a separate worker.
    web_dist_dir: Path | None = None
    run_worker_in_process: bool = False

    # Demo deployments only: load the college demo data into an EMPTY database on start-up.
    # In production this needs ALLOW_DEMO_SEED=true and a private DEMO_PASSWORD (never the
    # published development password).
    allow_demo_seed: bool = False
    demo_password: str | None = None

    @field_validator("database_url")
    @classmethod
    def _db_url(cls, v: str) -> str:
        # Hosting providers hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the driver.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

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
    def email_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def invitation_codes_shown_to_admin(self) -> bool:
        """Without email, the Admin who creates/re-invites an account is shown its activation code
        (in that authenticated Admin response only) to hand over in person."""
        return not self.email_configured

    @property
    def reset_codes_in_server_log(self) -> bool:
        """Development without email: password-reset codes are printed in the server's own log so the
        person running the server can test the flow. Never in production, never in an API response."""
        return not self.is_production and not self.email_configured

    def validate_for_production(self) -> None:
        if self.is_production:
            if self.jwt_secret.startswith("dev-only") or len(self.jwt_secret) < 32:
                raise RuntimeError("JWT_SECRET must be set to a strong secret in production")
            if "*" in self.cors_origins:
                raise RuntimeError("CORS_ORIGINS must be explicit in production")
            if self.allow_demo_seed and (not self.demo_password or len(self.demo_password) < 10
                                         or self.demo_password == "Demo@12345"):
                raise RuntimeError("DEMO_PASSWORD (10+ characters, not the published one) is required for a demo seed")


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.validate_for_production()
    return s
