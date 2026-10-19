# Market-data providers

## Current choice: Yahoo Finance (`yahoo`)

Chosen because the project must be free and run with nobody having to do anything daily.

**Brokers that were checked:**
- **Sharekhan and IIFL:** both have free APIs, but each needs a manual browser login with OTP
  every trading day.
- **Groww:** its API is paid.
- **Econo Broking:** no public API.
- **Angel One:** would allow automatic login, but it needs a new account, so it was ruled out.

**How the Yahoo adapter works** (`services/market_data/yahoo.py`):
- **Two batch downloads per 100 symbols:** daily bars for 3 months, and today's 1-minute bars.
- **Previous close, previous-session volume and the 20-day average** come from the daily bars.
  Today's partial bar is left out of the average.
- **Last price and timestamp** come from the latest 1-minute bar at or before scan time.
- **Volume so far today** is Yahoo's running daily total. Summing the minute bars gives 3–15%
  less, as measured on 2026-10-19.
- **Splits:** a stock split dated today is flagged, and that stock is excluded.
- **Unknown symbols** are simply absent from the results, and are excluded as `no_quote`.

**Known limits:**
- **Unofficial:** Yahoo may rate-limit or change its data. The scan retries, and if it still
  fails it is marked failed; the last good snapshot stays.
- **No same-time-of-day volume baseline:** afternoon relative volume uses the pro-rated daily
  average. Every stock is affected in the same way, so the order within a category barely
  changes, and each pick is labelled `pro_rata_daily`.
- **No backfill:** past scans cannot be recreated, because Yahoo only serves live quotes.
- **Personal use only:** Yahoo's terms do not allow redistributing its data publicly.

## Adding another provider

The scanner depends only on `MarketDataProvider` in
`backend/app/services/market_data/base.py`. To add a vendor:

1. Create `services/market_data/<vendor>.py` with a class that implements:
   - `list_universe()`
   - `get_quotes(symbols, as_of)`
   - `get_price_at()` and `get_daily_history()`, if the vendor supports historical data
2. Declare honest `capabilities`. For a live-only feed, set `point_in_time_quotes=False`. The
   scanner then refuses backfills instead of stamping today's prices on past dates. Set
   `is_mock=False`.
3. Map vendor errors to the right exception:
   - `TransientProviderError` for timeouts, 5xx responses and rate limits. These are retried.
   - `ProviderError` for auth, licence or bad-request errors. These fail the run immediately.
4. **Never fill in missing values.** If the vendor lacks a field, return `None`. The ranking
   engine excludes the stock and records the reason.
5. Register the class in `services/market_data/__init__.py:build_provider`. Then set
   `MARKET_DATA_PROVIDER=<vendor>`, and put the key in `MARKET_DATA_API_KEY` (in env or a
   secret manager, never in git).
6. Import a real AMFI classification. A mock classification is rejected when the provider is not
   mock.

## Checks before signing up (spec §4.3)

- [ ] Covers all NSE-listed equities in the AMFI list, not just index constituents
- [ ] Provides intraday last price, open, previous close and accumulated session volume, with exchange timestamps
- [ ] Provides a 20-day average daily volume, or enough daily history to compute it
- [ ] Ideally provides a same-time-of-day volume baseline; otherwise the pro-rata fallback is used
- [ ] Adjusts previous close for corporate actions, or flags ex-dates
- [ ] Has rate limits that allow about 450 symbols in one batch at 09:15 and 15:00
- [ ] Licence permits the intended display (personal, internal or public) **and** storage/retention of snapshots
- [ ] Provides historical daily bars, if you want the performance and history views
- [ ] Production use is allowed; free endpoints usually don't permit it
