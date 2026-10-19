from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api import deps
from app.core.config import Settings, get_settings
from app.core.trading_calendar import DEFAULT_HOLIDAYS_FILE, TradingCalendar
from app.db.base import Base
from app.db.session import make_engine
from app.main import create_app
from app.models import ScanSession
from app.services.classification import import_mock_classification
from app.services.market_data.mock import MockProvider
from app.services.scanner import run_scan, scheduled_time

IST = ZoneInfo("Asia/Kolkata")
FRIDAY = date(2026, 10, 16)  # regular trading day
THURSDAY = date(2026, 10, 15)
SATURDAY = date(2026, 10, 17)
DUSSEHRA = date(2026, 10, 20)  # NSE holiday


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        admin_api_key="test-admin-key",
        provider_retry_base_delay_seconds=0,
        alert_webhook_url="",
    )


@pytest.fixture
def calendar() -> TradingCalendar:
    return TradingCalendar.from_file(DEFAULT_HOLIDAYS_FILE)


@pytest.fixture
def factory(settings):
    engine = make_engine(settings.database_url)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def provider() -> MockProvider:
    return MockProvider()


@pytest.fixture
def seeded(factory, provider):
    with factory() as db:
        import_mock_classification(db, provider, date(2026, 9, 30))
    return factory


@pytest.fixture
def scan(seeded, provider, settings, calendar):
    """Run a scan at its scheduled time (the mock provider supports point-in-time quotes)."""

    def _scan(d: date = FRIDAY, session: ScanSession = ScanSession.MORNING, prov=None, **kw):
        return run_scan(
            seeded, d, session, provider=prov or provider, settings=settings, calendar=calendar,
            as_of=kw.pop("as_of", scheduled_time(d, session, settings)), sleep=lambda _: None, **kw,
        )

    return _scan


class Clock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 10, 17, 6, 0, tzinfo=timezone.utc))  # Saturday 11:30 IST


@pytest.fixture
def client(seeded, settings, provider, calendar, clock):
    app = create_app()

    def _db():
        db = seeded()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[deps.get_db] = _db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[deps.provider_dep] = lambda: provider
    app.dependency_overrides[deps.calendar_dep] = lambda: calendar
    app.dependency_overrides[deps.session_factory_dep] = lambda: seeded
    app.dependency_overrides[deps.now_dep] = clock
    with TestClient(app) as c:
        yield c
