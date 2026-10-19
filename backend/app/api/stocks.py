from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, now_dep, provider_dep, settings_dep
from app.core.config import Settings
from app.core.errors import ApiError
from app.models import ScanRun, StockPick
from app.schemas.stocks import DailyBarOut, PickWithContext, StockHistoryOut
from app.services import queries as q
from app.services.market_data.base import MarketDataProvider, ProviderError

router = APIRouter(prefix="/api", tags=["stocks"])

SYMBOL_PATTERN = r"^[A-Z0-9][A-Z0-9&\-]{0,31}$"
MAX_RANGE_DAYS = 366


def _with_context(pick: StockPick, run: ScanRun, settings: Settings, perf) -> PickWithContext:
    base = q.pick_out(pick, settings, perf).model_dump()
    return PickWithContext(
        **base, trading_date=run.trading_date, session=run.session, scan_type=run.scan_type, run_id=run.id,
        is_mock_data=run.is_mock_data,
    )


@router.get("/stocks/{symbol}/history", response_model=StockHistoryOut)
def stock_history(
    symbol: str = Path(pattern=SYMBOL_PATTERN),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    provider: MarketDataProvider = Depends(provider_dep),
    now: datetime = Depends(now_dep),
):
    to =to or now.astimezone(settings.tz).date()
    from_ = from_ or to - timedelta(days=30)
    if from_ > to:
        raise ApiError(422, "invalid_range", "'from' must not be after 'to'")
    if (to - from_).days >= MAX_RANGE_DAYS:
        raise ApiError(422, "range_too_large", f"date range may span at most {MAX_RANGE_DAYS} days")

    rows = q.picks_for_symbol(db, symbol, from_, to)
    perf = q._perf_by_pick(db, [p.id for p, _ in rows])
    picks = [_with_context(p, r, settings, perf.get(p.id)) for p, r in rows]

    bars, note = [], None
    supported = provider.capabilities.historical_prices
    if supported:
        try:
            bars = [DailyBarOut(**{k: getattr(b, k) for k in DailyBarOut.model_fields}) for b in provider.get_daily_history(symbol, from_, to)]
        except ProviderError:
            supported, note = False, "Price history is temporarily unavailable from the data provider."
    else:
        note = "The configured data provider does not supply historical prices."
    return StockHistoryOut(
        symbol=symbol, from_date=from_, to_date=to, picks=picks, price_history_supported=supported,
        price_history=bars, price_history_is_mock=provider.capabilities.is_mock, note=note,
    )


@router.get("/picks/{pick_id}", response_model=PickWithContext)
def pick_detail(pick_id: int, db: Session = Depends(get_db), settings: Settings = Depends(settings_dep)):
    row = db.execute(select(StockPick, ScanRun).join(ScanRun).where(StockPick.id == pick_id)).first()
    if row is None:
        raise ApiError(404, "pick_not_found", f"No pick with id {pick_id}")
    pick, run = row
    return _with_context(pick, run, settings, q._perf_by_pick(db, [pick.id]).get(pick.id))
