from datetime import date

import pytest

from app.core.trading_calendar import TradingCalendar, UnknownCalendarYear
from tests.conftest import DUSSEHRA, FRIDAY, SATURDAY


def test_weekends_and_holidays_are_not_trading_days(calendar):
    assert calendar.is_trading_day(FRIDAY)
    assert not calendar.is_trading_day(SATURDAY)
    assert not calendar.is_trading_day(DUSSEHRA)
    assert calendar.non_trading_reason(SATURDAY) == "weekend"
    assert calendar.non_trading_reason(DUSSEHRA) == "holiday:Dussehra"
    assert calendar.non_trading_reason(FRIDAY) is None


def test_previous_trading_day_skips_weekends_and_holidays(calendar):
    assert calendar.previous_trading_day(date(2026, 10, 19)) == FRIDAY  # Monday -> Friday
    assert calendar.previous_trading_day(date(2026, 10, 21)) == date(2026, 10, 19)  # skips Dussehra
    assert calendar.previous_trading_day(date(2026, 10, 5)) == date(2026, 10, 1)  # skips Gandhi Jayanti + weekend


def test_unknown_year_is_never_guessed(calendar):
    with pytest.raises(UnknownCalendarYear):
        calendar.is_trading_day(date(2031, 1, 6))
    assert calendar.non_trading_reason(date(2031, 1, 6)) == "calendar_unknown"
    # weekends are still known to be closed
    assert calendar.non_trading_reason(date(2031, 1, 4)) == "weekend"


def test_trading_days_range(calendar):
    days = calendar.trading_days(date(2026, 10, 12), date(2026, 10, 23))
    assert DUSSEHRA not in days
    assert len(days) == 9


def test_2026_matches_official_nse_circulars(calendar):
    # NSE/CMTR/71775 (15 weekday holidays) + NSE/CMTR/72260 (Jan 15 election holiday)
    weekday_holidays = [d for d in calendar._holidays[2026]]
    assert len(weekday_holidays) == 16
    assert all(d.weekday() < 5 for d in weekday_holidays)
    assert calendar.non_trading_reason(date(2026, 1, 15)).startswith("holiday:")
    assert calendar.previous_trading_day(date(2026, 1, 16)) == date(2026, 1, 14)
    assert calendar.is_special_session(date(2026, 11, 8))  # Muhurat: not scanned


def test_special_sessions():
    cal = TradingCalendar({2026: {}}, {date(2026, 11, 8): "Muhurat trading"})
    assert cal.is_special_session(date(2026, 11, 8))
