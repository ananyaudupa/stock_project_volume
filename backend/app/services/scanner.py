"""Scan orchestration: claim a run, fetch data, rank, and publish atomically.

Guarantees
----------
* One run row per (trading_date, session, scan_type), enforced by a unique constraint.
* A run is "claimed" with a conditional UPDATE (pending/failed/abandoned -> running), which acts
  as a database lock: two workers can never execute the same scan concurrently.
* A published (completed/partial) run is never re-run or modified.
* Picks, snapshots and the final status are written in ONE transaction. If anything fails the
  transaction is rolled back, the run is marked failed, and every earlier snapshot is untouched.
"""

import logging
import time as time_mod
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.trading_calendar import TradingCalendar, get_calendar
from app.db.base import utcnow
from app.models import MarketDataSnapshot, ScanAttempt, ScanRun, ScanSession, ScanStatus, ScanType, StockPick
from app.models.enums import PUBLISHED_STATUSES
from app.services.alerts import send_alert
from app.services.classification import current_universe
from app.services.market_data.base import MarketDataProvider, ProviderError, Quote, TransientProviderError
from app.services.ranking import ALGORITHM_VERSION, Candidate, RankingConfig, rank_universe

log = logging.getLogger(__name__)


class ScanRefused(Exception):
    code = "scan_refused"


class NotATradingDay(ScanRefused):
    code = "not_a_trading_day"


class ScanAlreadyPublished(ScanRefused):
    code = "scan_already_published"


class ScanInProgress(ScanRefused):
    code = "scan_in_progress"


class DataQualityError(Exception):
    """Data failed validation; the run fails rather than publishing a misleading snapshot."""


def scheduled_time(trading_date: date, session: ScanSession, settings: Settings) -> datetime:
    t = settings.morning_scan_time if session == ScanSession.MORNING else settings.afternoon_scan_time
    return datetime.combine(trading_date, t, settings.tz)


def ranking_config(settings: Settings) -> RankingConfig:
    return RankingConfig(
        volume_weight=settings.volume_score_weight,
        movement_weight=settings.movement_score_weight,
        picks_per_category=settings.picks_per_category,
        max_staleness_seconds=settings.max_data_staleness_seconds,
        min_avg_traded_value_inr=settings.min_avg_traded_value_inr,
    )


def _claim_run(
    db: Session, trading_date: date, session: ScanSession, scan_type: ScanType, provider: MarketDataProvider,
    settings: Settings, trigger: str,
) -> tuple[ScanRun, ScanAttempt]:
    key = dict(trading_date=trading_date, session=session.value, scan_type=scan_type.value)
    run = db.scalar(select(ScanRun).filter_by(**key))
    if run is None:
        run = ScanRun(
            **key,
            scheduled_at=scheduled_time(trading_date, session, settings),
            status=ScanStatus.PENDING.value,
            provider=provider.name,
            is_mock_data=provider.capabilities.is_mock,
            algorithm_version=ALGORITHM_VERSION,
            config=ranking_config(settings).as_dict(),
        )
        db.add(run)
        try:
            db.commit()
        except IntegrityError:  # another worker created it first
            db.rollback()
            run = db.scalar(select(ScanRun).filter_by(**key))

    if run.status in PUBLISHED_STATUSES:
        raise ScanAlreadyPublished(f"{trading_date} {session} ({scan_type}) is already published (run {run.id})")

    now = utcnow()
    abandoned_before = now - timedelta(seconds=settings.stale_run_timeout_seconds)
    claimed = db.execute(
        update(ScanRun)
        .where(
            ScanRun.id == run.id,
            or_(
                ScanRun.status.in_([ScanStatus.PENDING.value, ScanStatus.FAILED.value]),
                (ScanRun.status == ScanStatus.RUNNING.value) & (ScanRun.started_at < abandoned_before),
            ),
        )
        .values(
            status=ScanStatus.RUNNING.value,
            started_at=now,
            attempt_count=ScanRun.attempt_count + 1,
            error_message=None,
            provider=provider.name,
            is_mock_data=provider.capabilities.is_mock,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        db.rollback()
        raise ScanInProgress(f"{trading_date} {session} ({scan_type}) is already running")
    db.commit()
    db.refresh(run)
    attempt = ScanAttempt(
        scan_run_id=run.id, attempt_no=run.attempt_count, trigger=trigger, started_at=now,
        status=ScanStatus.RUNNING.value,
    )
    db.add(attempt)
    db.commit()
    return run, attempt


def _fetch_with_retries(
    provider: MarketDataProvider, symbols: list[str], as_of: datetime, settings: Settings,
    sleep: Callable[[float], None],
) -> tuple[dict[str, Quote], int, int]:
    """Bounded exponential-backoff retries for transient errors only. Returns (quotes, latency_ms, calls)."""
    attempts = settings.provider_max_retries + 1
    for i in range(attempts):
        started = time_mod.monotonic()
        try:
            quotes = provider.get_quotes(symbols, as_of)
            return quotes, int((time_mod.monotonic() - started) * 1000), i + 1
        except TransientProviderError as exc:
            if i == attempts - 1:
                raise ProviderError(f"provider still failing after {attempts} attempts: {exc}") from exc
            delay = settings.provider_retry_base_delay_seconds * (2**i)
            log.warning("transient provider error, retrying", extra={"attempt": i + 1, "delay_s": delay, "error": str(exc)})
            sleep(delay)
    raise AssertionError("unreachable")


def run_scan(
    session_factory: sessionmaker[Session],
    trading_date: date,
    session: ScanSession,
    *,
    provider: MarketDataProvider,
    scan_type: ScanType = ScanType.SCHEDULED,
    trigger: str = "scheduler",
    as_of: datetime | None = None,
    settings: Settings | None = None,
    calendar: TradingCalendar | None = None,
    sleep: Callable[[float], None] = time_mod.sleep,
) -> ScanRun:
    """Execute one scan. Raises ScanRefused subclasses if the scan must not run; returns the run otherwise
    (status completed / partial / failed)."""
    settings = settings or get_settings()
    calendar = calendar or get_calendar()

    reason = calendar.non_trading_reason(trading_date)
    if reason:
        raise NotATradingDay(f"{trading_date} is not a trading day ({reason})")
    if calendar.is_special_session(trading_date):
        raise NotATradingDay(f"{trading_date} is a special session; regular scans are not run")

    now = utcnow()
    as_of = as_of or now
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if not provider.capabilities.point_in_time_quotes and abs((now - as_of).total_seconds()) > 300:
        raise ScanRefused(f"provider '{provider.name}' only serves live quotes; cannot scan as of {as_of.isoformat()}")
    if as_of.astimezone(settings.tz).date() != trading_date:
        raise ScanRefused("as_of must fall on the requested trading date")

    with session_factory() as db:
        run, attempt = _claim_run(db, trading_date, session, scan_type, provider, settings, trigger)
        log_ctx = {"run_id": run.id, "trading_date": str(trading_date), "session": session.value, "attempt": attempt.attempt_no}
        log.info("scan started", extra=log_ctx)
        t0 = time_mod.monotonic()
        latency_ms = calls = None
        try:
            cv, universe = current_universe(db)
            if settings.max_universe_rank:
                universe = [u for u in universe if u.cap_rank is None or u.cap_rank <= settings.max_universe_rank]
            if cv is None or not universe:
                raise DataQualityError("no current market-cap classification is loaded")
            if cv.is_mock != provider.capabilities.is_mock:
                raise DataQualityError("classification and provider disagree on mock vs real data")

            symbols = [u.symbol for u in universe]
            quotes, latency_ms, calls = _fetch_with_retries(provider, symbols, as_of, settings, sleep)

            fresh = sum(
                1 for q in quotes.values()
                if q.data_timestamp and (as_of - q.data_timestamp).total_seconds() <= settings.max_data_staleness_seconds
            )
            coverage = fresh / len(symbols)
            if coverage < settings.min_universe_coverage:
                raise DataQualityError(
                    f"fresh data for only {coverage:.0%} of the universe (minimum {settings.min_universe_coverage:.0%})"
                )

            cfg = ranking_config(settings)
            candidates = [Candidate(u.symbol, u.company_name, u.cap_category, quotes.get(u.symbol)) for u in universe]
            result = rank_universe(candidates, session, as_of, cfg)

            # ---- publish: everything below is one transaction ----
            captured = utcnow()
            for u in universe:
                q = quotes.get(u.symbol)
                db.add(
                    MarketDataSnapshot(
                        scan_run_id=run.id, symbol=u.symbol, captured_at=captured,
                        data_timestamp=q.data_timestamp if q else None,
                        price=q.last_price if q else None, open_price=q.open_price if q else None,
                        previous_close=q.previous_close if q else None, volume=q.session_volume if q else None,
                        previous_session_volume=q.previous_session_volume if q else None,
                        avg_daily_volume=q.avg_daily_volume if q else None,
                        same_time_avg_volume=q.same_time_avg_volume if q else None,
                        provider=provider.name,
                        eligible=u.symbol in result.metrics_by_symbol,
                        exclusion_reason=result.excluded_symbols.get(u.symbol),
                        quality_flags=dict(q.flags) if q else {"missing": True},
                    )
                )
            pick_timestamps = []
            for cat, picks in result.picks.items():
                for p in picks:
                    m = p.metrics
                    pick_timestamps.append(m.data_timestamp)
                    db.add(
                        StockPick(
                            scan_run_id=run.id, symbol=m.symbol, company_name=m.company_name, cap_category=cat,
                            rank=p.rank, price_at_scan=m.price, previous_close=m.previous_close,
                            reference_price=m.reference_price, price_change_pct=m.price_change_pct,
                            movement_strength=m.movement_strength, intraday_volume=m.intraday_volume,
                            relative_volume=m.relative_volume, volume_basis=m.volume_basis,
                            volume_score=p.volume_score, movement_score=p.movement_score, final_score=p.final_score,
                            data_timestamp=m.data_timestamp, selection_reason=p.selection_reason,
                            metrics=m.inputs | {"eligible_in_category": p.eligible_in_category},
                        )
                    )

            short = [c for c, ps in result.picks.items() if len(ps) < cfg.picks_per_category]
            status = ScanStatus.PARTIAL if short else ScanStatus.COMPLETED
            done = utcnow()
            run.status = status.value
            run.completed_at = done
            run.classification_version = cv.version
            run.data_as_of = min(pick_timestamps) if pick_timestamps else None
            run.duration_ms = int((time_mod.monotonic() - t0) * 1000)
            run.algorithm_version = ALGORITHM_VERSION
            run.config = cfg.as_dict()
            run.summary = {
                "as_of": as_of.isoformat(),
                "universe_size": len(symbols),
                "quotes_received": len(quotes),
                "fresh_coverage": round(coverage, 4),
                "eligible_counts": result.eligible_counts,
                "pick_counts": {c: len(ps) for c, ps in result.picks.items()},
                "categories_short_of_target": short,
                "exclusions": dict(sorted(result.exclusions.items())),
                "provider_latency_ms": latency_ms,
                "data_timestamp_range": [
                    min(pick_timestamps).isoformat() if pick_timestamps else None,
                    max(pick_timestamps).isoformat() if pick_timestamps else None,
                ],
            }
            attempt.status = status.value
            attempt.finished_at = done
            attempt.provider_latency_ms = latency_ms
            attempt.provider_calls = calls
            db.commit()
            log.info("scan published", extra=log_ctx | {"status": status.value, "duration_ms": run.duration_ms, "summary": run.summary})
            if short:
                send_alert("scan_partial", f"Scan {trading_date} {session} published with short categories: {short}", **log_ctx)
            return run

        except Exception as exc:
            db.rollback()
            msg = f"{type(exc).__name__}: {exc}"
            failed_at = utcnow()
            db.execute(
                update(ScanRun)
                .where(ScanRun.id == run.id, ScanRun.status == ScanStatus.RUNNING.value)
                .values(status=ScanStatus.FAILED.value, error_message=msg[:2000],
                        duration_ms=int((time_mod.monotonic() - t0) * 1000), updated_at=failed_at)
                .execution_options(synchronize_session=False)
            )
            db.execute(
                update(ScanAttempt)
                .where(ScanAttempt.id == attempt.id)
                .values(status=ScanStatus.FAILED.value, finished_at=failed_at, error_message=msg[:2000],
                        provider_latency_ms=latency_ms, provider_calls=calls)
                .execution_options(synchronize_session=False)
            )
            db.commit()
            db.refresh(run)
            send_alert("scan_failed", f"Scan {trading_date} {session} failed: {msg}", **log_ctx)
            if not isinstance(exc, (ProviderError, DataQualityError)):
                log.exception("unexpected scan error", extra=log_ctx)
            return run


def now_ist(settings: Settings | None = None) -> datetime:
    return datetime.now(timezone.utc).astimezone((settings or get_settings()).tz)
