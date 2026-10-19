from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import CapCategory, ScanSession


class PerformanceOut(BaseModel):
    measurement_type: str
    measurement_time: datetime
    measurement_price: float
    return_pct: float


class PickOut(BaseModel):
    id: int
    symbol: str
    company_name: str
    cap_category: str
    rank: int
    price_at_scan: float
    previous_close: float
    price_change_pct: float
    direction: Literal["up", "down", "flat"]
    movement_strength: float
    intraday_volume: int | None
    relative_volume: float | None
    volume_basis: str
    volume_basis_label: str
    volume_score: float
    movement_score: float
    final_score: float
    data_timestamp: datetime
    selection_reason: str
    performance: list[PerformanceOut] = []


class RunMeta(BaseModel):
    run_id: int
    trading_date: date
    session: ScanSession
    scan_type: str
    status: str
    scheduled_at: datetime
    scan_time: str = Field(description="Scheduled local scan time, e.g. 09:15:00+05:30")
    started_at: datetime | None
    completed_at: datetime | None
    data_as_of: datetime | None
    is_stale: bool
    stale_reason: str | None
    is_mock_data: bool
    provider: str
    algorithm_version: str
    classification_version: str | None
    weights: dict[str, float]
    methodology_note: str
    message: str | None = None
    eligible_counts: dict[str, int] = {}
    exclusions: dict[str, int] = {}


class SessionSnapshotOut(RunMeta):
    categories: dict[CapCategory, list[PickOut]]


class CategorySnapshotOut(RunMeta):
    category: CapCategory
    stocks: list[PickOut]


class LatestOut(BaseModel):
    today: date
    morning: SessionSnapshotOut | None
    afternoon: SessionSnapshotOut | None


class SessionSummary(BaseModel):
    status: str
    run_id: int | None = None
    pick_count: int = 0
    is_mock_data: bool | None = None


class HistoryDay(BaseModel):
    date: date
    is_trading_day: bool | None
    non_trading_reason: str | None
    morning: SessionSummary
    afternoon: SessionSummary


class HistoryOut(BaseModel):
    from_date: date = Field(alias="from")
    to_date: date = Field(alias="to")
    page: int
    page_size: int
    total_days: int
    days: list[HistoryDay]

    model_config = {"populate_by_name": True}


class CompareOut(BaseModel):
    trading_date: date
    category: CapCategory
    morning: CategorySnapshotOut | None
    afternoon: CategorySnapshotOut | None
    in_both: list[str]
    morning_only: list[str]
    afternoon_only: list[str]


class LastRunOut(BaseModel):
    run_id: int
    trading_date: date
    session: ScanSession
    status: str
    completed_at: datetime | None
    data_as_of: datetime | None
    message: str | None


class StatusOut(BaseModel):
    now: datetime
    today: date
    is_trading_day: bool | None
    non_trading_reason: str | None
    previous_trading_day: date | None
    provider: str
    is_mock_data: bool
    last_successful: LastRunOut | None
    latest_run: LastRunOut | None
    today_sessions: dict[str, SessionSummary]
    next_scheduled_scan: datetime | None
    data_freshness_seconds: int | None
    classification_version: str | None
    calendar_years_loaded: list[int]


class AdminRunRequest(BaseModel):
    session: ScanSession
    trading_date: date | None = None
    scan_type: Literal["manual", "scheduled"] = "manual"
    # Only for providers with point-in-time quotes (e.g. mock backfills): scan as of the scheduled time.
    use_scheduled_time: bool = False


class AttemptOut(BaseModel):
    attempt_no: int
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    status: str
    provider_latency_ms: int | None
    provider_calls: int | None
    error_message: str | None


class AdminRunOut(BaseModel):
    run_id: int
    trading_date: date
    session: str
    scan_type: str
    status: str
    provider: str
    is_mock_data: bool
    scheduled_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    error_message: str | None
    algorithm_version: str
    classification_version: str | None
    config: dict
    summary: dict
    attempts: list[AttemptOut]
