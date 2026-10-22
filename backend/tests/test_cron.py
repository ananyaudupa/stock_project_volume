from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.models import ClassificationVersion, ScanRun, StockUniverse
from app.scheduler import cron
from tests.conftest import IST


@pytest.mark.parametrize(
    "hhmm,expected",
    [((9, 0), None), ((9, 20), "morning"), ((9, 49), "morning"), ((10, 50), None), ((15, 0), "afternoon"),
     ((15, 29), "afternoon"), ((15, 45), None), ((16, 0), "performance"), ((21, 0), None)],
)
def test_due_job_windows(hhmm, expected):
    s = Settings(_env_file=None, morning_scan_time="09:20")
    assert cron.due_job(datetime(2026, 10, 16, *hhmm, tzinfo=IST), s) == expected


def test_database_url_gets_psycopg_driver():
    for raw in ("postgres://u:p@h/db?sslmode=require", "postgresql://u:p@h/db?sslmode=require"):
        assert Settings(_env_file=None, database_url=raw).database_url == "postgresql+psycopg://u:p@h/db?sslmode=require"


def test_bundled_amfi_is_imported_once(factory):
    assert cron.ensure_classification(factory, date(2026, 10, 19)) == ["amfi-2026H2"]
    assert cron.ensure_classification(factory, date(2026, 10, 19)) == []
    with factory() as db:
        cv = db.scalar(select(ClassificationVersion))
        assert cv.is_current and not cv.is_mock
        assert db.scalar(select(func.count()).select_from(StockUniverse)) > 2000


def test_bundled_amfi_not_imported_before_effective_date(factory):
    assert cron.ensure_classification(factory, date(2026, 6, 30)) == []


def test_cron_runs_due_scan_and_is_idempotent(seeded, provider, calendar, settings, monkeypatch):
    import app.services.scanner as scanner

    when = datetime(2026, 10, 16, 15, 2, tzinfo=IST)
    monkeypatch.setattr(scanner, "utcnow", lambda: when)
    monkeypatch.setattr(cron, "BUNDLED_AMFI", [])  # the mock provider uses the mock classification
    kw = dict(now=when, factory=seeded, settings=settings, provider=provider, calendar=calendar)
    assert cron.main(**kw) == 0
    assert cron.main(**kw) == 0  # backup trigger: skipped, no duplicate
    with seeded() as db:
        assert db.scalar(select(func.count()).select_from(ScanRun)) == 1


def test_cron_exit_code_signals_failure(seeded, calendar, settings, monkeypatch):
    import app.services.scanner as scanner
    from app.services.market_data.mock import MockProvider

    when = datetime(2026, 10, 16, 15, 2, tzinfo=IST)
    monkeypatch.setattr(scanner, "utcnow", lambda: when)
    monkeypatch.setattr(cron, "BUNDLED_AMFI", [])
    assert cron.main(now=when, factory=seeded, settings=settings, provider=MockProvider(fail_times=99), calendar=calendar) == 1


def test_cron_does_nothing_on_holiday(seeded, provider, calendar, settings, monkeypatch):
    monkeypatch.setattr(cron, "BUNDLED_AMFI", [])
    when = datetime(2026, 10, 20, 9, 25, tzinfo=IST)  # Dussehra
    assert cron.main(now=when, factory=seeded, settings=Settings(_env_file=None, morning_scan_time="09:20",
                     database_url=settings.database_url), provider=provider, calendar=calendar) == 0


# --- HTTP trigger (cron-job.org) and missed-scan detection ---------------------------------

def test_cron_endpoint_requires_token(client, settings):
    assert client.post("/api/cron/run").json()["error"]["code"] == "cron_disabled"
    settings.cron_token = "tok-123"
    assert client.post("/api/cron/run").status_code == 401
    assert client.post("/api/cron/run", headers={"X-Cron-Token": "wrong"}).status_code == 401


def test_cron_endpoint_nothing_due(client, settings, clock):
    settings.cron_token = "tok-123"
    clock.value = datetime(2026, 10, 16, 12, 0, tzinfo=IST)
    r = client.post("/api/cron/run", headers={"X-Cron-Token": "tok-123"})
    assert r.status_code == 202 and r.json()["due"] is None and r.json()["started"] is False


def test_cron_endpoint_runs_due_scan_in_background(client, settings, clock, seeded, monkeypatch):
    import app.services.scanner as scanner

    settings.cron_token = "tok-123"
    when = datetime(2026, 10, 16, 15, 1, tzinfo=IST)
    clock.value = when
    monkeypatch.setattr(scanner, "utcnow", lambda: when)
    monkeypatch.setattr(cron, "BUNDLED_AMFI", [])
    r = client.post("/api/cron/run", headers={"X-Cron-Token": "tok-123"})
    assert r.status_code == 202 and r.json() == {"due": "afternoon", "started": True, "ist": when.isoformat()}
    # TestClient runs background tasks before returning; a second call is a harmless duplicate.
    client.post("/api/cron/run", headers={"X-Cron-Token": "tok-123"})
    with seeded() as db:
        runs = db.scalars(select(ScanRun)).all()
    assert [(r.session, r.status) for r in runs] == [("afternoon", "completed")]


def test_late_trigger_reports_missed_scan(seeded, provider, calendar, settings, monkeypatch, scan):
    monkeypatch.setattr(cron, "BUNDLED_AMFI", [])
    s = Settings(_env_file=None, database_url=settings.database_url, morning_scan_time="09:20")
    late = datetime(2026, 10, 16, 14, 30, tzinfo=IST)  # GitHub ran the 09:20 trigger 5h late
    assert cron.missed_sessions(late, seeded, s, calendar) == ["morning"]
    assert cron.main(now=late, factory=seeded, settings=s, provider=provider, calendar=calendar) == 1
    from app.models import ScanSession
    scan(session=ScanSession.MORNING)
    assert cron.main(now=late, factory=seeded, settings=s, provider=provider, calendar=calendar) == 0
    evening = datetime(2026, 10, 16, 21, 0, tzinfo=IST)
    assert cron.missed_sessions(evening, seeded, s, calendar) == ["afternoon"]
    assert cron.missed_sessions(datetime(2026, 10, 20, 21, 0, tzinfo=IST), seeded, s, calendar) == []  # holiday
