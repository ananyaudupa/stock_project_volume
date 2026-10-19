from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utcnow


class ScanRun(Base):
    """One scheduled or manual scan. Identity = (trading_date, session, scan_type).

    Retries reuse the same row (attempts are recorded in scan_attempts), so a session can never
    publish two snapshots of the same type.
    """

    __tablename__ = "scan_runs"
    __table_args__ = (UniqueConstraint("trading_date", "session", "scan_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trading_date: Mapped[date] = mapped_column(Date, index=True)
    session: Mapped[str] = mapped_column(String(16))
    scan_type: Mapped[str] = mapped_column(String(16), default="scheduled")
    scheduled_at: Mapped[datetime] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    provider: Mapped[str] = mapped_column(String(64))
    is_mock_data: Mapped[bool] = mapped_column(Boolean, default=False)
    algorithm_version: Mapped[str] = mapped_column(String(64))
    classification_version: Mapped[str | None] = mapped_column(String(64))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    data_as_of: Mapped[datetime | None] = mapped_column(UTCDateTime)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    picks: Mapped[list["StockPick"]] = relationship(
        back_populates="scan_run", order_by="(StockPick.cap_category, StockPick.rank)"
    )
    attempts: Mapped[list["ScanAttempt"]] = relationship(back_populates="scan_run", order_by="ScanAttempt.attempt_no")


class ScanAttempt(Base):
    __tablename__ = "scan_attempts"
    __table_args__ = (UniqueConstraint("scan_run_id", "attempt_no"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(String(32))  # scheduler | admin | cli
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16))
    provider_latency_ms: Mapped[int | None] = mapped_column(Integer)
    provider_calls: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)

    scan_run: Mapped[ScanRun] = relationship(back_populates="attempts")


class StockPick(Base):
    """One selected stock in one scan. Immutable once written: later scans never modify it."""

    __tablename__ = "stock_picks"
    __table_args__ = (
        UniqueConstraint("scan_run_id", "cap_category", "rank"),
        UniqueConstraint("scan_run_id", "symbol", "cap_category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    company_name: Mapped[str] = mapped_column(String(256))
    cap_category: Mapped[str] = mapped_column(String(16))
    rank: Mapped[int] = mapped_column(Integer)
    price_at_scan: Mapped[float] = mapped_column(Float)
    previous_close: Mapped[float] = mapped_column(Float)
    reference_price: Mapped[float] = mapped_column(Float)
    price_change_pct: Mapped[float] = mapped_column(Float)
    movement_strength: Mapped[float] = mapped_column(Float)
    intraday_volume: Mapped[int | None] = mapped_column(BigInteger)
    relative_volume: Mapped[float | None] = mapped_column(Float)
    volume_basis: Mapped[str] = mapped_column(String(32))
    volume_score: Mapped[float] = mapped_column(Float)
    movement_score: Mapped[float] = mapped_column(Float)
    final_score: Mapped[float] = mapped_column(Float)
    data_timestamp: Mapped[datetime] = mapped_column(UTCDateTime)
    selection_reason: Mapped[str] = mapped_column(Text)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)  # full scoring inputs, for audit
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    scan_run: Mapped[ScanRun] = relationship(back_populates="picks")


@event.listens_for(StockPick, "before_update")
def _picks_are_immutable(mapper, connection, target):
    raise RuntimeError("stock_picks rows are immutable historical records")
