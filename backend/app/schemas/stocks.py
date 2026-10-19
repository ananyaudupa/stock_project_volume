from datetime import date

from pydantic import BaseModel

from app.schemas.scans import PickOut


class PickWithContext(PickOut):
    trading_date: date
    session: str
    scan_type: str
    run_id: int
    is_mock_data: bool


class DailyBarOut(BaseModel):
    trading_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


class StockHistoryOut(BaseModel):
    symbol: str
    from_date: date
    to_date: date
    picks: list[PickWithContext]
    price_history_supported: bool
    price_history: list[DailyBarOut]
    price_history_is_mock: bool
    note: str | None = None
