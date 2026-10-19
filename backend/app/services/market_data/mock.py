"""Deterministic synthetic data for development and tests.

Everything here is fabricated. Symbols are fictional (DEMOL001, DEMOM001, DEMOS001...) so they
cannot be mistaken for real NSE listings, and every scan made with this provider is flagged
is_mock_data=True and labelled as demo data in the API and UI.
"""

import hashlib
import math
import random
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.services.market_data.base import (
    DailyBar,
    MarketDataProvider,
    PricePoint,
    ProviderCapabilities,
    Quote,
    TransientProviderError,
    UniverseEntry,
)

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
SESSION_MINUTES = 375

# (prefix, count, typical price range, typical avg daily volume, daily volatility %)
_TIERS = [
    ("DEMOL", 100, (400, 4000), (1_500_000, 12_000_000), 1.2),
    ("DEMOM", 150, (150, 2500), (300_000, 3_000_000), 1.8),
    ("DEMOS", 200, (20, 900), (60_000, 1_500_000), 2.6),
]


def _rng(*parts) -> random.Random:
    seed = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return random.Random(int.from_bytes(seed[:8], "big"))


def _session_fraction(ts: datetime) -> float:
    """Fraction of the trading session elapsed at ts (0 before open, 1 after close)."""
    local = ts.astimezone(IST)
    minutes = (local.hour * 60 + local.minute + local.second / 60) - (MARKET_OPEN.hour * 60 + MARKET_OPEN.minute)
    return min(max(minutes / SESSION_MINUTES, 0.0), 1.0)


def _volume_curve(x: float) -> float:
    """Cumulative U-shaped intraday volume profile; monotonic, 0 at open and 1 at close."""
    return x + 0.15 * math.sin(2 * math.pi * x)


class MockProvider(MarketDataProvider):
    name = "mock"
    capabilities = ProviderCapabilities(
        intraday_quotes=True,
        historical_prices=True,
        same_time_volume_baseline=True,
        point_in_time_quotes=True,
        is_mock=True,
    )

    def __init__(self, fail_times: int = 0):
        # fail_times > 0 makes the next N get_quotes calls raise TransientProviderError (tests).
        self._fail_times = fail_times
        self.calls = 0
        self._meta = {}
        for prefix, count, prices, vols, vol_pct in _TIERS:
            for i in range(1, count + 1):
                sym = f"{prefix}{i:03d}"
                r = _rng("meta", sym)
                self._meta[sym] = {
                    "name": f"Demo {prefix[4:]}-Tier Co {i:03d}",
                    "base_price": round(r.uniform(*prices), 2),
                    "avg_volume": int(r.uniform(*vols)),
                    "vol_pct": vol_pct * r.uniform(0.6, 1.5),
                }

    # --- deterministic price/volume model -------------------------------------------------

    def _prev_close(self, sym: str, d: date) -> float:
        m = self._meta[sym]
        day_index = (d - date(2026, 1, 1)).days
        drift = 1 + 0.25 * math.sin(day_index / 40 + _rng("phase", sym).random() * 6)
        return round(m["base_price"] * drift, 2)

    def _day_params(self, sym: str, d: date) -> tuple[float, float, float]:
        m = self._meta[sym]
        r = _rng("day", sym, d.isoformat())
        gap = r.gauss(0, m["vol_pct"] * 0.4) / 100
        day_ret = r.gauss(0, m["vol_pct"]) / 100
        vol_mult = math.exp(r.gauss(0, 0.45))
        if r.random() < 0.03:  # occasional news-driven spike
            vol_mult *= r.uniform(3, 6)
            day_ret *= 2.5
        return gap, day_ret, vol_mult

    def _price_at(self, sym: str, ts: datetime) -> float:
        d = ts.astimezone(IST).date()
        prev = self._prev_close(sym, d)
        gap, day_ret, _ = self._day_params(sym, d)
        x = _session_fraction(ts)
        wiggle = 0.002 * math.sin(x * 17 + len(sym))
        return round(prev * (1 + gap) * (1 + day_ret * x + wiggle * x), 2)

    # --- provider interface ---------------------------------------------------------------

    def list_universe(self) -> list[UniverseEntry]:
        return [UniverseEntry(sym, m["name"]) for sym, m in self._meta.items()]

    def get_quotes(self, symbols: list[str], as_of: datetime) -> dict[str, Quote]:
        self.calls += 1
        if self._fail_times > 0:
            self._fail_times -= 1
            raise TransientProviderError("mock transient failure")

        d = as_of.astimezone(IST).date()
        x = _session_fraction(as_of)
        out: dict[str, Quote] = {}
        for sym in symbols:
            if sym not in self._meta:
                continue
            m = self._meta[sym]
            gap, _, vol_mult = self._day_params(sym, d)
            _, _, prev_mult = self._day_params(sym, d - timedelta(days=1))
            q = _rng("quality", sym, d.isoformat(), as_of.astimezone(IST).hour)
            roll = q.random()

            ts = as_of
            session_volume: int | None = int(m["avg_volume"] * vol_mult * _volume_curve(x))
            flags: dict = {}
            suspended = False
            if roll < 0.02:
                ts = as_of - timedelta(minutes=25)
                flags["simulated"] = "stale_timestamp"
            elif roll < 0.03:
                session_volume = None
                flags["simulated"] = "missing_volume"
            elif roll < 0.035:
                suspended = True
                flags["simulated"] = "suspended"

            out[sym] = Quote(
                symbol=sym,
                data_timestamp=ts,
                last_price=self._price_at(sym, ts) if x > 0 else round(self._prev_close(sym, d) * (1 + gap), 2),
                open_price=round(self._prev_close(sym, d) * (1 + gap), 2),
                previous_close=self._prev_close(sym, d),
                session_volume=session_volume,
                previous_session_volume=int(m["avg_volume"] * prev_mult),
                avg_daily_volume=float(m["avg_volume"]),
                same_time_avg_volume=float(m["avg_volume"] * _volume_curve(x)) if x > 0 else None,
                is_suspended=suspended,
                flags=flags,
            )
        return out

    def get_price_at(self, symbol: str, at: datetime) -> PricePoint | None:
        if symbol not in self._meta:
            return None
        return PricePoint(symbol, at, self._price_at(symbol, at))

    def get_daily_history(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        if symbol not in self._meta:
            return []
        from app.core.trading_calendar import get_calendar

        bars = []
        for d in get_calendar().trading_days(start, end):
            open_ts = datetime.combine(d, MARKET_OPEN, IST)
            close_ts = datetime.combine(d, MARKET_CLOSE, IST)
            o, c = self._price_at(symbol, open_ts), self._price_at(symbol, close_ts)
            _, _, vol_mult = self._day_params(symbol, d)
            bars.append(
                DailyBar(
                    symbol=symbol,
                    trading_date=d,
                    open=o,
                    high=round(max(o, c) * 1.004, 2),
                    low=round(min(o, c) * 0.996, 2),
                    close=c,
                    volume=int(self._meta[symbol]["avg_volume"] * vol_mult),
                )
            )
        return bars
