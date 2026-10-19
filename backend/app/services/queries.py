"""Read side: turn stored runs into API responses. Never triggers a scan."""

from datetime import date, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.trading_calendar import TradingCalendar, UnknownCalendarYear
from app.models import DailyPerformance, ScanRun, ScanSession, StockPick
from app.models.enums import PUBLISHED_STATUSES, CapCategory, ScanStatus
from app.schemas.scans import (
    CategorySnapshotOut,
    LastRunOut,
    PerformanceOut,
    PickOut,
    RunMeta,
    SessionSnapshotOut,
    SessionSummary,
)
from app.services.ranking import VOLUME_BASIS_LABELS

LATE_TOLERANCE = timedelta(minutes=15)

METHODOLOGY = {
    "morning": (
        "Opening scan: ranks the opening move vs previous close together with how unusual the previous "
        "session's volume was (vs its 20-day average). Intraday volume at the open is minimal and is shown "
        "for reference only - it is not used for ranking."
    ),
    "afternoon": (
        "Afternoon scan: ranks today's price move vs previous close together with volume accumulated so far "
        "relative to typical volume by the same time of day."
    ),
}


def public_error(run: ScanRun) -> str | None:
    """Error text safe for public display (provider internals are not exposed)."""
    if run.status != ScanStatus.FAILED.value:
        return None
    msg = run.error_message or ""
    if msg.startswith("DataQualityError"):
        return "Scan failed data-quality checks: " + msg.split(":", 1)[-1].strip()
    if msg.startswith(("ProviderError", "TransientProviderError")):
        return "The market-data provider was unavailable or returned an error."
    return "The scan failed due to an internal error."


def _ist(dt: datetime | None, settings: Settings) -> datetime | None:
    return dt.astimezone(settings.tz) if dt else None


def pick_out(p: StockPick, settings: Settings, perf: list[DailyPerformance] | None = None) -> PickOut:
    direction = "up" if p.price_change_pct > 0 else "down" if p.price_change_pct < 0 else "flat"
    return PickOut(
        id=p.id, symbol=p.symbol, company_name=p.company_name, cap_category=p.cap_category, rank=p.rank,
        price_at_scan=p.price_at_scan, previous_close=p.previous_close, price_change_pct=p.price_change_pct,
        direction=direction, movement_strength=p.movement_strength, intraday_volume=p.intraday_volume,
        relative_volume=p.relative_volume, volume_basis=p.volume_basis,
        volume_basis_label=VOLUME_BASIS_LABELS.get(p.volume_basis, p.volume_basis),
        volume_score=p.volume_score, movement_score=p.movement_score, final_score=p.final_score,
        data_timestamp=_ist(p.data_timestamp, settings), selection_reason=p.selection_reason,
        performance=[
            PerformanceOut(measurement_type=x.measurement_type, measurement_time=_ist(x.measurement_time, settings),
                           measurement_price=x.measurement_price, return_pct=x.return_pct)
            for x in (perf or [])
        ],
    )


def run_meta(run: ScanRun, settings: Settings) -> dict:
    sched = run.scheduled_at.astimezone(settings.tz)
    stale_reason = None
    as_of_raw = (run.summary or {}).get("as_of")
    if run.status in PUBLISHED_STATUSES:
        as_of = datetime.fromisoformat(as_of_raw) if as_of_raw else None
        if run.data_as_of is None:
            stale_reason = "No data timestamp recorded"
        elif as_of and as_of - sched > LATE_TOLERANCE:
            mins = int((as_of - sched).total_seconds() // 60)
            stale_reason = f"Data captured {mins} min after the scheduled scan time"
        elif as_of and (as_of - run.data_as_of).total_seconds() > settings.max_data_staleness_seconds:
            stale_reason = "Some quotes were older than the freshness limit"

    message = {
        ScanStatus.PENDING.value: "Scan is scheduled but has not started.",
        ScanStatus.RUNNING.value: "Scan is in progress.",
        ScanStatus.PARTIAL.value: "Published with fewer than five eligible stocks in at least one category.",
    }.get(run.status) or public_error(run)

    cfg = run.config or {}
    summary = run.summary or {}
    return dict(
        run_id=run.id, trading_date=run.trading_date, session=run.session, scan_type=run.scan_type, status=run.status,
        scheduled_at=sched, scan_time=sched.isoformat()[11:], started_at=_ist(run.started_at, settings),
        completed_at=_ist(run.completed_at, settings), data_as_of=_ist(run.data_as_of, settings),
        is_stale=stale_reason is not None, stale_reason=stale_reason, is_mock_data=run.is_mock_data,
        provider=run.provider, algorithm_version=run.algorithm_version,
        classification_version=run.classification_version,
        weights={"volume": cfg.get("volume_weight", 0.5), "movement": cfg.get("movement_weight", 0.5)},
        methodology_note=METHODOLOGY[run.session], message=message,
        eligible_counts=summary.get("eligible_counts", {}), exclusions=summary.get("exclusions", {}),
    )


def _perf_by_pick(db: Session, pick_ids: list[int]) -> dict[int, list[DailyPerformance]]:
    out: dict[int, list[DailyPerformance]] = {}
    if not pick_ids:
        return out
    for row in db.scalars(
        select(DailyPerformance).where(DailyPerformance.stock_pick_id.in_(pick_ids)).order_by(DailyPerformance.measurement_time)
    ):
        out.setdefault(row.stock_pick_id, []).append(row)
    return out


def display_run(db: Session, d: date, session: ScanSession) -> ScanRun | None:
    """The run to show for a date/session: the published one (scheduled preferred over manual);
    otherwise the most recently updated unpublished run so its status can be explained."""
    runs = db.scalars(
        select(ScanRun)
        .where(ScanRun.trading_date == d, ScanRun.session == session.value)
        .options(selectinload(ScanRun.picks))
        .order_by(
            case((ScanRun.status.in_(PUBLISHED_STATUSES), 0), else_=1),
            case((ScanRun.scan_type == "scheduled", 0), else_=1),
            ScanRun.updated_at.desc(),
        )
    ).all()
    return runs[0] if runs else None


def session_snapshot(db: Session, run: ScanRun, settings: Settings) -> SessionSnapshotOut:
    published = run.status in PUBLISHED_STATUSES
    perf = _perf_by_pick(db, [p.id for p in run.picks]) if published else {}
    cats: dict[CapCategory, list[PickOut]] = {c: [] for c in CapCategory}
    if published:
        for p in sorted(run.picks, key=lambda p: (p.cap_category, p.rank)):
            cats[CapCategory(p.cap_category)].append(pick_out(p, settings, perf.get(p.id)))
    return SessionSnapshotOut(**run_meta(run, settings), categories=cats)


def category_snapshot(db: Session, run: ScanRun, category: CapCategory, settings: Settings) -> CategorySnapshotOut:
    snap = session_snapshot(db, run, settings)
    data = snap.model_dump(exclude={"categories"})
    return CategorySnapshotOut(**data, category=category, stocks=snap.categories[category])


def missing_reason(d: date, session: ScanSession, calendar: TradingCalendar, settings: Settings, now: datetime) -> tuple[str, str]:
    """Explain why no run exists, distinguishing 'nothing scheduled' from 'not yet' from 'missing'."""
    reason = calendar.non_trading_reason(d)
    if reason == "calendar_unknown":
        return "calendar_unknown", f"The NSE holiday calendar for {d.year} is not loaded."
    if reason == "weekend":
        return "non_trading_day", f"{d.isoformat()} is a weekend; NSE is closed."
    if reason:
        return "non_trading_day", f"{d.isoformat()} is an NSE holiday ({reason.split(':', 1)[1]})."
    t = settings.morning_scan_time if session == ScanSession.MORNING else settings.afternoon_scan_time
    sched = datetime.combine(d, t, settings.tz)
    if now < sched:
        return "scan_not_yet_run", f"The {session.value} scan for {d.isoformat()} is scheduled for {sched.strftime('%H:%M')} IST."
    return "no_scan_recorded", f"No {session.value} scan was recorded for {d.isoformat()}."


def session_summary(run: ScanRun | None) -> SessionSummary:
    if run is None:
        return SessionSummary(status="none")
    count = len(run.picks) if run.status in PUBLISHED_STATUSES else 0
    return SessionSummary(status=run.status, run_id=run.id, pick_count=count, is_mock_data=run.is_mock_data)


def history_days(db: Session, start: date, end: date, calendar: TradingCalendar) -> list[dict]:
    runs = db.scalars(
        select(ScanRun).where(ScanRun.trading_date.between(start, end)).options(selectinload(ScanRun.picks))
    ).all()
    best: dict[tuple[date, str], ScanRun] = {}
    for r in sorted(runs, key=lambda r: (r.status not in PUBLISHED_STATUSES, r.scan_type != "scheduled", -r.updated_at.timestamp())):
        best.setdefault((r.trading_date, r.session), r)
    days = []
    cur = end
    while cur >= start:
        try:
            trading = calendar.is_trading_day(cur)
        except UnknownCalendarYear:
            trading = None
        days.append(dict(
            date=cur, is_trading_day=trading, non_trading_reason=calendar.non_trading_reason(cur),
            morning=session_summary(best.get((cur, "morning"))),
            afternoon=session_summary(best.get((cur, "afternoon"))),
        ))
        cur -= timedelta(days=1)
    return days


def last_run_out(run: ScanRun | None, settings: Settings) -> LastRunOut | None:
    if run is None:
        return None
    return LastRunOut(
        run_id=run.id, trading_date=run.trading_date, session=run.session, status=run.status,
        completed_at=_ist(run.completed_at, settings), data_as_of=_ist(run.data_as_of, settings),
        message=public_error(run),
    )


def last_successful_run(db: Session) -> ScanRun | None:
    return db.scalar(
        select(ScanRun).where(ScanRun.status.in_(PUBLISHED_STATUSES)).order_by(ScanRun.completed_at.desc()).limit(1)
    )


def latest_run(db: Session) -> ScanRun | None:
    return db.scalar(select(ScanRun).order_by(ScanRun.updated_at.desc()).limit(1))


def latest_published_for_session(db: Session, session: ScanSession) -> ScanRun | None:
    return db.scalar(
        select(ScanRun)
        .where(ScanRun.session == session.value, ScanRun.status.in_(PUBLISHED_STATUSES))
        .options(selectinload(ScanRun.picks))
        .order_by(ScanRun.trading_date.desc(), case((ScanRun.scan_type == "scheduled", 0), else_=1))
        .limit(1)
    )


def picks_for_symbol(db: Session, symbol: str, start: date, end: date) -> list[tuple[StockPick, ScanRun]]:
    return list(
        db.execute(
            select(StockPick, ScanRun)
            .join(ScanRun)
            .where(StockPick.symbol == symbol, ScanRun.trading_date.between(start, end),
                   ScanRun.status.in_(PUBLISHED_STATUSES))
            .order_by(ScanRun.trading_date.desc(), ScanRun.session)
        ).all()
    )


def count_runs(db: Session) -> int:
    return db.scalar(select(func.count(ScanRun.id))) or 0
