from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select

from app.models import ScanRun, ScanSession
from app.services.market_data.mock import MockProvider
from tests.conftest import IST


def test_category_snapshot_shape(client, scan):
    scan()
    r = client.get("/api/scans/2026-10-16/morning/mid-cap")
    assert r.status_code == 200
    body = r.json()
    assert body["trading_date"] == "2026-10-16"
    assert body["session"] == "morning" and body["category"] == "mid-cap"
    assert body["scan_time"] == "09:15:00+05:30"
    assert body["status"] == "completed"
    assert body["is_mock_data"] is True
    assert body["data_as_of"].endswith("+05:30")
    assert len(body["stocks"]) == 5
    s = body["stocks"][0]
    for key in ("symbol", "rank", "price_at_scan", "price_change_pct", "intraday_volume", "relative_volume",
                "final_score", "direction", "data_timestamp", "selection_reason", "volume_basis_label"):
        assert key in s
    assert "intraday volume" in body["methodology_note"].lower()


def test_session_snapshot_has_all_categories(client, scan):
    scan(session=ScanSession.AFTERNOON)
    body = client.get("/api/scans/2026-10-16/afternoon").json()
    assert set(body["categories"]) == {"small-cap", "mid-cap", "large-cap"}
    assert all(len(v) == 5 for v in body["categories"].values())


@pytest.mark.parametrize(
    "path,code",
    [
        ("/api/scans/2026-10-17/morning", "non_trading_day"),  # Saturday
        ("/api/scans/2026-10-20/afternoon/mid-cap", "non_trading_day"),  # Dussehra
        ("/api/scans/2026-10-15/morning", "no_scan_recorded"),
        ("/api/scans/2026-10-19/morning", "scan_not_yet_run"),  # future trading day
        ("/api/scans/2031-03-03/morning", "calendar_unknown"),
    ],
)
def test_missing_snapshots_are_distinguishable(client, path, code):
    r = client.get(path)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == code


def test_failed_scan_is_reported_without_provider_internals(client, scan):
    scan(prov=MockProvider(fail_times=100))
    body = client.get("/api/scans/2026-10-16/morning/large-cap").json()
    assert body["status"] == "failed"
    assert body["stocks"] == []
    assert body["message"] == "The market-data provider was unavailable or returned an error."


def test_invalid_parameters_are_rejected(client):
    assert client.get("/api/scans/2026-13-01/morning").status_code == 422
    assert client.get("/api/scans/2026-10-16/evening").status_code == 422
    r = client.get("/api/scans/2026-10-16/morning/micro-cap")
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert client.get("/api/stocks/bad symbol!/history").status_code == 422
    assert client.get("/api/scans/history?from=2026-10-10&to=2026-10-01").status_code == 422


def test_browsing_never_triggers_a_scan(client, scan, provider, seeded):
    scan()
    calls_before = provider.calls
    with seeded() as db:
        runs_before = db.scalar(select(func.count()).select_from(ScanRun))
    for path in [
        "/api/scans/latest", "/api/scans/status", "/api/scans/2026-10-16/morning",
        "/api/scans/2026-10-16/afternoon", "/api/scans/2026-10-15/morning/small-cap",
        "/api/scans/history?from=2026-10-01&to=2026-10-17", "/api/scans/2026-10-16/compare?category=mid-cap",
    ]:
        client.get(path)
    assert provider.calls == calls_before
    with seeded() as db:
        assert db.scalar(select(func.count()).select_from(ScanRun)) == runs_before


def test_history_lists_days_and_sessions(client, scan):
    scan()
    body = client.get("/api/scans/history?from=2026-10-14&to=2026-10-17").json()
    days = {d["date"]: d for d in body["days"]}
    assert days["2026-10-17"]["is_trading_day"] is False
    assert days["2026-10-16"]["morning"]["status"] == "completed"
    assert days["2026-10-16"]["morning"]["pick_count"] == 15
    assert days["2026-10-16"]["afternoon"]["status"] == "none"
    assert body["from"] == "2026-10-14" and body["total_days"] == 4


def test_history_pagination(client):
    body = client.get("/api/scans/history?from=2026-09-01&to=2026-10-17&page=2&page_size=10").json()
    assert body["days"][0]["date"] == "2026-10-07"
    assert len(body["days"]) == 10


def test_compare_morning_and_afternoon(client, scan):
    scan(session=ScanSession.MORNING)
    scan(session=ScanSession.AFTERNOON)
    body = client.get("/api/scans/2026-10-16/compare?category=small-cap").json()
    m = {s["symbol"] for s in body["morning"]["stocks"]}
    a = {s["symbol"] for s in body["afternoon"]["stocks"]}
    assert set(body["in_both"]) == m & a
    assert set(body["morning_only"]) == m - a


def test_status_and_latest(client, scan, clock):
    scan(session=ScanSession.AFTERNOON)
    status = client.get("/api/scans/status").json()
    assert status["today"] == "2026-10-17"
    assert status["is_trading_day"] is False
    assert status["previous_trading_day"] == "2026-10-16"
    assert status["is_mock_data"] is True
    assert status["last_successful"]["session"] == "afternoon"
    assert status["next_scheduled_scan"] == "2026-10-19T09:15:00+05:30"
    latest = client.get("/api/scans/latest").json()
    assert latest["morning"] is None
    assert latest["afternoon"]["trading_date"] == "2026-10-16"


def test_late_manual_scan_is_flagged_stale(client, scan):
    scan(as_of=datetime(2026, 10, 16, 11, 0, tzinfo=IST), scan_type=__import__("app.models", fromlist=["ScanType"]).ScanType.MANUAL)
    body = client.get("/api/scans/2026-10-16/morning").json()
    assert body["scan_type"] == "manual"
    assert body["is_stale"] is True and "after the scheduled" in body["stale_reason"]


def test_admin_requires_key(client):
    assert client.post("/api/admin/scans/run", json={"session": "morning"}).status_code == 401
    r = client.post("/api/admin/scans/run", json={"session": "morning"}, headers={"X-Admin-Key": "wrong"})
    assert r.status_code == 401
    assert client.get("/api/admin/scans/1").status_code == 401


def test_admin_disabled_without_configured_key(client, settings):
    settings.admin_api_key = ""
    r = client.post("/api/admin/scans/run", json={"session": "morning"}, headers={"X-Admin-Key": "anything"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "admin_disabled"


def test_admin_trigger_and_inspect(client):
    h = {"X-Admin-Key": "test-admin-key"}
    r = client.post("/api/admin/scans/run", headers=h,
                    json={"session": "afternoon", "trading_date": "2026-10-16", "use_scheduled_time": True})
    assert r.status_code == 200, r.text
    run = r.json()
    assert run["status"] == "completed" and run["scan_type"] == "manual"
    assert run["attempts"][0]["trigger"] == "admin"
    again = client.post("/api/admin/scans/run", headers=h,
                        json={"session": "afternoon", "trading_date": "2026-10-16", "use_scheduled_time": True})
    assert again.status_code == 409 and again.json()["error"]["code"] == "scan_already_published"
    assert client.get(f"/api/admin/scans/{run['run_id']}", headers=h).json()["summary"]["universe_size"] == 450
    assert client.post("/api/admin/scans/run", headers=h, json={"session": "morning"}).json()["error"]["code"] == "not_a_trading_day"


def test_scheduled_snapshot_preferred_over_manual(client, scan):
    from app.models import ScanType

    manual = scan(scan_type=ScanType.MANUAL)
    scheduled = scan()
    body = client.get("/api/scans/2026-10-16/morning").json()
    assert body["run_id"] == scheduled.id != manual.id


def test_stock_history_and_pick_detail(client, scan, seeded):
    from app.services.performance import measure_close_performance

    run = scan(session=ScanSession.AFTERNOON)
    with seeded() as db:
        measure_close_performance(db, run.trading_date, MockProvider())
    snap = client.get("/api/scans/2026-10-16/afternoon/large-cap").json()
    top = snap["stocks"][0]
    assert top["performance"][0]["measurement_type"] == "close"
    h = client.get(f"/api/stocks/{top['symbol']}/history?from=2026-10-01&to=2026-10-16").json()
    assert h["picks"][0]["trading_date"] == "2026-10-16"
    assert h["price_history_supported"] is True and h["price_history_is_mock"] is True
    assert len(h["price_history"]) == 11
    d = client.get(f"/api/picks/{top['id']}").json()
    assert d["symbol"] == top["symbol"] and d["selection_reason"]
    assert client.get("/api/picks/999999").status_code == 404


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"
