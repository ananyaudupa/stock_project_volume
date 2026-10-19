"""Entry point for an external cron (GitHub Actions): `python -m app.scheduler.cron`.

The cron fires a few times around each target time (as a backup, because hosted crons can
start late or skip). Each invocation works out what is due from the current IST time:

  morning scan      MORNING_SCAN_TIME   .. +90 min
  afternoon scan    AFTERNOON_SCAN_TIME .. 15:30
  close performance PERFORMANCE_JOB_TIME .. 20:00

Duplicate invocations are harmless: a published scan is never re-run (see services/scanner.py).
Exit code 1 = a scan failed, so the hosting cron reports/email-alerts the failure.
"""

import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import get_sessionmaker
from app.models import ClassificationVersion, ScanSession
from app.scheduler.jobs import performance_job, scheduled_scan_job
from app.services.classification import parse_amfi_file, save_classification

AMFI_DIR = Path(__file__).resolve().parent.parent / "data" / "amfi"
# (file, version, effective date) - add a row each January and July when AMFI publishes a new list.
BUNDLED_AMFI = [
    ("AverageMarketCapitalization30Jun2026.xlsx", "amfi-2026H2", date(2026, 7, 1)),
]

MORNING_WINDOW = timedelta(minutes=90)
AFTERNOON_END = time(15, 30)
PERFORMANCE_END = time(20, 0)


def due_job(now: datetime, settings: Settings) -> str | None:
    local = now.astimezone(settings.tz)
    t = local.time()
    d = local.date()
    morning_start = datetime.combine(d, settings.morning_scan_time, settings.tz)
    if morning_start <= local < morning_start + MORNING_WINDOW:
        return "morning"
    if settings.afternoon_scan_time <= t < AFTERNOON_END:
        return "afternoon"
    if settings.performance_job_time <= t < PERFORMANCE_END:
        return "performance"
    return None


def ensure_classification(factory, today: date) -> list[str]:
    """Import any bundled AMFI list that isn't in the database yet. Returns versions imported."""
    imported = []
    with factory() as db:
        have = set(db.scalars(select(ClassificationVersion.version)).all())
        current = db.scalar(select(ClassificationVersion).where(ClassificationVersion.is_current.is_(True)))
        for fname, version, effective in sorted(BUNDLED_AMFI, key=lambda r: r[2]):
            if version in have or effective > today:
                continue
            make_current = current is None or current.is_mock or effective >= current.effective_date
            stocks = parse_amfi_file(AMFI_DIR / fname)
            cv = save_classification(db, stocks, version, source=f"AMFI {fname}", effective_date=effective,
                                     make_current=make_current)
            if make_current:
                current = cv
            imported.append(version)
    return imported


def main(now: datetime | None = None, factory=None, settings: Settings | None = None, **job_deps) -> int:
    configure_logging()
    settings = settings or get_settings()
    factory = factory or get_sessionmaker()
    now = now or datetime.now(timezone.utc)
    job = due_job(now, settings)
    print(f"now {now.astimezone(settings.tz):%Y-%m-%d %H:%M} IST -> {job or 'nothing due'}")
    if job is None:
        return 0

    imported = ensure_classification(factory, now.astimezone(settings.tz).date())
    if imported:
        print(f"imported classification: {', '.join(imported)}")

    if job == "performance":
        n = performance_job(factory=factory, settings=settings, now=now, **job_deps)
        print(f"close performance rows added: {n}")
        return 0

    run = scheduled_scan_job(ScanSession(job), factory=factory, settings=settings, now=now, **job_deps)
    if run is None:
        print("skipped (not a trading day, or already done)")
        return 0
    print(f"run {run.id}: {run.status} {run.error_message or ''}")
    return 1 if run.status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
