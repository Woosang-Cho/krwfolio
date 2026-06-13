import pandas as pd
import pytest

from krwfolio.analytics.metrics import compute_metrics


def test_metrics_total_return_can_use_initial_value():
    nav = pd.Series([999_500.0, 1_100_000.0], index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
    daily_returns = pd.Series([-0.0005, 0.10055], index=nav.index)
    trades = pd.DataFrame()

    metrics = compute_metrics(nav, daily_returns, trades, initial_value=1_000_000.0)

    assert metrics["total_return"] == pytest.approx(0.1)
