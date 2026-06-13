import math

import pandas as pd


def annualized_volatility(daily_returns: pd.Series, periods_per_year: int = 252) -> float:
    return float(daily_returns.iloc[1:].std(ddof=0) * math.sqrt(periods_per_year))


def sharpe_ratio(
    daily_returns: pd.Series,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    returns = daily_returns.iloc[1:]
    if returns.empty or returns.std(ddof=0) == 0:
        return 0.0
    daily_rf = (1.0 + risk_free_rate) ** (1.0 / periods_per_year) - 1.0
    excess = returns - daily_rf
    return float(excess.mean() / returns.std(ddof=0) * math.sqrt(periods_per_year))

