import pandas as pd
import pytest

from krwfolio import Asset, BacktestEngine, MarketData, PortfolioSpec


def test_rebalanced_portfolio_differs_from_buy_and_hold_counterfactual():
    assets = [Asset("A", "A", "KRW"), Asset("B", "B", "KRW")]
    dates = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"])
    data = MarketData(
        prices=pd.DataFrame(
            {"A": [100.0, 200.0, 100.0], "B": [100.0, 100.0, 200.0]},
            index=dates,
        ),
        fx=pd.DataFrame({"KRW": [1.0, 1.0, 1.0]}, index=dates),
    )
    spec = PortfolioSpec("KRW", 1_000_000, {"A": 0.5, "B": 0.5}, rebalance="monthly")

    result = BacktestEngine().run(assets, spec, data)
    rebalance = result.attribution["rebalance"].iloc[0]

    assert rebalance["gross_rebalance_effect"] != 0.0
    assert result.metrics["gross_rebalance_effect"] == rebalance["gross_rebalance_effect"]


def test_no_terminal_rebalance_cost_on_final_date():
    assets = [Asset("A", "A", "KRW"), Asset("B", "B", "KRW")]
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-05"])
    data = MarketData(
        prices=pd.DataFrame(
            {"A": [100.0, 200.0, 210.0], "B": [100.0, 100.0, 90.0]},
            index=dates,
        ),
        fx=pd.DataFrame({"KRW": [1.0, 1.0, 1.0]}, index=dates),
    )
    spec = PortfolioSpec(
        "KRW",
        1_000_000,
        {"A": 0.5, "B": 0.5},
        rebalance="monthly",
        transaction_cost_bps=10,
    )

    result = BacktestEngine().run(assets, spec, data)

    assert result.diagnostics["rebalance_dates"] == []
    assert set(result.trades["trade_type"]) == {"initial"}
    assert result.equity_curve["transaction_cost"].iloc[1:].sum() == 0.0


def test_rebalance_none_has_zero_net_rebalance_effect_with_initial_cost():
    assets = [Asset("A", "A", "KRW"), Asset("B", "B", "KRW")]
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    data = MarketData(
        prices=pd.DataFrame({"A": [100.0, 120.0], "B": [100.0, 90.0]}, index=dates),
        fx=pd.DataFrame({"KRW": [1.0, 1.0]}, index=dates),
    )
    spec = PortfolioSpec(
        "KRW",
        1_000_000,
        {"A": 0.5, "B": 0.5},
        rebalance="none",
        transaction_cost_bps=10,
    )

    result = BacktestEngine().run(assets, spec, data)
    rebalance = result.attribution["rebalance"].iloc[0]

    assert rebalance["gross_rebalance_effect"] == pytest.approx(0.0)
    assert rebalance["rebalance_trading_cost_drag"] == pytest.approx(0.0)
    assert rebalance["net_rebalance_effect"] == pytest.approx(0.0)
    assert rebalance["implementation_cost_drag"] < 0


def test_rebalance_uses_execution_calendar_and_requires_fx_observed():
    assets = [Asset("KR", "KR", "KRW"), Asset("US", "US", "USD")]
    dates = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-01"])
    data = MarketData(
        prices=pd.DataFrame(
            {"KR": [100.0, 110.0, 111.0], "US": [100.0, 120.0, 121.0]},
            index=dates,
        ),
        fx=pd.DataFrame(
            {"USD": [1300.0, None, 1310.0], "KRW": [1.0, 1.0, 1.0]},
            index=dates,
        ),
    )
    spec = PortfolioSpec("KRW", 1_000_000, {"KR": 0.5, "US": 0.5}, rebalance="monthly")

    result = BacktestEngine(max_staleness_days=40).run(assets, spec, data)

    assert result.diagnostics["scheduled_rebalance_candidates"] == []
    assert result.diagnostics["executed_rebalance_dates"] == []
    assert set(result.trades["trade_type"]) == {"initial"}


def test_transaction_cost_matches_turnover_basis():
    assets = [Asset("A", "A", "KRW"), Asset("B", "B", "KRW")]
    dates = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-29"])
    data = MarketData(
        prices=pd.DataFrame({"A": [100.0, 200.0, 100.0], "B": [100.0, 100.0, 200.0]}, index=dates),
        fx=pd.DataFrame({"KRW": [1.0, 1.0, 1.0]}, index=dates),
    )
    spec = PortfolioSpec(
        "KRW",
        1_000_000,
        {"A": 0.5, "B": 0.5},
        rebalance="monthly",
        transaction_cost_bps=10,
    )

    result = BacktestEngine().run(assets, spec, data)

    expected_cost = result.trades["turnover_basis_base"].sum() * 10 / 10_000
    assert result.trades["cost_base"].sum() == pytest.approx(expected_cost)
    assert result.equity_curve["transaction_cost"].sum() == pytest.approx(expected_cost)
    assert "turnover_rebalance_cost_basis" in result.metrics
    assert "turnover_rebalance_executed" in result.metrics
