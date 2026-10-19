"""Application settings, loaded from environment variables / a local untracked .env."""

from datetime import time
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://user:password@localhost:5432/stock_scanner"

    market_data_provider: str = "mock"
    market_data_api_key: str = Field(default="", repr=False)

    timezone: str = "Asia/Kolkata"
    morning_scan_time: time = time(9, 15)
    afternoon_scan_time: time = time(15, 0)
    performance_job_time: time = time(16, 0)

    volume_score_weight: float = 0.5
    movement_score_weight: float = 0.5

    max_data_staleness_seconds: int = 300
    min_avg_traded_value_inr: float = 5_000_000
    min_universe_coverage: float = 0.80
    picks_per_category: int = 5
    # Only scan stocks ranked 1..N by market cap (0 = no limit). 500 = 100 large + 150 mid + 250 small.
    max_universe_rank: int = 500

    provider_max_retries: int = 3
    provider_retry_base_delay_seconds: float = 2.0

    # A run stuck in "running" longer than this is treated as abandoned and may be retried.
    stale_run_timeout_seconds: int = 900

    # Password for viewing the site. Empty = no login (local development only; refused in production).
    app_password: str = Field(default="", repr=False)
    session_days: int = 30
    # Built frontend to serve from the API (single origin). Empty = auto-detect ../frontend/dist.
    frontend_dist: str = ""

    admin_api_key: str = Field(default="", repr=False)
    alert_webhook_url: str = Field(default="", repr=False)
    cors_origins: str = "http://localhost:5173"

    holidays_file: str = ""  # optional override for app/data/nse_holidays.json

    @field_validator("morning_scan_time", "afternoon_scan_time", "performance_job_time", mode="before")
    @classmethod
    def _parse_hhmm(cls, v):
        if isinstance(v, str) and len(v) == 5:
            hh, mm = v.split(":")
            return time(int(hh), int(mm))
        return v

    @field_validator("database_url", mode="before")
    @classmethod
    def _psycopg_driver(cls, v):
        # Hosts like Neon/Render hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the driver named.
        if isinstance(v, str):
            for prefix in ("postgres://", "postgresql://"):
                if v.startswith(prefix):
                    return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @model_validator(mode="after")
    def _check_weights(self):
        if self.volume_score_weight < 0 or self.movement_score_weight < 0:
            raise ValueError("score weights must be non-negative")
        if self.volume_score_weight + self.movement_score_weight == 0:
            raise ValueError("score weights must not both be zero")
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
