"""Operational CLI: `python -m app.cli <command>`.

  seed-mock-classification         load the fictional mock universe (development only)
  import-amfi FILE --version V --effective-date YYYY-MM-DD
  run-scan --session morning|afternoon [--date D] [--scan-type manual|scheduled] [--at-scheduled-time]
  backfill-mock --from D --to D    mock provider only: generate demo history for past trading days
  measure-performance --date D
"""

import argparse
import sys
from datetime import date, datetime, timezone

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.trading_calendar import get_calendar
from app.db.session import get_sessionmaker
from app.models import ScanSession, ScanType
from app.services.classification import import_mock_classification, parse_amfi_file, save_classification
from app.services.market_data import get_provider
from app.services.performance import measure_close_performance
from app.services.scanner import ScanRefused, run_scan, scheduled_time


def _today() -> date:
    return datetime.now(timezone.utc).astimezone(get_settings().tz).date()


def main(argv: list[str] | None = None) -> int:
    configure_logging("WARNING")
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seed-mock-classification")

    imp = sub.add_parser("import-amfi")
    imp.add_argument("file")
    imp.add_argument("--version", required=True, help="e.g. amfi-2026H2")
    imp.add_argument("--effective-date", required=True, type=date.fromisoformat)

    rs = sub.add_parser("run-scan")
    rs.add_argument("--session", required=True, choices=[s.value for s in ScanSession])
    rs.add_argument("--date", type=date.fromisoformat)
    rs.add_argument("--scan-type", default="manual", choices=[t.value for t in ScanType])
    rs.add_argument("--at-scheduled-time", action="store_true", help="point-in-time providers only")

    bf = sub.add_parser("backfill-mock")
    bf.add_argument("--from", dest="start", required=True, type=date.fromisoformat)
    bf.add_argument("--to", dest="end", required=True, type=date.fromisoformat)

    mp = sub.add_parser("measure-performance")
    mp.add_argument("--date", type=date.fromisoformat)

    args = p.parse_args(argv)
    settings, factory, provider = get_settings(), get_sessionmaker(), get_provider()

    if args.cmd == "seed-mock-classification":
        with factory() as db:
            cv = import_mock_classification(db, provider, _today())
        print(f"loaded mock classification {cv.version}")
        return 0

    if args.cmd == "import-amfi":
        stocks = parse_amfi_file(args.file)
        with factory() as db:
            cv = save_classification(db, stocks, args.version, source=f"AMFI file {args.file}", effective_date=args.effective_date)
        print(f"imported {len(stocks)} symbols as {cv.version}")
        return 0

    if args.cmd == "run-scan":
        d, s = args.date or _today(), ScanSession(args.session)
        as_of = scheduled_time(d, s, settings) if args.at_scheduled_time else None
        try:
            run = run_scan(factory, d, s, provider=provider, scan_type=ScanType(args.scan_type), trigger="cli", as_of=as_of)
        except ScanRefused as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        print(f"run {run.id}: {run.status} {run.error_message or ''}")
        return 0 if run.status != "failed" else 1

    if args.cmd == "backfill-mock":
        if not provider.capabilities.is_mock:
            print("backfill-mock only works with MARKET_DATA_PROVIDER=mock", file=sys.stderr)
            return 2
        now = datetime.now(timezone.utc)
        for d in get_calendar().trading_days(args.start, args.end):
            for s in ScanSession:
                at = scheduled_time(d, s, settings)
                if at > now:
                    continue
                try:
                    run = run_scan(factory, d, s, provider=provider, trigger="cli", as_of=at)
                    print(f"{d} {s.value}: {run.status}")
                except ScanRefused as exc:
                    print(f"{d} {s.value}: skipped ({exc.code})")
            if datetime.combine(d, settings.performance_job_time, settings.tz) <= now:
                with factory() as db:
                    measure_close_performance(db, d, provider)
        return 0

    if args.cmd == "measure-performance":
        with factory() as db:
            n = measure_close_performance(db, args.date or _today(), provider)
        print(f"added {n} performance rows")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
