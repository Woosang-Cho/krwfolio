import json

import pandas as pd
import pytest

from krwfolio import Asset, BacktestEngine, MarketData, PortfolioSpec
from krwfolio.exceptions import DataError, ValidationError
from krwfolio.io.exporters import export_result
from krwfolio.io.spec_loader import load_run_config_text


def test_two_asset_offsetting_returns_produce_zero_portfolio_return():
    assets = [Asset("A", "A", "KRW"), Asset("B", "B", "KRW")]
    spec = PortfolioSpec("KRW", 1_000_000, {"A": 0.5, "B": 0.5})
    data = MarketData(
        prices=pd.DataFrame(
            {"A": [100.0, 110.0], "B": [100.0, 90.0]},
            index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
        ),
        fx=pd.DataFrame({"KRW": [1.0, 1.0]}, index=pd.to_datetime(["2024-01-02", "2024-01-03"])),
    )

    result = BacktestEngine().run(assets, spec, data)

    assert round(result.metrics["total_return"], 10) == 0.0
    assert round(result.attribution["daily"].iloc[1]["portfolio_contribution"], 10) == 0.0


def test_cumulative_pnl_contribution_equals_final_total_return():
    assets = [Asset("KR", "KR", "KRW"), Asset("US", "US", "USD")]
    spec = PortfolioSpec("KRW", 1_000_000, {"KR": 0.4, "US": 0.6}, transaction_cost_bps=5)
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    data = MarketData(
        prices=pd.DataFrame({"KR": [100.0, 105.0, 103.0], "US": [100.0, 110.0, 108.0]}, index=dates),
        fx=pd.DataFrame({"USD": [1000.0, 1100.0, 1090.0], "KRW": [1.0, 1.0, 1.0]}, index=dates),
    )

    result = BacktestEngine().run(assets, spec, data)
    cumulative = result.attribution["cumulative"].iloc[0]

    assert round(cumulative["total_contribution"], 10) == round(result.metrics["total_return"], 10)
    parts = (
        cumulative["asset_contribution"]
        + cumulative["cash_contribution"]
        + cumulative["cost_contribution"]
    )
    assert round(parts, 10) == round(result.metrics["total_return"], 10)


def test_ledger_reconciles_nav_attribution_and_costs():
    assets = [Asset("KR", "KR", "KRW"), Asset("US", "US", "USD")]
    spec = PortfolioSpec(
        "KRW",
        1_000_000,
        {"KR": 0.4, "US": 0.6},
        rebalance="monthly",
        transaction_cost_bps=5,
    )
    dates = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-29"])
    data = MarketData(
        prices=pd.DataFrame({"KR": [100.0, 110.0, 105.0], "US": [100.0, 95.0, 108.0]}, index=dates),
        fx=pd.DataFrame({"USD": [1300.0, 1320.0, 1280.0], "KRW": [1.0, 1.0, 1.0]}, index=dates),
    )

    result = BacktestEngine().run(assets, spec, data)
    equity = result.equity_curve
    daily = result.attribution["daily"]

    total_return_from_nav = equity["nav"].iloc[-1] / spec.initial_value - 1.0
    total_return_from_attr = daily["total_pnl"].sum() / spec.initial_value
    assert total_return_from_nav == pytest.approx(total_return_from_attr)
    assert result.attribution["cumulative"].iloc[0]["total_contribution"] == pytest.approx(
        total_return_from_nav
    )
    asset_parts = daily["local_pnl"] + daily["fx_pnl"] + daily["cross_pnl"]
    total_parts = daily["asset_pnl"] + daily["cash_pnl"] + daily["cost_pnl"]
    assert (daily["asset_pnl"] - asset_parts).abs().max() < 1e-9
    assert (daily["total_pnl"] - total_parts).abs().max() < 1e-9
    assert equity["transaction_cost"].sum() == pytest.approx(-daily["cost_pnl"].sum())
    previous_nav = pd.Series(
        [spec.initial_value, *equity["nav"].iloc[:-1].tolist()],
        index=equity.index,
    )
    assert (daily["portfolio_contribution"] - equity["daily_return"]).abs().max() < 1e-12
    assert (daily["total_pnl"] / previous_nav - equity["daily_return"]).abs().max() < 1e-12


def test_result_schema_version_and_required_columns_are_stable():
    assets = [Asset("A", "A", "KRW"), Asset("B", "B", "KRW")]
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    data = MarketData(
        prices=pd.DataFrame({"A": [100.0, 101.0], "B": [100.0, 99.0]}, index=dates),
        fx=pd.DataFrame({"KRW": [1.0, 1.0]}, index=dates),
    )
    spec = PortfolioSpec("KRW", 1_000_000, {"A": 0.5, "B": 0.5}, transaction_cost_bps=5)

    result = BacktestEngine().run(assets, spec, data)

    assert result.schema_version == "0.2"
    assert {"nav", "cash", "transaction_cost", "daily_return", "risk_daily_return", "drawdown"} <= set(
        result.equity_curve.columns
    )
    assert {"trade_type", "trade_value_base", "cost_base", "turnover_basis_base"} <= set(
        result.trades.columns
    )
    assert {
        "local_pnl",
        "fx_pnl",
        "cross_pnl",
        "asset_pnl",
        "cash_pnl",
        "cost_pnl",
        "total_pnl",
        "portfolio_contribution",
    } <= set(result.attribution["daily"].columns)
    assert {"asset_contribution", "cash_contribution", "cost_contribution", "total_contribution"} <= set(
        result.attribution["cumulative"].columns
    )
    assert {"total_return", "cagr", "mdd", "volatility", "sharpe"} <= set(result.metrics)
    assert {"effective_start", "effective_end", "scheduled_rebalance_dates", "executed_rebalance_dates"} <= set(
        result.diagnostics
    )


def test_json_export_includes_schema_version(tmp_path):
    assets = [Asset("A", "A", "KRW")]
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    data = MarketData(
        prices=pd.DataFrame({"A": [100.0, 101.0]}, index=dates),
        fx=pd.DataFrame({"KRW": [1.0, 1.0]}, index=dates),
    )
    result = BacktestEngine().run(assets, PortfolioSpec("KRW", 1_000_000, {"A": 1.0}), data)

    export_result(result, tmp_path, {"json"})

    payload = json.loads((tmp_path / "result.json").read_text())
    assert payload["schema_version"] == "0.2"
    assert "metrics" in payload
    assert "diagnostics" in payload


def test_initial_cost_is_kept_out_of_risk_daily_return():
    assets = [Asset("A", "A", "KRW")]
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    data = MarketData(
        prices=pd.DataFrame({"A": [100.0, 100.0]}, index=dates),
        fx=pd.DataFrame({"KRW": [1.0, 1.0]}, index=dates),
    )
    spec = PortfolioSpec("KRW", 1_000_000, {"A": 1.0}, transaction_cost_bps=10)

    result = BacktestEngine().run(assets, spec, data)

    assert result.equity_curve["daily_return"].iloc[0] == pytest.approx(-0.001)
    assert result.equity_curve["risk_daily_return"].iloc[0] == pytest.approx(0.0)
    assert result.metrics["total_return"] == pytest.approx(-0.001)
    assert result.metrics["volatility"] == pytest.approx(0.0)


def test_staleness_over_limit_raises_data_error():
    assets = [Asset("A", "A", "KRW")]
    price_dates = pd.to_datetime(["2024-01-01", "2024-01-10"])
    fx_dates = pd.date_range("2024-01-01", "2024-01-10", freq="D")
    data = MarketData(
        prices=pd.DataFrame({"A": [100.0, 110.0]}, index=price_dates),
        fx=pd.DataFrame({"KRW": [1.0] * len(fx_dates)}, index=fx_dates),
    )
    spec = PortfolioSpec("KRW", 1_000_000, {"A": 1.0})

    with pytest.raises(DataError, match="last_observed=2024-01-01, stale_days=4"):
        BacktestEngine(max_staleness_days=3).run(assets, spec, data)


def test_staleness_before_effective_start_is_detected():
    assets = [Asset("A", "A", "KRW"), Asset("B", "B", "KRW")]
    data = MarketData(
        prices=pd.DataFrame(
            {"A": [100.0, None, 110.0], "B": [None, 200.0, 210.0]},
            index=pd.to_datetime(["2024-01-01", "2024-01-10", "2024-01-11"]),
        ),
        fx=pd.DataFrame(
            {"KRW": [1.0, 1.0, 1.0]},
            index=pd.to_datetime(["2024-01-01", "2024-01-10", "2024-01-11"]),
        ),
    )
    spec = PortfolioSpec("KRW", 1_000_000, {"A": 0.5, "B": 0.5})

    with pytest.raises(DataError, match="2024-01-10"):
        BacktestEngine(max_staleness_days=3).run(assets, spec, data)


def test_unused_fx_column_does_not_trigger_validation():
    assets = [Asset("A", "A", "KRW")]
    dates = pd.to_datetime(["2024-01-01", "2024-01-02"])
    data = MarketData(
        prices=pd.DataFrame({"A": [100.0, 101.0]}, index=dates),
        fx=pd.DataFrame({"EUR": [0.0, 0.0]}, index=dates),
    )
    spec = PortfolioSpec("KRW", 1_000_000, {"A": 1.0})

    result = BacktestEngine().run(assets, spec, data)

    assert result.metrics["total_return"] == pytest.approx(0.01)
    assert result.diagnostics["unused_fx_columns"] == ["EUR"]


def test_market_data_input_is_not_mutated_when_krw_fx_column_missing():
    assets = [Asset("A", "A", "KRW")]
    dates = pd.to_datetime(["2024-01-01", "2024-01-02"])
    fx = pd.DataFrame({"USD": [1300.0, 1310.0]}, index=dates)
    data = MarketData(
        prices=pd.DataFrame({"A": [100.0, 101.0]}, index=dates),
        fx=fx,
    )
    spec = PortfolioSpec("KRW", 1_000_000, {"A": 1.0})

    BacktestEngine().run(assets, spec, data)

    assert "KRW" not in fx.columns
    assert "KRW" not in data.fx.columns


def test_yaml_calendar_config_is_parsed():
    config = load_run_config_text(
        """
base_currency: KRW
initial_value: 1000000
start: 2024-01-01
end: 2024-01-02
calendar:
  policy: union_ffill
  max_staleness_days: 2
rebalance:
  frequency: monthly
  timing: after_close
  transaction_cost_bps: 3
  include_terminal_rebalance: true
assets:
  - symbol: A
    currency: KRW
    weight: 1.0
"""
    )

    assert config.calendar_policy == "union_ffill"
    assert config.max_staleness_days == 2
    assert config.include_terminal_rebalance is True


def test_nested_yaml_typo_raises_validation_error():
    with pytest.raises(Exception, match="Unknown rebalance keys"):
        load_run_config_text(
            """
base_currency: KRW
initial_value: 1000000
start: 2024-01-01
end: 2024-01-02
rebalance:
  frequency: monthly
  transaction_cost_bp: 3
assets:
  - symbol: A
    currency: KRW
    weight: 1.0
"""
        )


@pytest.mark.parametrize(
    ("yaml_text", "message"),
    [
        (
            """
base_currency: KRW
initial_value: 1000000
start: 2024-01-01
end: 2024-01-02
rebalance: monthly
assets:
  - symbol: A
    currency: KRW
    weight: 1.0
""",
            "rebalance must be a mapping/object",
        ),
        (
            """
base_currency: KRW
initial_value: 1000000
start: 2024-01-01
end: 2024-01-02
rebalance:
  include_terminal_rebalance: "false"
assets:
  - symbol: A
    currency: KRW
    weight: 1.0
""",
            "rebalance.include_terminal_rebalance must be boolean",
        ),
        (
            """
base_currency: KRW
initial_value: abc
start: 2024-01-01
end: 2024-01-02
assets:
  - symbol: A
    currency: KRW
    weight: 1.0
""",
            "initial_value must be a number",
        ),
        (
            """
base_currency: KRW
initial_value: 1000000
start: 2024-01-01
end: 2024-01-02
assets:
  - symbol: A
    currency: KRW
""",
            "Missing required YAML field: asset.weight",
        ),
        (
            """
base_currency: KRW
initial_value: 1000000
start: 2024-01-01
end: 2024-01-02
fx:
  USD: KRW=X
assets:
  - symbol: A
    currency: KRW
    weight: 1.0
""",
            "Unknown YAML keys: \\['fx'\\]",
        ),
        (
            """
base_currency: KRW
initial_value: 1000000
start: 2024-01-01
end: 2024-01-02
calendar:
  max_staleness_days: -1
assets:
  - symbol: A
    currency: KRW
    weight: 1.0
""",
            "calendar.max_staleness_days must be non-negative",
        ),
    ],
)
def test_yaml_validation_errors_are_explicit(yaml_text, message):
    with pytest.raises(ValidationError, match=message):
        load_run_config_text(yaml_text)
