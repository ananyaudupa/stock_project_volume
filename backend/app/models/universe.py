from datetime import date, datetime

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime, utcnow


class ClassificationVersion(Base):
    """One imported market-cap classification list (e.g. an AMFI half-yearly list)."""

    __tablename__ = "classification_versions"

    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(128))
    effective_date: Mapped[date] = mapped_column(Date)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False)


class StockUniverse(Base):
    """Eligible symbols and their market-cap category under a given classification version.

    Rows are kept per version so historical scans remain explainable.
    """

    __tablename__ = "stock_universe"
    __table_args__ = (UniqueConstraint("symbol", "classification_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    company_name: Mapped[str] = mapped_column(String(256))
    exchange: Mapped[str] = mapped_column(String(8), default="NSE")
    isin: Mapped[str | None] = mapped_column(String(12))
    cap_category: Mapped[str] = mapped_column(String(16))
    cap_rank: Mapped[int | None] = mapped_column(Integer)
    classification_version: Mapped[str] = mapped_column(ForeignKey("classification_versions.version"))
    classification_date: Mapped[date] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
