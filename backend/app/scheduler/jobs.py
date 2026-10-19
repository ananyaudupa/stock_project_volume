"""Scheduled job bodies. Kept free of APScheduler so they can be unit-tested directly."""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.trading_calendar import TradingCalendar, get_calendar
from app.db.session import get_sessionmaker
from app.models import ScanRun, ScanSession, ScanType
from app.models.enums import PUBLISHED_STATUSES
from app.services import queries
from app.services.alerts import send_alert
from app.services.market_data import get_provider
from app.services.market_data.base import MarketDataProvider, ProviderError
from app.services.performance import measure_close_performance
from app.services.scanner import ScanAlreadyPublished, ScanInProgress, run_scan, scheduled_time

log = logging.getLogger("scheduler")

MISSING_SCAN_GRACE = timedelta(minutes=20)


def _deps(factory, provider, settings, calendar, now):
    return (
        factory or get_sessionmaker(),
        provider or get_provider(),
        settings or get_settings(),
        calendar or get_calendar(),
        now or datetime.now(timezone.utc),
    )


def scheduled_scan_job(
    session: ScanSession,
    *,
    factory: sessionmaker[Session] | None = None,
    provider: MarketDataProvider | None = None,
    settings: Settings | None = None,
    calendar: TradingCalendar | None = None,
    now: datetime | None = None,
) -> ScanRun | None:
    factory, provider, settings, calendar, now = _deps(factory, provider, settings, calendar, now)
    today = now.astimezone(settings.tz).date()
    reason = calendar.non_trading_reason(today)
    if reason == "calendar_unknown":
        send_alert("calendar_unknown", f"NSE holiday calendar for {today.year} is not loaded; {session} scan skipped")
        return None
    if reason or calendar.is_special_session(today):
        log.info("not a regular trading day, scan skipped", extra={"date": str(today), "reason": reason or "special_session"})
        return None
    try:
        return run_scan(factory, today, session, provider=provider, scan_type=ScanType.SCHEDULED,
                        trigger="scheduler", settings=settings, calendar=calendar)
    except (ScanAlreadyPublished, ScanInProgress) as exc:
        log.info("duplicate scheduled run suppressed", extra={"date": str(today), "session": session.value, "reason": str(exc)})
        return None


def missing_scan_watchdog(
    *, factory=None, settings=None, calendar=None, now=None
) -> list[str]:
    """Alert if a session's scheduled time has passed (plus grace) without a published snapshot."""
    factory = factory or get_sessionmaker()
    settings = settings or get_settings()
    calendar = calendar or get_calendar()
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(settings.tz).date()
    if calendar.non_trading_reason(today):
        return []
    missing = []
    with factory() as db:
        for s in ScanSession:
            if now < scheduled_time(today, s, settings) + MISSING_SCAN_GRACE:
                continue
            run = queries.display_run(db, today, s)
            if run is None or run.status not in PUBLISHED_STATUSES:
                missing.append(s.value)
                send_alert("scan_missing", f"No published {s.value} snapshot for {today}",
                           status=run.status if run else "none")
    return missing


def performance_job(*, factory=None, provider=None, settings=None, calendar=None, now=None) -> int:
    factory, provider, settings, calendar, now = _deps(factory, provider, settings, calendar, now)
    today = now.astimezone(settings.tz).date()
    if calendar.non_trading_reason(today):
        return 0
    with factory() as db:
        try:
            return measure_close_performance(db, today, provider)
        except (ProviderError, ValueError) as exc:
            log.warning("performance measurement skipped", extra={"reason": str(exc)})
            return 0
