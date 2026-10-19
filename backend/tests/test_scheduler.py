from datetime import datetime

import pytest
from sqlalchemy import func, select

from app.models import DailyPerformance, ScanRun, ScanSession, StockPick
from app.scheduler import jobs
from tests.conftest import IST


@pytest.fixture
def job_kwargs(seeded, provider, settings, calendar):
    return dict(factory=seeded, provider=provider, settings=settings, calendar=calendar)


def at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


def count_runs(factory):
    with factory() as db:
        return db.scalar(select(func.count()).select_from(ScanRun))


@pytest.mark.parametrize("when", [at(2026, 10, 17, 9, 15), at(2026, 10, 20, 9, 15)])  # Saturday, Dussehra
def test_job_skips_weekends_and_holidays(job_kwargs, seeded, when, monkeypatch):
    assert jobs.scheduled_scan_job(ScanSession.MORNING, now=when, **job_kwargs) is None
    assert count_runs(seeded) == 0


def test_job_alerts_and_skips_when_calendar_unknown(job_kwargs, seeded, monkeypatch):
    alerts = []
    monkeypatch.setattr(jobs, "send_alert", lambda kind, msg, **_: alerts.append(kind))
    assert jobs.scheduled_scan_job(ScanSession.MORNING, now=at(2031, 3, 3, 9, 15), **job_kwargs) is None
    assert alerts == ["calendar_unknown"] and count_runs(seeded) == 0


def test_job_is_idempotent(job_kwargs, seeded, monkeypatch):
    when = at(2026, 10, 16, 15, 0)
    # The scheduler scans "now"; pin the scanner's as_of to the fake clock.
    import app.services.scanner as scanner

    monkeypatch.setattr(scanner, "utcnow", lambda: when)
    first = jobs.scheduled_scan_job(ScanSession.AFTERNOON, now=when, **job_kwargs)
    assert first.status == "completed"
    assert jobs.scheduled_scan_job(ScanSession.AFTERNOON, now=when, **job_kwargs) is None
    assert count_runs(seeded) == 1
    with seeded() as db:
        assert db.scalar(select(func.count()).select_from(StockPick)) == 15


def test_watchdog_alerts_on_missing_scan(job_kwargs, monkeypatch):
    alerts = []
    monkeypatch.setattr(jobs, "send_alert", lambda kind, msg, **_: alerts.append((kind, msg)))
    kw = {k: v for k, v in job_kwargs.items() if k != "provider"}
    assert jobs.missing_scan_watchdog(now=at(2026, 10, 16, 9, 30), **kw) == []  # within grace
    assert jobs.missing_scan_watchdog(now=at(2026, 10, 16, 9, 40), **kw) == ["morning"]
    assert alerts[0][0] == "scan_missing"
    assert jobs.missing_scan_watchdog(now=at(2026, 10, 17, 12, 0), **kw) == []  # weekend


def test_performance_job_is_idempotent(job_kwargs, scan, seeded):
    scan(session=ScanSession.AFTERNOON)
    when = at(2026, 10, 16, 16, 0)
    assert jobs.performance_job(now=when, **job_kwargs) == 15
    assert jobs.performance_job(now=when, **job_kwargs) == 0
    with seeded() as db:
        assert db.scalar(select(func.count()).select_from(DailyPerformance)) == 15
