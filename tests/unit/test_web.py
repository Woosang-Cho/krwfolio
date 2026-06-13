from io import StringIO

import pandas as pd

from krwfolio.portfolio import MarketData
from krwfolio.web import (
    SAMPLE_FX,
    SAMPLE_PRICES,
    SAMPLE_YAML,
    equity_chart,
    render_page,
    run_backtest_html,
    simple_fields_from_form,
    simple_fields_to_yaml,
)


def test_web_backtest_renders_results():
    html = run_backtest_html(SAMPLE_YAML, SAMPLE_PRICES, SAMPLE_FX)

    assert "결과" in html
    assert "Total Return" in html
    assert "성과 분해" in html
    assert "누적 PnL 기여도" in html
    assert "sum(daily total_pnl)" in html
    assert "원화 기준 NAV" in html


def test_web_initial_page_does_not_render_results():
    html = render_page()

    assert '<section class="results">' not in html
    assert "Total Return" not in html
    assert "간편 입력" in html
    assert "10,000,000" in html
    assert "FX는 foreign exchange" in html
    assert "asset-card" in html
    assert "자산 추가" in html
    assert "ticker-suggestions" in html
    assert "yfinance 결과는 나중에 달라질 수 있습니다" in html
    assert 'name="start_year"' in html
    assert 'name="end_year"' in html
    assert 'name="start_date"' in html
    assert 'name="end_date"' in html


def test_simple_fields_to_yaml_accepts_comma_initial_value():
    yaml_text = simple_fields_to_yaml(
        {
            "initial_value": "10,000,000",
            "start": "2024-01-02",
            "end": "2024-12-31",
            "rebalance": "quarterly",
            "transaction_cost_bps": "5",
            "symbols": ["SPY", "TLT", "", "", ""],
            "names": ["SPY", "TLT", "", "", ""],
            "currencies": ["USD", "USD", "USD", "USD", "USD"],
            "weights": ["60", "40", "", "", ""],
        }
    )

    assert "initial_value: 10000000" in yaml_text
    assert "symbol: SPY" in yaml_text
    assert "weight: 0.6" in yaml_text


def test_simple_fields_from_form_builds_dates_from_parts():
    fields = simple_fields_from_form(
        {
            "initial_value": ["10,000,000"],
            "start_year": ["2020"],
            "start_date": ["2025-01-02"],
            "end_year": ["2024"],
            "end_date": ["2026-12-31"],
            "symbol": ["SPY"],
            "currency": ["USD"],
            "weight": ["100"],
        }
    )

    assert fields["start"] == "2020-01-02"
    assert fields["end"] == "2024-12-31"


def test_web_formats_equity_amounts_as_amounts_not_percentages():
    html = run_backtest_html(SAMPLE_YAML, SAMPLE_PRICES, SAMPLE_FX)

    assert "1000000000.0000%" not in html
    assert "transaction_cost" in html


def test_web_formats_attribution_percentages_to_two_decimals():
    html = run_backtest_html(SAMPLE_YAML, SAMPLE_PRICES, SAMPLE_FX)

    assert "43.71%" in html
    assert "43.7128%" not in html


def test_web_samples_use_multi_year_dates():
    assert "start: 2020-01-02" in SAMPLE_YAML
    assert "end: 2024-12-31" in SAMPLE_YAML


def test_web_yfinance_mode_uses_provider(monkeypatch):
    class FakeYFinanceProvider:
        def load(self, assets, start, end):
            assert [asset.symbol for asset in assets] == ["069500.KS", "SPY", "TLT"]
            assert start == "2020-01-02"
            assert end == "2024-12-31"
            prices = pd.read_csv(StringIO(SAMPLE_PRICES), index_col=0, parse_dates=True)
            fx = pd.read_csv(StringIO(SAMPLE_FX), index_col=0, parse_dates=True)
            return MarketData(prices=prices, fx=fx)

    monkeypatch.setattr("krwfolio.web.YFinanceProvider", FakeYFinanceProvider)

    html = run_backtest_html(SAMPLE_YAML, "", "", data_source="yfinance")

    assert "Data source: yfinance" in html
    assert "Total Return" in html


def test_equity_chart_has_axes_and_labels():
    nav = pd.Series(
        [10_000_000, 10_500_000, 11_250_000],
        index=pd.to_datetime(["2024-01-02", "2024-06-03", "2024-12-31"]),
    )

    html = equity_chart(nav)

    assert "원화 기준 NAV" in html
    assert "2024-01-02" not in html
    assert "2024 Q1" in html
    assert "시작" in html
    assert "종료" in html
    assert "만" in html


def test_equity_chart_uses_month_grid_without_month_labels_for_daily_series():
    nav = pd.Series(
        range(250),
        index=pd.date_range("2024-01-02", periods=250, freq="B"),
        dtype=float,
    ) + 10_000_000

    html = equity_chart(nav)

    assert "month-tick" in html
    assert html.count('class="tick-label"') < 15
