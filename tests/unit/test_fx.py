import pandas as pd
import pytest

from krwfolio import Asset, BacktestEngine, MarketData, PortfolioSpec


def test_usd_fx_only_return_is_attributed_to_fx():
    assets = [Asset("SPY", "SPY", "USD")]
    spec = PortfolioSpec("KRW", 1_000_000, {"SPY": 1.0})
    data = MarketData(
        prices=pd.DataFrame({"SPY": [100.0, 100.0]}, index=pd.to_datetime(["2024-01-02", "2024-01-03"])),
        fx=pd.DataFrame({"USD": [1000.0, 1100.0], "KRW": [1.0, 1.0]}, index=pd.to_datetime(["2024-01-02", "2024-01-03"])),
    )

    result = BacktestEngine().run(assets, spec, data)

    daily = result.attribution["daily"].iloc[1]
    assert result.metrics["total_return"] == pytest.approx(0.1)
    assert daily["local_contribution"] == 0.0
    assert daily["fx_contribution"] == pytest.approx(0.1)
    assert daily["cross_contribution"] == 0.0


def test_usd_local_and_fx_cross_term_reconciles():
    assets = [Asset("SPY", "SPY", "USD")]
    spec = PortfolioSpec("KRW", 1_000_000, {"SPY": 1.0})
    data = MarketData(
        prices=pd.DataFrame({"SPY": [100.0, 110.0]}, index=pd.to_datetime(["2024-01-02", "2024-01-03"])),
        fx=pd.DataFrame({"USD": [1000.0, 1100.0], "KRW": [1.0, 1.0]}, index=pd.to_datetime(["2024-01-02", "2024-01-03"])),
    )

    result = BacktestEngine().run(assets, spec, data)

    daily = result.attribution["daily"].iloc[1]
    assert round(result.metrics["total_return"], 10) == 0.21
    assert round(daily["local_contribution"], 10) == 0.1
    assert round(daily["fx_contribution"], 10) == 0.1
    assert round(daily["cross_contribution"], 10) == 0.01


def test_krw_asset_has_no_fx_or_cross_contribution():
    assets = [Asset("069500.KS", "KODEX 200", "KRW")]
    spec = PortfolioSpec("KRW", 1_000_000, {"069500.KS": 1.0})
    data = MarketData(
        prices=pd.DataFrame({"069500.KS": [10_000.0, 11_000.0]}, index=pd.to_datetime(["2024-01-02", "2024-01-03"])),
        fx=pd.DataFrame({"KRW": [1.0, 1.0]}, index=pd.to_datetime(["2024-01-02", "2024-01-03"])),
    )

    result = BacktestEngine().run(assets, spec, data)

    daily = result.attribution["daily"].iloc[1]
    assert round(result.metrics["total_return"], 10) == 0.1
    assert round(daily["local_contribution"], 10) == 0.1
    assert daily["fx_contribution"] == 0.0
    assert daily["cross_contribution"] == 0.0
