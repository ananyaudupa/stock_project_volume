"""Shared FastAPI dependencies (overridable in tests)."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.trading_calendar import TradingCalendar, get_calendar
from app.db.session import get_db, get_sessionmaker
from app.services.market_data import get_provider
from app.services.market_data.base import MarketDataProvider


# Settings are injected via get_settings itself so one override covers every consumer.
settings_dep = get_settings


def calendar_dep() -> TradingCalendar:
    return get_calendar()


def provider_dep() -> MarketDataProvider:
    return get_provider()


def session_factory_dep() -> sessionmaker[Session]:
    return get_sessionmaker()


def now_dep() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["calendar_dep", "get_db", "now_dep", "provider_dep", "session_factory_dep", "settings_dep"]
