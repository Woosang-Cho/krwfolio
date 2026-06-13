from typing import Protocol

from krwfolio.assets import Asset
from krwfolio.portfolio import MarketData


class DataProvider(Protocol):
    def load(self, assets: list[Asset], start: str, end: str) -> MarketData:
        """Load local prices and FX rates for a date range."""

