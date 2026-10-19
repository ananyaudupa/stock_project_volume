"""Yahoo adapter tests with a fake downloader (no network)."""

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from app.services.market_data.base import ProviderError, TransientProviderError
from app.services.market_data.yahoo import YahooProvider
from tests.conftest import IST

TODAY = date(2026, 10, 16)
AS_OF = datetime(2026, 10, 16, 15, 0, tzinfo=IST)


def daily_frame(ticker, n_past=25, today=True, split_today=False, close=100.0, volume=1_000_000):
    days = pd.bdate_range(end=pd.Timestamp(TODAY) - pd.Timedelta(days=1), periods=n_past)
    rows = [dict(Open=close, High=close, Low=close, Close=close, **{"Adj Close": close}, Volume=volume,
                 Dividends=0.0, **{"Stock Splits": 0.0}) for _ in days]
    idx = list(days)
    if today:
        rows.append(dict(Open=101.0, High=106, Low=100, Close=105.0, **{"Adj Close": 105.0}, Volume=1_800_000,
                         Dividends=0.0, **{"Stock Splits": 2.0 if split_today else 0.0}))
        idx.append(pd.Timestamp(TODAY))
    df = pd.DataFrame(rows, index=pd.DatetimeIndex(idx))
    df.columns = pd.MultiIndex.from_product([[ticker], df.columns])
    return df


def minute_frame(ticker, last=datetime(2026, 10, 16, 14, 59, tzinfo=IST), n=10, price=105.0):
    idx = pd.DatetimeIndex([last - timedelta(minutes=k) for k in range(n - 1, -1, -1)])
    df = pd.DataFrame({"Open": price, "High": price, "Low": price, "Close": price, "Adj Close": price, "Volume": 1000}, index=idx)
    df.columns = pd.MultiIndex.from_product([[ticker], df.columns])
    return df


def fake(daily: dict, minute: dict):
    def dl(tickers, **kw):
        src = minute if kw.get("interval") == "1m" else daily
        frames = [src[t] for t in tickers if t in src]
        return pd.concat(frames, axis=1) if frames else pd.DataFrame()
    return dl


def test_builds_quote_from_daily_and_minute_bars():
    p = YahooProvider(fake({"AAA.NS": daily_frame("AAA.NS")}, {"AAA.NS": minute_frame("AAA.NS")}))
    q = p.get_quotes(["AAA"], AS_OF)["AAA"]
    assert q.previous_close == 100.0
    assert q.last_price == 105.0
    assert q.data_timestamp == AS_OF  # 14:59 bar closes at 15:00
    assert q.session_volume == 1_800_000 and q.flags["session_volume_source"] == "daily_bar_running_total"
    assert q.previous_session_volume == 1_000_000
    assert q.avg_daily_volume == 1_000_000  # today's partial bar excluded from the average
    assert q.same_time_avg_volume is None
    assert q.open_price == 101.0


def test_unknown_symbol_is_absent_not_invented():
    p = YahooProvider(fake({"AAA.NS": daily_frame("AAA.NS")}, {"AAA.NS": minute_frame("AAA.NS")}))
    assert set(p.get_quotes(["AAA", "NOPE"], AS_OF)) == {"AAA"}


def test_no_minute_bars_means_no_price_or_timestamp():
    p = YahooProvider(fake({"AAA.NS": daily_frame("AAA.NS")}, {}))
    q = p.get_quotes(["AAA"], AS_OF)["AAA"]
    assert q.last_price is None and q.data_timestamp is None


def test_bars_after_as_of_and_old_days_are_ignored():
    m = minute_frame("AAA.NS", last=datetime(2026, 10, 16, 15, 10, tzinfo=IST), n=30)
    q = YahooProvider(fake({"AAA.NS": daily_frame("AAA.NS")}, {"AAA.NS": m})).get_quotes(["AAA"], AS_OF)["AAA"]
    assert q.data_timestamp <= AS_OF
    old = minute_frame("AAA.NS", last=datetime(2026, 10, 15, 15, 29, tzinfo=IST))
    q = YahooProvider(fake({"AAA.NS": daily_frame("AAA.NS")}, {"AAA.NS": old})).get_quotes(["AAA"], AS_OF)["AAA"]
    assert q.data_timestamp is None


def test_short_history_gives_no_average_volume():
    p = YahooProvider(fake({"AAA.NS": daily_frame("AAA.NS", n_past=5)}, {"AAA.NS": minute_frame("AAA.NS")}))
    assert p.get_quotes(["AAA"], AS_OF)["AAA"].avg_daily_volume is None


def test_split_today_is_flagged():
    p = YahooProvider(fake({"AAA.NS": daily_frame("AAA.NS", split_today=True)}, {"AAA.NS": minute_frame("AAA.NS")}))
    assert p.get_quotes(["AAA"], AS_OF)["AAA"].unadjusted_corporate_action is True


def test_falls_back_to_summed_minute_volume_without_daily_today():
    p = YahooProvider(fake({"AAA.NS": daily_frame("AAA.NS", today=False)}, {"AAA.NS": minute_frame("AAA.NS")}))
    q = p.get_quotes(["AAA"], AS_OF)["AAA"]
    assert q.session_volume == 10_000 and q.flags["session_volume_source"] == "sum_1m_bars"


def test_empty_response_is_transient_and_chunks_are_used():
    calls = []

    def dl(tickers, **kw):
        calls.append(len(tickers))
        return pd.DataFrame()

    with pytest.raises(TransientProviderError):
        YahooProvider(dl, chunk_size=2).get_quotes(["A", "B", "C"], AS_OF)
    assert calls == [2, 2]


def test_daily_history_and_close_price():
    p = YahooProvider(fake({"AAA.NS": daily_frame("AAA.NS")}, {}))
    bars = p.get_daily_history("AAA", date(2026, 10, 1), TODAY)
    assert bars[-1].trading_date == TODAY and bars[-1].close == 105.0
    close = p.get_price_at("AAA", datetime(2026, 10, 16, 15, 30, tzinfo=IST))
    assert close.price == 105.0
    with pytest.raises(ProviderError):
        p.get_price_at("AAA", datetime(2026, 10, 16, 12, 0, tzinfo=IST))


def test_capabilities_are_honest():
    caps = YahooProvider().capabilities
    assert caps.is_mock is False and caps.point_in_time_quotes is False and caps.same_time_volume_baseline is False
