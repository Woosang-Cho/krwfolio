from __future__ import annotations

import math

import pandas as pd

from krwfolio.analytics.drawdown import max_drawdown
from krwfolio.analytics.risk import annualized_volatility, sharpe_ratio


def compute_metrics(
    nav: pd.Series,
    daily_returns: pd.Series,
    trades: pd.DataFrame,
    initial_value: float | None = None,
    risk_free_rate: float = 0.0,
) -> dict[str, float]:
    starting_value = float(initial_value if initial_value is not None else nav.iloc[0])
    total_return = float(nav.iloc[-1] / starting_value - 1.0)
    years = max((nav.index[-1] - nav.index[0]).days / 365.25, 1 / 365.25)
    cagr = float((nav.iloc[-1] / starting_value) ** (1.0 / years) - 1.0)
    periods_per_year, median_gap_days = infer_periods_per_year(nav.index)
    turnover_total_cost_basis = 0.0
    turnover_total_executed = 0.0
    turnover_rebalance_cost_basis = 0.0
    turnover_rebalance_executed = 0.0
    initial_investment_ratio = 0.0
    if not trades.empty:
        turnover_total_cost_basis = float(trades["turnover_basis_base"].sum() / nav.mean())
        turnover_total_executed = float(trades["executed_trade_value_base"].abs().sum() / nav.mean())
        rebalance_trades = trades[trades["trade_type"] == "rebalance"]
        initial_trades = trades[trades["trade_type"] == "initial"]
        turnover_rebalance_cost_basis = float(rebalance_trades["turnover_basis_base"].sum() / nav.mean())
        turnover_rebalance_executed = float(
            rebalance_trades["executed_trade_value_base"].abs().sum() / nav.mean()
        )
        initial_investment_ratio = float(
            initial_trades["executed_trade_value_base"].abs().sum() / starting_value
        )
    return {
        "total_return": total_return,
        "cagr": cagr,
        "mdd": max_drawdown(nav),
        "volatility": annualized_volatility(daily_returns, periods_per_year=periods_per_year),
        "sharpe": sharpe_ratio(
            daily_returns,
            risk_free_rate=risk_free_rate,
            periods_per_year=periods_per_year,
        ),
        "turnover": turnover_rebalance_cost_basis,
        "turnover_total_cost_basis": turnover_total_cost_basis,
        "turnover_total_executed": turnover_total_executed,
        "turnover_rebalance_cost_basis": turnover_rebalance_cost_basis,
        "turnover_rebalance_executed": turnover_rebalance_executed,
        "turnover_rebalance_only": turnover_rebalance_cost_basis,
        "initial_investment_ratio": initial_investment_ratio,
        "annualization_periods_per_year": float(periods_per_year),
        "median_valuation_gap_days": float(median_gap_days),
    }


def infer_periods_per_year(index: pd.DatetimeIndex) -> tuple[int, float]:
    if len(index) < 2:
        return 252, 1.0
    gaps = index.to_series().diff().dropna().dt.days
    median_gap = float(gaps.median())
    if median_gap <= 1.5:
        return 252, median_gap
    periods = max(1, min(252, math.ceil(365.25 / median_gap)))
    return periods, median_gap
