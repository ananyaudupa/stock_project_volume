from functools import lru_cache

from app.core.config import get_settings
from app.services.market_data.base import MarketDataProvider, ProviderError


def build_provider(name: str) -> MarketDataProvider:
    if name == "mock":
        from app.services.market_data.mock import MockProvider

        return MockProvider()
    if name == "yahoo":
        from app.services.market_data.yahoo import YahooProvider

        return YahooProvider()
    # Register licensed vendor adapters here, e.g.:
    #   if name == "myvendor": return MyVendorProvider(api_key=get_settings().market_data_api_key)
    # See docs/data-provider.md for the adapter checklist.
    raise ProviderError(f"unknown MARKET_DATA_PROVIDER '{name}'")


@lru_cache
def get_provider() -> MarketDataProvider:
    return build_provider(get_settings().market_data_provider)
