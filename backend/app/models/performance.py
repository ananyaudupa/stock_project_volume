from datetime import datetime

from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, utcnow


class DailyPerformance(Base):
    """Post-selection price measurement. Stored separately; never modifies the original pick."""

    __tablename__ = "daily_performance"
    __table_args__ = (UniqueConstraint("stock_pick_id", "measurement_type", "measurement_time"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_pick_id: Mapped[int] = mapped_column(ForeignKey("stock_picks.id"), index=True)
    measurement_type: Mapped[str] = mapped_column(String(32))  # e.g. "close"
    measurement_time: Mapped[datetime] = mapped_column(UTCDateTime)
    measurement_price: Mapped[float] = mapped_column(Float)
    return_pct: Mapped[float] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
