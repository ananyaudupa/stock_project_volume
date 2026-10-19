"""Public, read-only scan endpoints. Nothing here triggers a market scan."""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import calendar_dep, get_db, now_dep, provider_dep, settings_dep
from app.core.config import Settings
from app.core.errors import ApiError
from app.core.trading_calendar import TradingCalendar, UnknownCalendarYear
from app.models import ScanSession
from app.models.enums import CapCategory
from app.schemas.scans import (
    CategorySnapshotOut,
    CompareOut,
    HistoryOut,
    LatestOut,
    SessionSnapshotOut,
    StatusOut,
)
from app.services import queries as q
from app.services.classification import current_universe
from app.services.market_data.base import MarketDataProvider

router = APIRouter(prefix="/api/scans", tags=["scans"])

MAX_HISTORY_DAYS = 366


def _not_found(d: date, session: ScanSession, cal: TradingCalendar, settings: Settings, now: datetime):
    code, message = q.missing_reason(d, session, cal, settings, now.astimezone(settings.tz))
    return ApiError(404, code, message, {"trading_date": d.isoformat(), "session": session.value})


@router.get("/latest", response_model=LatestOut)
def latest(db: Session = Depends(get_db), settings: Settings = Depends(settings_dep), now: datetime = Depends(now_dep)):
    def snap(s: ScanSession):
        run = q.latest_published_for_session(db, s)
        return q.session_snapshot(db, run, settings) if run else None

    return LatestOut(today=now.astimezone(settings.tz).date(), morning=snap(ScanSession.MORNING), afternoon=snap(ScanSession.AFTERNOON))


@router.get("/status", response_model=StatusOut)
def status(
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    cal: TradingCalendar = Depends(calendar_dep),
    provider: MarketDataProvider = Depends(provider_dep),
    now: datetime = Depends(now_dep),
):
    local = now.astimezone(settings.tz)
    today = local.date()
    try:
        trading = cal.is_trading_day(today)
        prev = cal.previous_trading_day(today)
    except UnknownCalendarYear:
        trading, prev = None, None

    next_scan = None
    try:
        for offset in range(0, 15):
            d = today + timedelta(days=offset)
            if not cal.is_trading_day(d):
                continue
            for t in (settings.morning_scan_time, settings.afternoon_scan_time):
                candidate = datetime.combine(d, t, settings.tz)
                if candidate > local:
                    next_scan = candidate
                    break
            if next_scan:
                break
    except UnknownCalendarYear:
        pass

    last_ok = q.last_successful_run(db)
    freshness = int((now - last_ok.data_as_of).total_seconds()) if last_ok and last_ok.data_as_of else None
    cv, _ = current_universe(db)
    return StatusOut(
        now=local, today=today, is_trading_day=trading, non_trading_reason=cal.non_trading_reason(today),
        previous_trading_day=prev, provider=provider.name, is_mock_data=provider.capabilities.is_mock,
        last_successful=q.last_run_out(last_ok, settings), latest_run=q.last_run_out(q.latest_run(db), settings),
        today_sessions={s.value: q.session_summary(q.display_run(db, today, s)) for s in ScanSession},
        next_scheduled_scan=next_scan, data_freshness_seconds=freshness,
        classification_version=cv.version if cv else None, calendar_years_loaded=cal.known_years(),
    )


@router.get("/history", response_model=HistoryOut, response_model_by_alias=True)
def history(
    from_: date = Query(alias="from"),
    to: date = Query(),
    page: int = Query(1, ge=1),
    page_size: int = Query(31, ge=1, le=100),
    db: Session = Depends(get_db),
    cal: TradingCalendar = Depends(calendar_dep),
):
    if from_ > to:
        raise ApiError(422, "invalid_range", "'from' must not be after 'to'")
    if (to - from_).days >= MAX_HISTORY_DAYS:
        raise ApiError(422, "range_too_large", f"date range may span at most {MAX_HISTORY_DAYS} days")
    total = (to - from_).days + 1
    page_end = to - timedelta(days=(page - 1) * page_size)
    page_start = max(from_, page_end - timedelta(days=page_size - 1))
    days = q.history_days(db, page_start, page_end, cal) if page_end >= from_ else []
    return HistoryOut(from_date=from_, to_date=to, page=page, page_size=page_size, total_days=total, days=days)


@router.get("/{trading_date}/compare", response_model=CompareOut)
def compare(
    trading_date: date,
    category: CapCategory,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
):
    snaps = {}
    for s in ScanSession:
        run = q.display_run(db, trading_date, s)
        snaps[s.value] = q.category_snapshot(db, run, category, settings) if run else None
    m = {p.symbol for p in snaps["morning"].stocks} if snaps["morning"] else set()
    a = {p.symbol for p in snaps["afternoon"].stocks} if snaps["afternoon"] else set()
    return CompareOut(
        trading_date=trading_date, category=category, morning=snaps["morning"], afternoon=snaps["afternoon"],
        in_both=sorted(m & a), morning_only=sorted(m - a), afternoon_only=sorted(a - m),
    )


@router.get("/{trading_date}/{session}", response_model=SessionSnapshotOut)
def session_snapshot(
    trading_date: date,
    session: ScanSession,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    cal: TradingCalendar = Depends(calendar_dep),
    now: datetime = Depends(now_dep),
):
    run = q.display_run(db, trading_date, session)
    if run is None:
        raise _not_found(trading_date, session, cal, settings, now)
    return q.session_snapshot(db, run, settings)


@router.get("/{trading_date}/{session}/{category}", response_model=CategorySnapshotOut)
def category_snapshot(
    trading_date: date,
    session: ScanSession,
    category: CapCategory,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dep),
    cal: TradingCalendar = Depends(calendar_dep),
    now: datetime = Depends(now_dep),
):
    run = q.display_run(db, trading_date, session)
    if run is None:
        raise _not_found(trading_date, session, cal, settings, now)
    return q.category_snapshot(db, run, category, settings)
