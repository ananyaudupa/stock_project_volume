"""Post-selection performance. Inserts new daily_performance rows; never modifies stock_picks."""

import logging
from datetime import date, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import utcnow
from app.models import DailyPerformance, ScanRun, StockPick
from app.models.enums import PUBLISHED_STATUSES
from app.services.market_data.base import MarketDataProvider, ProviderError

log = logging.getLogger(__name__)

MARKET_CLOSE = time(15, 30)


def measure_close_performance(db: Session, trading_date: date, provider: MarketDataProvider) -> int:
    """Record the closing price for every pick made on trading_date. Idempotent. Returns rows added."""
    if not provider.capabilities.historical_prices:
        raise ProviderError(f"provider '{provider.name}' does not provide historical prices")
    tz = get_settings().tz
    close_ts = datetime.combine(trading_date, MARKET_CLOSE, tz)
    if utcnow() < close_ts:
        raise ValueError(f"market has not closed yet for {trading_date}")

    picks = db.scalars(
        select(StockPick)
        .join(ScanRun)
        .where(ScanRun.trading_date == trading_date, ScanRun.status.in_(PUBLISHED_STATUSES))
    ).all()
    existing = set(
        db.scalars(
            select(DailyPerformance.stock_pick_id).where(
                DailyPerformance.stock_pick_id.in_([p.id for p in picks]),
                DailyPerformance.measurement_type == "close",
            )
        ).all()
    )
    added = 0
    for p in picks:
        # Never mix sources: mock picks are only measured with mock prices and vice versa.
        if p.id in existing or p.scan_run.provider != provider.name:
            continue
        point = provider.get_price_at(p.symbol, close_ts)
        if point is None:  # missing data is recorded as missing, not invented
            log.warning("no close price available", extra={"symbol": p.symbol, "date": str(trading_date)})
            continue
        db.add(
            DailyPerformance(
                stock_pick_id=p.id,
                measurement_type="close",
                measurement_time=close_ts,
                measurement_price=point.price,
                return_pct=round((point.price - p.price_at_scan) / p.price_at_scan * 100, 4),
                provider=provider.name,
            )
        )
        added += 1
    db.commit()
    log.info("close performance recorded", extra={"date": str(trading_date), "rows": added})
    return added
