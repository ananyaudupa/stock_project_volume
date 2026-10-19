from datetime import date, timedelta

import pytest
from sqlalchemy import func, select, update

from app.db.base import utcnow
from app.models import MarketDataSnapshot, ScanAttempt, ScanRun, ScanSession, ScanType, StockPick
from app.services.classification import ClassifiedStock, save_classification
from app.services.market_data.mock import MockProvider
from app.services.scanner import NotATradingDay, ScanAlreadyPublished, ScanInProgress, ScanRefused, run_scan
from tests.conftest import DUSSEHRA, FRIDAY, SATURDAY


def picks_of(factory, run_id):
    with factory() as db:
        return db.scalars(select(StockPick).where(StockPick.scan_run_id == run_id).order_by(StockPick.cap_category, StockPick.rank)).all()


def test_completed_scan_stores_up_to_five_per_category(scan, seeded):
    run = scan()
    assert run.status == "completed"
    assert run.is_mock_data is True
    assert run.classification_version.startswith("mock-")
    picks = picks_of(seeded, run.id)
    by_cat = {}
    for p in picks:
        by_cat.setdefault(p.cap_category, []).append(p.rank)
    assert by_cat == {"large-cap": [1, 2, 3, 4, 5], "mid-cap": [1, 2, 3, 4, 5], "small-cap": [1, 2, 3, 4, 5]}
    p = picks[0]
    assert p.data_timestamp is not None and p.selection_reason and p.metrics["avg_daily_volume"]
    assert run.summary["exclusions"]  # mock injects stale/missing/suspended rows
    with seeded() as db:
        assert db.scalar(select(func.count()).select_from(MarketDataSnapshot).where(MarketDataSnapshot.scan_run_id == run.id)) == 450


def test_morning_scan_ranks_on_previous_session_volume(scan, seeded):
    run = scan(session=ScanSession.MORNING)
    assert {p.volume_basis for p in picks_of(seeded, run.id)} == {"previous_session"}
    # 0 at the open, or None where the provider had no session volume (not used for ranking either way)
    assert all(p.intraday_volume in (0, None) for p in picks_of(seeded, run.id))


def test_morning_and_afternoon_are_separate_snapshots(scan, seeded):
    m = scan(session=ScanSession.MORNING)
    a = scan(session=ScanSession.AFTERNOON)
    assert m.id != a.id
    assert {p.volume_basis for p in picks_of(seeded, a.id)} == {"same_time_baseline"}
    assert len(picks_of(seeded, m.id)) == 15 and len(picks_of(seeded, a.id)) == 15


def test_scan_is_reproducible(seeded, settings, calendar, factory):
    """Same inputs + config => identical ranking (separate DBs, fresh provider instances)."""
    from tests.conftest import scheduled_time

    def symbols(scan_type):
        run = run_scan(seeded, FRIDAY, ScanSession.AFTERNOON, provider=MockProvider(), scan_type=scan_type,
                       settings=settings, calendar=calendar, as_of=scheduled_time(FRIDAY, ScanSession.AFTERNOON, settings))
        return [(p.cap_category, p.rank, p.symbol, p.final_score) for p in picks_of(seeded, run.id)]

    assert symbols(ScanType.SCHEDULED) == symbols(ScanType.MANUAL)


def test_published_scan_is_never_rerun(scan, seeded):
    first = scan()
    before = [(p.symbol, p.final_score) for p in picks_of(seeded, first.id)]
    with pytest.raises(ScanAlreadyPublished):
        scan()
    assert [(p.symbol, p.final_score) for p in picks_of(seeded, first.id)] == before


def test_duplicate_concurrent_run_is_refused(scan, seeded):
    with seeded() as db:
        db.add(ScanRun(trading_date=FRIDAY, session="morning", scan_type="scheduled", scheduled_at=utcnow(),
                       started_at=utcnow(), status="running", provider="mock", algorithm_version="x"))
        db.commit()
    with pytest.raises(ScanInProgress):
        scan()


def test_abandoned_running_scan_can_be_reclaimed(scan, seeded, settings):
    old = utcnow() - timedelta(seconds=settings.stale_run_timeout_seconds + 60)
    with seeded() as db:
        db.add(ScanRun(trading_date=FRIDAY, session="morning", scan_type="scheduled", scheduled_at=old,
                       started_at=old, status="running", provider="mock", algorithm_version="x", attempt_count=1))
        db.commit()
    run = scan()
    assert run.status == "completed" and run.attempt_count == 2


def test_failed_scan_keeps_previous_snapshot_and_records_failure(scan, seeded):
    good = scan(d=date(2026, 10, 15), session=ScanSession.AFTERNOON)
    good_picks = [(p.id, p.symbol) for p in picks_of(seeded, good.id)]

    always_down = MockProvider(fail_times=100)
    failed = scan(prov=always_down)
    assert failed.status == "failed"
    assert "ProviderError" in failed.error_message
    assert always_down.calls == 4  # 1 try + 3 bounded retries
    assert picks_of(seeded, failed.id) == []
    assert [(p.id, p.symbol) for p in picks_of(seeded, good.id)] == good_picks
    with seeded() as db:
        attempts = db.scalars(select(ScanAttempt).where(ScanAttempt.scan_run_id == failed.id)).all()
        assert [(a.attempt_no, a.status) for a in attempts] == [(1, "failed")]


def test_retry_after_failure_reuses_the_same_run(scan, seeded):
    failed = scan(prov=MockProvider(fail_times=100))
    retried = scan()
    assert retried.id == failed.id
    assert retried.status == "completed" and retried.attempt_count == 2
    with seeded() as db:
        assert db.scalar(select(func.count()).select_from(ScanRun)) == 1
        statuses = db.scalars(select(ScanAttempt.status).where(ScanAttempt.scan_run_id == failed.id).order_by(ScanAttempt.attempt_no)).all()
    assert statuses == ["failed", "completed"]


def test_transient_errors_are_retried(scan):
    flaky = MockProvider(fail_times=2)
    run = scan(prov=flaky)
    assert run.status == "completed"
    assert flaky.calls == 3


@pytest.mark.parametrize("day", [SATURDAY, DUSSEHRA])
def test_non_trading_days_are_refused(scan, day):
    with pytest.raises(NotATradingDay):
        scan(d=day)


def test_insufficient_coverage_fails_instead_of_publishing(seeded, settings, calendar):
    class HalfProvider(MockProvider):
        def get_quotes(self, symbols, as_of):
            return super().get_quotes(symbols[: len(symbols) // 2], as_of)

    from tests.conftest import scheduled_time

    run = run_scan(seeded, FRIDAY, ScanSession.MORNING, provider=HalfProvider(), settings=settings, calendar=calendar,
                   as_of=scheduled_time(FRIDAY, ScanSession.MORNING, settings))
    assert run.status == "failed" and "DataQualityError" in run.error_message
    assert picks_of(seeded, run.id) == []


def test_partial_when_a_category_has_fewer_than_five(factory, settings, calendar, provider):
    stocks = [ClassifiedStock(f"DEMOL{i:03d}", "x", i) for i in range(1, 11)] + [
        ClassifiedStock("DEMOM001", "y", 101), ClassifiedStock("DEMOS001", "z", 300)]
    with factory() as db:
        save_classification(db, stocks, "mock-tiny", "test", FRIDAY, is_mock=True)
    from tests.conftest import scheduled_time

    run = run_scan(factory, FRIDAY, ScanSession.AFTERNOON, provider=provider, settings=settings, calendar=calendar,
                   as_of=scheduled_time(FRIDAY, ScanSession.AFTERNOON, settings))
    assert run.status == "partial"
    assert sorted(run.summary["categories_short_of_target"]) == ["mid-cap", "small-cap"]


def test_picks_are_immutable(scan, seeded):
    run = scan()
    with seeded() as db:
        pick = db.scalars(select(StockPick).where(StockPick.scan_run_id == run.id)).first()
        pick.price_at_scan = 1.0
        with pytest.raises(RuntimeError, match="immutable"):
            db.commit()


def test_live_only_provider_cannot_backfill(seeded, settings, calendar):
    class LiveOnly(MockProvider):
        capabilities = MockProvider.capabilities.__class__(**{**MockProvider.capabilities.__dict__, "point_in_time_quotes": False})

    from tests.conftest import scheduled_time

    with pytest.raises(ScanRefused):
        run_scan(seeded, FRIDAY, ScanSession.MORNING, provider=LiveOnly(), settings=settings, calendar=calendar,
                 as_of=scheduled_time(FRIDAY, ScanSession.MORNING, settings))


def test_mock_classification_cannot_be_used_with_real_provider(seeded, settings, calendar):
    class Real(MockProvider):
        name = "realish"
        capabilities = MockProvider.capabilities.__class__(**{**MockProvider.capabilities.__dict__, "is_mock": False})

    from tests.conftest import scheduled_time

    run = run_scan(seeded, FRIDAY, ScanSession.MORNING, provider=Real(), settings=settings, calendar=calendar,
                   as_of=scheduled_time(FRIDAY, ScanSession.MORNING, settings))
    assert run.status == "failed" and "mock vs real" in run.error_message


def test_status_update_guard(scan, seeded):
    """A late failure write can never overwrite a published run."""
    run = scan()
    with seeded() as db:
        res = db.execute(update(ScanRun).where(ScanRun.id == run.id, ScanRun.status == "running").values(status="failed"))
        assert res.rowcount == 0
