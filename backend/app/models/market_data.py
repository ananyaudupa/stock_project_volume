from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime


class MarketDataSnapshot(Base):
    """Normalized provider observation used as scoring input (one per symbol per scan run)."""

    __tablename__ = "market_data_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_run_id: Mapped[int | None] = mapped_column(ForeignKey("scan_runs.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime)
    data_timestamp: Mapped[datetime | None] = mapped_column(UTCDateTime)
    price: Mapped[float | None] = mapped_column(Float)
    open_price: Mapped[float | None] = mapped_column(Float)
    previous_close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    previous_session_volume: Mapped[int | None] = mapped_column(BigInteger)
    avg_daily_volume: Mapped[float | None] = mapped_column(Float)
    same_time_avg_volume: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(64))
    eligible: Mapped[bool] = mapped_column(Boolean)
    exclusion_reason: Mapped[str | None] = mapped_column(String(64))
    quality_flags: Mapped[dict] = mapped_column(JSON, default=dict)
