"""Yahoo Finance adapter (via the unofficial `yfinance` library). Free, no account, no login.

Limits to be aware of
---------------------
* Unofficial: Yahoo can change or rate-limit it without notice. Failures surface as
  TransientProviderError (retried, then the scan fails and the last snapshot is kept).
* Personal use only - Yahoo's terms do not permit redistributing its data publicly.
* Live quotes only (point_in_time_quotes=False): past scans cannot be backfilled.
* No same-time-of-day volume baseline, so the afternoon scan uses the pro-rated daily
  average (labelled "pro_rata_daily" on every pick).
* Minute bars appear ~1 minute after the open, so run the morning scan at 09:20, not 09:15.

Symbols are NSE symbols (e.g. RELIANCE); the ".NS" suffix is added here.
"""

import logging
import math
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.services.market_data.base import (
    DailyBar,
    MarketDataProvider,
    PricePoint,
    ProviderCapabilities,
    ProviderError,
    Quote,
    TransientProviderError,
    UniverseEntry,
)

log = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
SUFFIX = ".NS"
MARKET_CLOSE = time(15, 30)
AVG_VOLUME_SESSIONS = 20
MIN_AVG_VOLUME_SESSIONS = 10
BAR = timedelta(minutes=1)

# downloader(tickers, **yfinance.download kwargs) -> pandas DataFrame grouped by ticker
Downloader = Callable[..., object]


def _yf_download(tickers: list[str], **kwargs):
    import yfinance as yf

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)  # it logs every unknown symbol as an error
    try:
        return yf.download(
            tickers, group_by="ticker", auto_adjust=False, progress=False, threads=True, prepost=False, **kwargs
        )
    except Exception as exc:  # network errors, rate limiting, JSON decode errors...
        raise TransientProviderError(f"Yahoo download failed: {type(exc).__name__}: {exc}") from exc


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _frame_for(df, ticker: str):
    """Return the per-ticker frame (rows with a Close), or None if Yahoo had no data for it."""
    if df is None or getattr(df, "empty", True):
        return None
    cols = df.columns
    if getattr(cols, "nlevels", 1) > 1:
        if ticker not in cols.get_level_values(0):
            return None
        sub = df[ticker]
    else:
        sub = df
    sub = sub.dropna(subset=["Close"])
    return None if sub.empty else sub


def _local_date(ts) -> date:
    if getattr(ts, "tzinfo", None) is None:
        return ts.date()
    return ts.astimezone(IST).date()


class YahooProvider(MarketDataProvider):
    name = "yahoo"
    capabilities = ProviderCapabilities(
        intraday_quotes=True,
        historical_prices=True,
        same_time_volume_baseline=False,
        point_in_time_quotes=False,
        is_mock=False,
    )

    def __init__(self, downloader: Downloader | None = None, chunk_size: int = 100):
        self._download = downloader or _yf_download
        self._chunk = chunk_size

    def list_universe(self) -> list[UniverseEntry]:
        # The universe comes from the imported AMFI classification, not from Yahoo.
        return []

    def get_quotes(self, symbols: list[str], as_of: datetime) -> dict[str, Quote]:
        out: dict[str, Quote] = {}
        trading_date = as_of.astimezone(IST).date()
        for i in range(0, len(symbols), self._chunk):
            chunk = symbols[i : i + self._chunk]
            tickers = [s + SUFFIX for s in chunk]
            daily = self._download(tickers, period="3mo", interval="1d", actions=True)
            intraday = self._download(tickers, period="1d", interval="1m")
            if getattr(daily, "empty", True) and getattr(intraday, "empty", True):
                raise TransientProviderError(f"Yahoo returned no data for {len(chunk)} symbols (rate limited or down?)")
            for sym, ticker in zip(chunk, tickers):
                q = self._build_quote(sym, _frame_for(daily, ticker), _frame_for(intraday, ticker), trading_date, as_of)
                if q is not None:
                    out[sym] = q
        return out

    @staticmethod
    def _build_quote(sym, daily, intraday, trading_date: date, as_of: datetime) -> Quote | None:
        if daily is None and intraday is None:
            return None  # unknown to Yahoo -> simply absent, never invented

        prev_close = prev_volume = avg_volume = today_row = None
        if daily is not None:
            dates = [_local_date(ts) for ts in daily.index]
            past_idx = [k for k, d in enumerate(dates) if d < trading_date]
            today_idx = [k for k, d in enumerate(dates) if d == trading_date]
            if past_idx:
                past = daily.iloc[past_idx]
                prev_close = _num(past["Close"].iloc[-1])
                prev_volume = _num(past["Volume"].iloc[-1])
                vols = [v for v in (_num(x) for x in past["Volume"].iloc[-AVG_VOLUME_SESSIONS:]) if v is not None and v > 0]
                avg_volume = sum(vols) / len(vols) if len(vols) >= MIN_AVG_VOLUME_SESSIONS else None
            if today_idx:
                today_row = daily.iloc[today_idx[-1]]

        last_price = data_ts = open_price = None
        minute_volume = None
        if intraday is not None:
            bars = intraday[[(_local_date(ts) == trading_date and ts <= as_of) for ts in intraday.index]]
            if not bars.empty:
                last_price = _num(bars["Close"].iloc[-1])
                bar_start = bars.index[-1].to_pydatetime()
                data_ts = min(bar_start + BAR, as_of)
                open_price = _num(bars["Open"].iloc[0])
                minute_volume = int(sum(v for v in (_num(x) for x in bars["Volume"]) if v is not None))

        # Yahoo's running daily total is more complete than summed minute bars (~3-15% higher),
        # and it matches how avg_volume is measured.
        session_volume, volume_source = minute_volume, "sum_1m_bars"
        if today_row is not None and _num(today_row["Volume"]) is not None:
            session_volume, volume_source = int(_num(today_row["Volume"])), "daily_bar_running_total"
            open_price = _num(today_row["Open"]) or open_price

        split_today = today_row is not None and (_num(today_row.get("Stock Splits")) or 0) != 0
        return Quote(
            symbol=sym,
            data_timestamp=data_ts,
            last_price=last_price,
            open_price=open_price,
            previous_close=prev_close,
            session_volume=session_volume,
            previous_session_volume=int(prev_volume) if prev_volume is not None else None,
            avg_daily_volume=avg_volume,
            same_time_avg_volume=None,
            unadjusted_corporate_action=split_today,
            flags={"source": "yahoo", "session_volume_source": volume_source},
        )

    def get_daily_history(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        ticker = symbol + SUFFIX
        df = _frame_for(self._download([ticker], start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(), interval="1d"), ticker)
        if df is None:
            return []
        bars = []
        for ts, row in df.iterrows():
            vals = [_num(row[c]) for c in ("Open", "High", "Low", "Close", "Volume")]
            if None in vals:
                continue
            o, h, low, c, v = vals
            bars.append(DailyBar(symbol, _local_date(ts), o, h, low, c, int(v)))
        return [b for b in bars if start <= b.trading_date <= end]

    def get_price_at(self, symbol: str, at: datetime) -> PricePoint | None:
        local = at.astimezone(IST)
        if local.time() < MARKET_CLOSE:
            raise ProviderError("Yahoo adapter only supports closing prices for performance measurement")
        for bar in self.get_daily_history(symbol, local.date(), local.date()):
            if bar.trading_date == local.date():
                return PricePoint(symbol, datetime.combine(local.date(), MARKET_CLOSE, IST), bar.close)
        return None
