"""Provider-adapter interface. The scanner and ranking engine depend only on these types,
so the market-data source can be swapped without touching scoring logic."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime


class ProviderError(Exception):
    """Non-retryable provider failure (bad credentials, unsupported request, licence limits...)."""


class TransientProviderError(ProviderError):
    """Retryable failure (timeouts, 5xx, rate-limit backoff)."""


@dataclass(frozen=True)
class ProviderCapabilities:
    intraday_quotes: bool
    historical_prices: bool
    same_time_volume_baseline: bool
    # True if quotes can be requested "as of" a past instant (needed for backfills/tests).
    point_in_time_quotes: bool
    is_mock: bool


@dataclass(frozen=True)
class UniverseEntry:
    symbol: str
    company_name: str
    isin: str | None = None


@dataclass(frozen=True)
class Quote:
    """A normalized observation. Any field the provider cannot supply must be None - never invented."""

    symbol: str
    data_timestamp: datetime | None
    last_price: float | None
    open_price: float | None
    previous_close: float | None
    session_volume: int | None  # accumulated current-session volume at data_timestamp
    previous_session_volume: int | None
    avg_daily_volume: float | None  # trailing average of full-session volume (e.g. 20 sessions)
    same_time_avg_volume: float | None  # trailing average of volume accumulated by this time of day
    is_suspended: bool = False
    # True when today is an ex-date and previous_close has NOT been adjusted by the provider.
    unadjusted_corporate_action: bool = False
    flags: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PricePoint:
    symbol: str
    timestamp: datetime
    price: float


@dataclass(frozen=True)
class DailyBar:
    symbol: str
    trading_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


class MarketDataProvider(ABC):
    name: str
    capabilities: ProviderCapabilities

    @abstractmethod
    def list_universe(self) -> list[UniverseEntry]:
        """Symbols the provider covers (used for coverage checks and the mock classification)."""

    @abstractmethod
    def get_quotes(self, symbols: list[str], as_of: datetime) -> dict[str, Quote]:
        """Latest quotes. Symbols the provider has no data for are simply absent from the result."""

    def get_price_at(self, symbol: str, at: datetime) -> PricePoint | None:
        raise ProviderError(f"{self.name} does not support historical point prices")

    def get_daily_history(self, symbol: str, start: date, end: date) -> list[DailyBar]:
        raise ProviderError(f"{self.name} does not support daily history")
