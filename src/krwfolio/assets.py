from dataclasses import dataclass
from typing import Literal

Currency = Literal["KRW", "USD"]


@dataclass(frozen=True)
class Asset:
    symbol: str
    name: str | None
    currency: Currency
    asset_class: str | None = None
    source: str = "csv"

