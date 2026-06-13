from dataclasses import dataclass

from krwfolio.assets import Asset
from krwfolio.portfolio import PortfolioSpec


@dataclass(frozen=True)
class RunConfig:
    assets: list[Asset]
    spec: PortfolioSpec
    start: str
    end: str
    price_csv: str | None = None
    fx_csv: str | None = None
    calendar_policy: str = "union_ffill"
    max_staleness_days: int = 7
    rebalance_timing: str = "after_close"
    include_terminal_rebalance: bool = False
