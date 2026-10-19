# NSE Daily Stock Scanner

Scans NSE equities twice per trading day (09:15 and 15:00 IST) and keeps the top five
high-volume, fast-moving stocks in each market-cap category (Small, Mid, Large). Every snapshot
is stored permanently, so you can browse today's and past results.

> This is a screening and historical-analysis tool. Rankings measure price movement and volume
> only. They are not investment advice and they do not predict returns.

**Data source:** **Yahoo Finance** (`MARKET_DATA_PROVIDER=yahoo`). It is free, needs no account
and no daily login, and is for **personal use only**. With Yahoo the morning scan runs at 09:20,
because Yahoo has no minute data at 09:15. For development there is also a `mock` provider. It
generates fictional symbols (`DEMOL001`…), and the app labels everything it produces as demo data.
See [docs/data-provider.md](docs/data-provider.md).

## Layout

```
backend/   FastAPI + SQLAlchemy + Alembic + APScheduler (Python 3.12+)
  app/services/market_data/   provider adapter interface + mock provider
  app/services/ranking.py     pure, deterministic scoring engine
  app/services/scanner.py     run claiming, retries, transactional publish
  app/services/classification.py  AMFI rank -> category, versioned imports
  app/scheduler/              single worker: scans, close-performance, missed-scan watchdog
  app/data/nse_holidays.json  NSE holiday list (verify yearly)
  migrations/                 Alembic (includes a Postgres immutability trigger on picks)
frontend/  React + TypeScript + Vite single-page UI
docs/      design decisions and the provider checklist
```

## Quick start (local)

Prerequisites: Python 3.12+, Node 20+, and PostgreSQL. You can run PostgreSQL with `docker compose up db`.

```bash
cp .env.example .env            # then edit DATABASE_URL and set ADMIN_API_KEY

cd backend
python -m venv .venv && .venv/Scripts/activate      # (Linux/macOS: source .venv/bin/activate)
pip install -r requirements-dev.txt
alembic upgrade head
python -m app.cli seed-mock-classification         # fictional universe, dev only
python -m app.cli backfill-mock --from 2026-09-01 --to 2026-10-16   # demo history
uvicorn app.main:app --reload                      # API on :8000
python -m app.scheduler                            # in a second terminal: the scheduler worker

cd ../frontend
npm install
npm run dev                                        # UI on :5173 (proxies /api to :8000)
```

To run the whole backend in Docker instead: `docker compose up` starts db, api and scheduler.

## Tests

```bash
cd backend && pytest          # 85 tests: ranking, classification, scanner, API, scheduler, migrations
cd frontend && npm test       # 7 tests: selectors, loading/empty/error/stale states, compare, details
```

## API

| Method | Path | Notes |
|---|---|---|
| GET | `/api/scans/latest` | latest published morning and afternoon snapshots |
| GET | `/api/scans/status` | today (IST), previous trading day, last success, freshness, next scan |
| GET | `/api/scans/history?from=&to=&page=&page_size=` | per-day session status (max 366 days) |
| GET | `/api/scans/{date}/{session}` | all three categories |
| GET | `/api/scans/{date}/{session}/{category}` | `category` = `small-cap`, `mid-cap` or `large-cap` |
| GET | `/api/scans/{date}/compare?category=` | morning vs afternoon, with overlap |
| GET | `/api/stocks/{symbol}/history?from=&to=` | past picks + provider price history |
| GET | `/api/picks/{id}` | one pick with metrics and performance |
| POST | `/api/admin/scans/run` | needs the `X-Admin-Key` header |
| GET | `/api/admin/scans/{run_id}` | full run details, attempts and errors |
| POST | `/api/admin/performance/run` | records close prices for a date |

When there is no snapshot, the API returns `404` with one of these codes:
`non_trading_day`, `scan_not_yet_run`, `no_scan_recorded`, `calendar_unknown`. The UI shows these
as informational messages, not as errors. A run that failed returns `200` with `status: "failed"`
and an error message that is safe to show publicly. Read endpoints never trigger a scan.

## Operations CLI

```
python -m app.cli import-amfi amfi.csv --version amfi-2026H2 --effective-date 2026-07-01
python -m app.cli run-scan --session afternoon [--date D] [--scan-type manual]
python -m app.cli measure-performance --date 2026-10-16
```

## Before going to production

See [docs/decisions.md](docs/decisions.md). In short:

- choose and license a data provider
- confirm the 09:15 methodology
- import the current AMFI list
- verify the holiday file
- decide the deployment audience and retention period
- backtest the 50/50 weights
