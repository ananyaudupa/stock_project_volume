# Design decisions and open items

## What is already decided in the code

### The 09:15 morning scan does not rank on intraday volume
At 09:15 continuous trading has only just started, so accumulated volume is close to zero.
The morning scan ranks two things instead:

- the **opening move**: open or latest price vs previous close
- **previous-session relative volume**: previous session's volume ÷ 20-day average daily volume

Each pick stores the intraday volume at scan time for transparency, but that figure is not
used in the score. The API and UI show this method note on every morning snapshot. If you
would rather rank on real intraday volume, set `MORNING_SCAN_TIME=09:30`. You would also have
to change the morning branch in `services/ranking.py` to use the same-time baseline.

### Afternoon relative volume
The afternoon scan compares session volume so far with the provider's *typical volume by the
same time of day*. If the provider doesn't supply that baseline, the code falls back to a
pro-rated daily average. That fallback ignores the U-shaped intraday volume pattern, so each
affected pick is labelled `pro_rata_daily`.

### Scoring (`pctrank-v1`)
- `volume_score` and `movement_score` are **percentile ranks** within each category's eligible
  set, from 0 to 1. Percentile ranks are robust to outliers such as one 40× volume spike.
- `final_score = w_v·volume_score + w_m·movement_score`. The weights come from env and are
  normalised to sum to 1.
- Ties are broken by movement, then relative volume, then symbol. The result is fully
  deterministic.
- Gainers and losers both qualify, because ranking uses `|change|`.
- Each run stores its weights, thresholds and algorithm version in `scan_runs.config`.

### Eligibility (a stock is excluded, never patched)
A stock is excluded and counted per reason in `scan_runs.summary.exclusions` if any of these apply:

- no quote, or a missing timestamp
- price older than `MAX_DATA_STALENESS_SECONDS` (300 s), or a timestamp in the future
- invalid price, or missing previous close
- suspended
- corporate action today with an unadjusted previous close
- no volume baseline
- illiquid: average daily traded value below `MIN_AVG_TRADED_VALUE_INR` (₹50 lakh)
- move larger than 35% (treated as bad data, since NSE price bands top out at 20%)
- not classified

Special sessions such as Muhurat trading are not scanned.

### Publishing rules
- **One run per (date, session, scan_type).** Retries reuse the same row. Each retry is
  recorded in `scan_attempts`.
- **Claiming a run is a conditional UPDATE.** It can move a run from pending, failed, or
  abandoned-running (older than 15 min) to running. Two workers can never run the same scan.
- **Publishing is one transaction:** snapshots, all picks, then status. If coverage of fresh
  quotes is below `MIN_UNIVERSE_COVERAGE` (80%), the run fails rather than publishing.
- **Published runs are never re-run or changed.** `stock_picks` and `daily_performance` reject
  UPDATEs in the ORM and, on Postgres, with a trigger.
- **Partial runs.** A run with fewer than 5 eligible stocks in any category is published as
  `partial`, and an alert is sent.
- **Scheduled beats manual.** If both a scheduled and a manual run exist for the same session,
  the scheduled one is shown.
- **Transient provider errors** are retried with bounded exponential backoff: 3 retries,
  starting at 2 s.
- **Alerts** for failed, partial or missing scans and for an unknown calendar year are logged,
  and also POSTed to `ALERT_WEBHOOK_URL` if it is set. A watchdog runs every 10 minutes during
  market hours.

### Calendar
`app/data/nse_holidays.json` holds the 2026 list. **Check it against the official NSE circular
before relying on it.** A year missing from the file is treated as *unknown*: the scheduler
skips the scan and sends an alert, rather than guessing.

## Decisions still needed (spec §16)

1. **Market-data provider.** Implement an adapter (see `data-provider.md`), and confirm the
   licence covers display, storage and the intended audience.
2. **09:15 methodology.** The default is the baseline-based opening scan described above.
   Confirm it, or move the scan to 09:30.
3. **Classification source.** Import AMFI's half-yearly list with `app.cli import-amfi`. Decide
   who refreshes it, and when (AMFI publishes in January and July).
4. **Deployment audience.** Personal, internal or public. This affects licensing, auth on the
   read API, and HTTPS/hosting.
5. **Retention.** Nothing is purged today. Set a retention period that fits the provider's terms.
   `market_data_snapshots` grows by about 450 rows per scan.
6. **Ranking policy.** Backtest the 50/50 weights against `daily_performance` before relying on
   them. Past activity does not predict returns.
