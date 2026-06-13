from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from krwfolio.assets import Currency
from krwfolio.exceptions import ValidationError

RebalanceFrequency = Literal["none", "monthly", "quarterly", "yearly"]


@dataclass(frozen=True)
class PortfolioSpec:
    base_currency: Currency
    initial_value: float
    weights: dict[str, float]
    rebalance: RebalanceFrequency = "none"
    transaction_cost_bps: float = 0.0

    def validate(self) -> None:
        if self.base_currency != "KRW":
            raise ValidationError("MVP supports base_currency='KRW' only.")
        if self.initial_value <= 0:
            raise ValidationError("initial_value must be positive.")
        if not self.weights:
            raise ValidationError("weights must not be empty.")
        if any(weight < 0 for weight in self.weights.values()):
            raise ValidationError("long-only MVP requires non-negative weights.")
        if abs(sum(self.weights.values()) - 1.0) > 1e-9:
            raise ValidationError("weights must sum to 1.0.")
        if self.rebalance not in {"none", "monthly", "quarterly", "yearly"}:
            raise ValidationError("rebalance must be none, monthly, quarterly, or yearly.")
        if self.transaction_cost_bps < 0:
            raise ValidationError("transaction_cost_bps must be non-negative.")


@dataclass
class MarketData:
    prices: pd.DataFrame
    fx: pd.DataFrame
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class BacktestResult:
    equity_curve: pd.DataFrame
    holdings: pd.DataFrame
    weights: pd.DataFrame
    trades: pd.DataFrame
    daily_returns: pd.Series
    attribution: dict[str, pd.DataFrame]
    metrics: dict[str, float]
    diagnostics: dict[str, object] = field(default_factory=dict)
