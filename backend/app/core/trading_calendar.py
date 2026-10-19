"""NSE trading-day calendar.

Holidays are loaded from a data file (app/data/nse_holidays.json by default, or HOLIDAYS_FILE).
That file must be refreshed from the official NSE holiday circular each year. Years missing
from the file are treated as *unknown*: the scheduler refuses to run on them rather than guess.
"""

import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

DEFAULT_HOLIDAYS_FILE = Path(__file__).resolve().parent.parent / "data" / "nse_holidays.json"


class UnknownCalendarYear(Exception):
    """Raised when the holiday list for a year has not been loaded."""


class TradingCalendar:
    def __init__(self, holidays: dict[int, dict[date, str]], special_sessions: dict[date, str] | None = None):
        self._holidays = holidays
        self._special = special_sessions or {}

    @classmethod
    def from_file(cls, path: str | Path) -> "TradingCalendar":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        holidays: dict[int, dict[date, str]] = {}
        for year, items in raw.get("holidays", {}).items():
            holidays[int(year)] = {date.fromisoformat(i["date"]): i["name"] for i in items}
        special = {date.fromisoformat(i["date"]): i["name"] for i in raw.get("special_sessions", [])}
        return cls(holidays, special)

    def known_years(self) -> list[int]:
        return sorted(self._holidays)

    def holiday_name(self, d: date) -> str | None:
        if d.year not in self._holidays:
            raise UnknownCalendarYear(f"NSE holiday list for {d.year} is not loaded")
        return self._holidays[d.year].get(d)

    def is_special_session(self, d: date) -> bool:
        """Special sessions (e.g. Muhurat trading) have non-standard hours and are not scanned."""
        return d in self._special

    def is_trading_day(self, d: date) -> bool:
        if d.weekday() >= 5:
            return False
        return self.holiday_name(d) is None

    def non_trading_reason(self, d: date) -> str | None:
        """None for a regular trading day; otherwise a short machine-readable reason."""
        if d.weekday() >= 5:
            return "weekend"
        try:
            name = self.holiday_name(d)
        except UnknownCalendarYear:
            return "calendar_unknown"
        return f"holiday:{name}" if name else None

    def previous_trading_day(self, d: date) -> date:
        cur = d - timedelta(days=1)
        for _ in range(30):
            if self.is_trading_day(cur):
                return cur
            cur -= timedelta(days=1)
        raise RuntimeError(f"no trading day found in the 30 days before {d}")

    def trading_days(self, start: date, end: date) -> list[date]:
        out, cur = [], start
        while cur <= end:
            if self.is_trading_day(cur):
                out.append(cur)
            cur += timedelta(days=1)
        return out


@lru_cache
def get_calendar() -> TradingCalendar:
    path = get_settings().holidays_file or DEFAULT_HOLIDAYS_FILE
    return TradingCalendar.from_file(path)
