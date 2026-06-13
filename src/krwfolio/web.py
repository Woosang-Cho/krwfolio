from __future__ import annotations

from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from urllib.parse import parse_qs

import pandas as pd

from krwfolio.core.engine import BacktestEngine
from krwfolio.data.yfinance_provider import YFinanceProvider
from krwfolio.io.spec_loader import load_run_config_text
from krwfolio.portfolio import MarketData

MAX_POST_BYTES = 2_000_000
DEFAULT_SIMPLE_FIELDS = {
    "initial_value": "10,000,000",
    "start": "2020-01-02",
    "end": "2024-12-31",
    "rebalance": "quarterly",
    "transaction_cost_bps": "5",
    "symbols": ["069500.KS", "SPY", "TLT", "", ""],
    "names": ["KODEX 200", "SPDR S&P 500 ETF", "iShares 20+ Year Treasury Bond ETF", "", ""],
    "currencies": ["KRW", "USD", "USD", "USD", "USD"],
    "weights": ["40", "40", "20", "", ""],
}

SAMPLE_YAML = """base_currency: KRW
initial_value: 10000000
start: 2020-01-02
end: 2024-12-31
calendar:
  policy: union_ffill
  max_staleness_days: 7
rebalance:
  frequency: quarterly
  timing: after_close
  transaction_cost_bps: 5
assets:
  - symbol: 069500.KS
    name: KODEX 200
    currency: KRW
    asset_class: Korea Equity
    weight: 0.4
  - symbol: SPY
    name: SPDR S&P 500 ETF
    currency: USD
    asset_class: US Equity
    weight: 0.4
  - symbol: TLT
    name: iShares 20+ Year Treasury Bond ETF
    currency: USD
    asset_class: US Bond
    weight: 0.2
"""

SAMPLE_PRICES = """date,069500.KS,SPY,TLT
2020-01-02,29800,324.87,137.01
2020-04-01,22100,246.15,162.93
2020-07-01,28950,310.52,163.71
2020-10-01,31150,337.04,160.60
2021-01-04,40200,368.79,151.23
2021-04-01,43050,400.61,136.10
2021-07-01,43900,430.43,145.67
2021-10-01,39200,434.24,143.18
2022-01-03,39700,477.71,148.19
2022-04-01,35600,452.92,132.88
2022-07-01,30300,381.24,114.14
2022-10-03,28300,357.18,102.03
2023-01-02,28950,380.82,100.92
2023-04-03,33700,410.95,106.02
2023-07-03,35450,443.79,101.94
2023-10-02,34100,427.31,86.92
2024-01-02,38000,472.65,98.88
2024-04-01,39500,522.16,91.35
2024-07-01,41850,545.34,91.86
2024-10-01,40500,568.62,88.53
2024-12-31,43200,586.08,87.39
"""

SAMPLE_FX = """date,USD,KRW
2020-01-02,1158.1,1.0
2020-04-01,1230.5,1.0
2020-07-01,1200.0,1.0
2020-10-01,1165.7,1.0
2021-01-04,1087.6,1.0
2021-04-01,1131.2,1.0
2021-07-01,1130.0,1.0
2021-10-01,1188.5,1.0
2022-01-03,1191.8,1.0
2022-04-01,1216.5,1.0
2022-07-01,1297.3,1.0
2022-10-03,1434.8,1.0
2023-01-02,1272.6,1.0
2023-04-03,1316.5,1.0
2023-07-03,1305.2,1.0
2023-10-02,1352.4,1.0
2024-01-02,1308.0,1.0
2024-04-01,1348.6,1.0
2024-07-01,1380.1,1.0
2024-10-01,1320.7,1.0
2024-12-31,1472.5,1.0
"""


def run_web_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), KrwfolioHandler)
    print(f"krwfolio web is running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping krwfolio web.")
    finally:
        server.server_close()


class KrwfolioHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self._send_html(render_page())

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length > MAX_POST_BYTES:
            error = (
                "<div class='error'><strong>Error</strong>"
                f"<pre>Request body is too large. Limit: {MAX_POST_BYTES} bytes.</pre></div>"
            )
            self._send_html(render_page(result_html=error))
            return
        body = self.rfile.read(content_length).decode("utf-8")
        form = parse_qs(body)
        yaml_text = form.get("yaml", [""])[0]
        prices_csv = form.get("prices", [""])[0]
        fx_csv = form.get("fx", [""])[0]
        input_mode = form.get("input_mode", ["simple"])[0]
        data_source = form.get("data_source", ["yfinance"])[0]
        include_rebalance_attribution = form.get("include_rebalance_attribution", [""])[0] == "on"
        simple_fields = simple_fields_from_form(form)
        if input_mode == "simple":
            yaml_text = simple_fields_to_yaml(simple_fields)
        try:
            result_html = run_backtest_html(
                yaml_text,
                prices_csv,
                fx_csv,
                data_source=data_source,
                include_rebalance_attribution=include_rebalance_attribution,
            )
            self._send_html(
                render_page(
                    yaml_text,
                    prices_csv,
                    fx_csv,
                    input_mode=input_mode,
                    data_source=data_source,
                    simple_fields=simple_fields,
                    include_rebalance_attribution=include_rebalance_attribution,
                    result_html=result_html,
                )
            )
        except Exception as exc:  # noqa: BLE001 - local UI should show user-facing errors.
            error = f"<div class='error'><strong>Error</strong><pre>{escape(str(exc))}</pre></div>"
            self._send_html(
                render_page(
                    yaml_text,
                    prices_csv,
                    fx_csv,
                    input_mode=input_mode,
                    data_source=data_source,
                    simple_fields=simple_fields,
                    include_rebalance_attribution=include_rebalance_attribution,
                    result_html=error,
                )
            )

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_html(self, body: str) -> None:
        encoded = body.encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)
        except (BrokenPipeError, ConnectionResetError):
            return


def run_backtest_html(
    yaml_text: str,
    prices_csv: str,
    fx_csv: str,
    data_source: str = "csv",
    include_rebalance_attribution: bool = True,
) -> str:
    config = load_run_config_text(yaml_text)
    if data_source == "yfinance":
        data = YFinanceProvider().load(config.assets, config.start, config.end)
    else:
        prices = pd.read_csv(StringIO(prices_csv), index_col=0, parse_dates=True)
        fx = pd.read_csv(StringIO(fx_csv), index_col=0, parse_dates=True)
        prices = prices.loc[config.start : config.end]
        fx = fx.loc[config.start : config.end]
        data = MarketData(prices=prices, fx=fx)
    result = BacktestEngine(
        calendar_policy=config.calendar_policy,
        max_staleness_days=config.max_staleness_days,
        include_terminal_rebalance=config.include_terminal_rebalance,
        include_rebalance_attribution=include_rebalance_attribution,
    ).run(config.assets, config.spec, data)

    metric_cards = "".join(
        metric_card(label, result.metrics[label])
        for label in ["total_return", "cagr", "mdd", "volatility", "sharpe"]
        if label in result.metrics
    )
    rebalance_cards = "".join(
        metric_card(label, result.metrics[label])
        for label in [
            "gross_rebalance_effect",
            "implementation_cost_drag",
            "rebalance_trading_cost_drag",
            "net_rebalance_policy_effect",
        ]
        if label in result.metrics
    )
    rebalance_note = (
        ""
        if include_rebalance_attribution
        else "<p class='note'>리밸런싱 vs buy-and-hold 비교는 빠른 실행을 위해 생략했습니다. 폼에서 추가 계산을 켜면 표시됩니다.</p>"
    )
    cumulative_raw = result.attribution["cumulative"]
    total_contribution = float(cumulative_raw.iloc[0].get("total_contribution", float("nan")))
    total_return = float(result.metrics.get("total_return", float("nan")))
    reconciliation_diff = abs(total_contribution - total_return)
    cumulative = cumulative_raw.rename(
        columns={
            "local_contribution": "Local",
            "fx_contribution": "FX",
            "cross_contribution": "Cross",
            "cash_contribution": "Cash",
            "cost_contribution": "Cost",
            "total_contribution": "Total",
        }
    )
    daily_columns = [
        "local_contribution",
        "fx_contribution",
        "cross_contribution",
        "cost_contribution",
        "portfolio_contribution",
    ]
    daily_columns = [column for column in daily_columns if column in result.attribution["daily"]]
    daily_summary = result.attribution["daily"][daily_columns].tail(12)
    diagnostics = result.diagnostics
    warnings_html = "".join(
        f"<div class='warning'>{escape(warning)}</div>"
        for warning in diagnostics.get("fx_warnings", [])
    )
    provider_warnings_html = "".join(
        f"<div class='warning'>{escape(str(warning))}</div>"
        for warning in diagnostics.get("provider_warnings", [])
    )
    data_source_label = "yfinance" if data_source == "yfinance" else "pasted CSV"
    return f"""
    <section class="results">
      <div class="section-title">
        <div>
          <h2>결과</h2>
          <p>원화 기준 성과와 회계 분해를 먼저 보여줍니다. Data source: {escape(data_source_label)}.</p>
        </div>
      </div>
      <div class="metric-grid">{metric_cards}</div>
      {warnings_html}
      {provider_warnings_html}
      <h3>성과 분해</h3>
      {rebalance_note}
      <div class="metric-grid compact">{rebalance_cards}</div>
      <div class="panel-row">
        <section class="subpanel">
          <h3>누적 PnL 기여도</h3>
          <p class="reconcile-note">sum(daily total_pnl) / initial value = final NAV / initial value - 1. 차이: {reconciliation_diff:.2e}</p>
          {frame_to_html(cumulative)}
        </section>
        <section class="subpanel">
          <h3>Data Health</h3>
          <dl class="diagnostics">
            <div><dt>기간</dt><dd>{escape(diagnostics["effective_start"])} - {escape(diagnostics["effective_end"])}</dd></div>
            <div><dt>평가일</dt><dd>{diagnostics["valuation_dates"]}</dd></div>
            <div><dt>리밸런싱</dt><dd>{len(diagnostics["rebalance_dates"])}</dd></div>
            <div><dt>스케줄 리밸런싱</dt><dd>{len(diagnostics.get("scheduled_rebalance_dates", []))}</dd></div>
            <div><dt>가격 staleness</dt><dd>{escape(str(diagnostics["max_price_staleness_by_symbol"]))}</dd></div>
          </dl>
        </section>
      </div>
      <h3>원화 기준 NAV</h3>
      {equity_chart(result.equity_curve["nav"])}
      <details>
        <summary>상세 테이블 보기</summary>
        <h3>NAV 테이블</h3>
        {equity_to_html(result.equity_curve.tail(20))}
        <h3>일별 성과 분해</h3>
        {attribution_to_html(daily_summary)}
      </details>
    </section>
    """


def frame_to_html(frame: pd.DataFrame) -> str:
    return attribution_to_html(frame)


def attribution_to_html(frame: pd.DataFrame) -> str:
    return frame.to_html(classes="data", border=0, float_format=lambda value: f"{value:.2%}")


def equity_to_html(frame: pd.DataFrame) -> str:
    formatters = {
        "nav": lambda value: f"{value:,.0f}",
        "cash": lambda value: f"{value:,.0f}",
        "transaction_cost": lambda value: f"{value:,.0f}",
        "daily_return": lambda value: f"{value:.4%}",
        "risk_daily_return": lambda value: f"{value:.4%}",
        "drawdown": lambda value: f"{value:.4%}",
    }
    return frame.to_html(classes="data", border=0, formatters=formatters)


METRIC_LABELS = {
    "total_return": "Total Return",
    "cagr": "CAGR",
    "mdd": "MDD",
    "volatility": "Volatility",
    "sharpe": "Sharpe",
    "gross_rebalance_effect": "Rebalanced vs Buy-Hold, Before Costs",
    "implementation_cost_drag": "Initial Cost Drag",
    "rebalance_trading_cost_drag": "Rebalance Trading Cost Drag",
    "net_rebalance_policy_effect": "Rebalance Policy Effect vs Buy-Hold",
    "rebalanced_vs_buy_hold_effect": "Rebalanced vs Buy-Hold, After Rebalance Costs",
}


def metric_card(label: str, value: float) -> str:
    display = f"{value:.2f}" if label == "sharpe" else f"{value:.2%}"
    return f"""
    <div class="metric-card">
      <span>{escape(METRIC_LABELS.get(label, label.replace("_", " ").title()))}</span>
      <strong>{escape(display)}</strong>
    </div>
    """


def equity_chart(nav: pd.Series) -> str:
    nav = nav.dropna().astype(float)
    values = nav.tolist()
    if len(values) < 2:
        return ""
    width = 760
    height = 300
    margin_left = 86
    margin_right = 28
    margin_top = 34
    margin_bottom = 54
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    low, high, y_ticks = nice_y_scale(min(values), max(values))
    spread = high - low or 1.0
    points = []
    for index, value in enumerate(values):
        x = margin_left + (index * plot_width / (len(values) - 1))
        y = margin_top + plot_height - ((value - low) / spread * plot_height)
        points.append(f"{x:.2f},{y:.2f}")
    y_tick_html = []
    for value in y_ticks:
        y = margin_top + plot_height - ((value - low) / spread * plot_height)
        y_tick_html.append(
            f"""
            <line class="grid-line" x1="{margin_left}" y1="{y:.2f}" x2="{width - margin_right}" y2="{y:.2f}"/>
            <text class="tick-label" x="{margin_left - 10}" y="{y + 4:.2f}" text-anchor="end">{escape(format_krw_axis(value))}</text>
            """
        )
    x_tick_html = []
    label_tick_html = []
    for index, label, is_major in time_ticks(nav.index):
        x = margin_left + (index * plot_width / (len(values) - 1))
        tick_class = "axis-tick" if is_major else "month-tick"
        x_tick_html.append(
            f"""
            <line class="{tick_class}" x1="{x:.2f}" y1="{margin_top}" x2="{x:.2f}" y2="{margin_top + plot_height + 5}"/>
            """
        )
        if label:
            label_tick_html.append(
                f"""
                <text class="tick-label" x="{x:.2f}" y="{margin_top + plot_height + 24}" text-anchor="middle">{escape(label)}</text>
                """
            )
    start_x, start_y = (float(part) for part in points[0].split(","))
    end_x, end_y = (float(part) for part in points[-1].split(","))
    total_return = (values[-1] / values[0]) - 1.0
    start_label = f"시작 {format_krw_axis(values[0])}"
    end_label = f"종료 {format_krw_axis(values[-1])} ({total_return:+.1%})"
    start_label_x = min(start_x + 12, width - margin_right - 120)
    start_label_y = max(start_y - 12, margin_top + 18)
    end_label_x = max(end_x - 12, margin_left + 130)
    end_label_y = max(end_y - 12, margin_top + 18)
    return f"""
    <div class="chart-wrap">
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="NAV chart with date and KRW axes">
        {''.join(y_tick_html)}
        <line class="axis-line" x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_height}"/>
        <line class="axis-line" x1="{margin_left}" y1="{margin_top + plot_height}" x2="{width - margin_right}" y2="{margin_top + plot_height}"/>
        {''.join(x_tick_html)}
        {''.join(label_tick_html)}
        <polyline points="{' '.join(points)}" fill="none" stroke="#146c5c" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
        <circle cx="{start_x:.2f}" cy="{start_y:.2f}" r="3.2" fill="#146c5c"/>
        <circle cx="{end_x:.2f}" cy="{end_y:.2f}" r="3.2" fill="#146c5c"/>
        <text class="chart-value-label" x="{start_label_x:.2f}" y="{start_label_y:.2f}" text-anchor="start">{escape(start_label)}</text>
        <text class="chart-value-label" x="{end_label_x:.2f}" y="{end_label_y:.2f}" text-anchor="end">{escape(end_label)}</text>
        <text class="axis-title" x="{margin_left}" y="{margin_top - 14}" text-anchor="start">원화 기준 NAV</text>
      </svg>
    </div>
    """


def time_ticks(index: pd.Index) -> list[tuple[int, str, bool]]:
    dates = pd.DatetimeIndex(index)
    if len(dates) < 2:
        return [(0, "", True)]
    duration_days = max((dates[-1] - dates[0]).days, 1)
    month_starts = pd.date_range(dates[0].to_period("M").to_timestamp(), dates[-1], freq="MS")
    minor_indexes = set()
    for month_start in month_starts:
        position = dates.searchsorted(month_start)
        if position < len(dates):
            minor_indexes.add(int(position))
    if duration_days > 365 * 2:
        label_dates = pd.date_range(dates[0].to_period("Y").to_timestamp(), dates[-1], freq="YS")
        label_style = "year"
    elif duration_days > 180:
        label_dates = pd.date_range(dates[0].to_period("Q").start_time, dates[-1], freq="QS")
        label_style = "quarter"
    else:
        label_dates = month_starts
        label_style = "month"
    label_indexes: list[tuple[int, str]] = []
    for label_date in label_dates:
        position = dates.searchsorted(label_date)
        if position < len(dates):
            label_indexes.append((int(position), format_time_tick_label(label_date, label_style)))
    label_indexes = thin_labels(label_indexes, max_labels=6)
    label_index_map = {position: label for position, label in label_indexes}
    all_indexes = sorted(minor_indexes | set(label_index_map))
    return [(position, label_index_map.get(position, ""), position in label_index_map) for position in all_indexes]


def format_time_tick_label(value: pd.Timestamp, style: str) -> str:
    timestamp = pd.Timestamp(value)
    if style == "year":
        return str(timestamp.year)
    if style == "quarter":
        return f"{timestamp.year} Q{timestamp.quarter}"
    return f"{timestamp.month}월"


def thin_labels(labels: list[tuple[int, str]], max_labels: int) -> list[tuple[int, str]]:
    if len(labels) <= max_labels:
        return labels
    step = max(1, round(len(labels) / max_labels))
    thinned = labels[::step]
    if labels[-1] not in thinned:
        thinned.append(labels[-1])
    return thinned[:max_labels]


def nice_y_scale(low: float, high: float) -> tuple[float, float, list[float]]:
    if low == high:
        padding = abs(low) * 0.05 or 1.0
        low -= padding
        high += padding
    else:
        padding = (high - low) * 0.06
        low -= padding
        high += padding
    ticks = [low + (high - low) * index / 4 for index in range(5)]
    return low, high, ticks


def format_krw_axis(value: float) -> str:
    absolute = abs(value)
    if absolute >= 100_000_000:
        return f"{value / 100_000_000:.1f}억"
    if absolute >= 1_000_000:
        return f"{value / 10_000:,.0f}만"
    return f"{value:,.0f}"


def simple_fields_from_form(form: dict[str, list[str]]) -> dict[str, object]:
    return {
        "initial_value": form.get("initial_value", [DEFAULT_SIMPLE_FIELDS["initial_value"]])[0],
        "start": date_from_form(form, "start", str(DEFAULT_SIMPLE_FIELDS["start"])),
        "end": date_from_form(form, "end", str(DEFAULT_SIMPLE_FIELDS["end"])),
        "rebalance": form.get("rebalance", [DEFAULT_SIMPLE_FIELDS["rebalance"]])[0],
        "transaction_cost_bps": form.get(
            "transaction_cost_bps", [DEFAULT_SIMPLE_FIELDS["transaction_cost_bps"]]
        )[0],
        "symbols": padded_values(form.get("symbol", []), 5),
        "names": padded_values(form.get("name", []), 5),
        "currencies": padded_values(form.get("currency", []), 5, default="USD"),
        "weights": padded_values(form.get("weight", []), 5),
    }


def date_from_form(form: dict[str, list[str]], field: str, default: str) -> str:
    year = form.get(f"{field}_year", [""])[0].strip()
    date_value = form.get(f"{field}_date", [""])[0].strip()
    if year and date_value:
        _, month, day = date_parts(date_value)
        return f"{int(year):04d}-{month:02d}-{day:02d}"
    return form.get(field, [default])[0]


def padded_values(values: list[str], length: int, default: str = "") -> list[str]:
    padded = list(values[:length])
    while len(padded) < length:
        padded.append(default)
    return padded


def simple_fields_to_yaml(fields: dict[str, object]) -> str:
    initial_value = parse_number(str(fields["initial_value"]))
    transaction_cost_bps = parse_number(str(fields["transaction_cost_bps"]))
    symbols = fields["symbols"]
    names = fields["names"]
    currencies = fields["currencies"]
    weights = fields["weights"]
    assert isinstance(symbols, list)
    assert isinstance(names, list)
    assert isinstance(currencies, list)
    assert isinstance(weights, list)
    asset_lines = []
    total_weight = 0.0
    for symbol, name, currency, weight_text in zip(symbols, names, currencies, weights):
        symbol = str(symbol).strip()
        if not symbol:
            continue
        weight_percent = parse_number(str(weight_text))
        total_weight += weight_percent
        asset_lines.append(
            "\n".join(
                [
                    f"  - symbol: {symbol}",
                    f"    name: {str(name).strip() or symbol}",
                    f"    currency: {str(currency).strip() or 'USD'}",
                    f"    weight: {weight_percent / 100:.10g}",
                ]
            )
        )
    if not asset_lines:
        raise ValueError("최소 1개 이상의 티커를 입력해야 합니다.")
    if abs(total_weight - 100.0) > 1e-9:
        raise ValueError(f"비중 합계가 100%여야 합니다. 현재 합계: {total_weight:.2f}%")
    return f"""base_currency: KRW
initial_value: {initial_value:.0f}
start: {str(fields["start"]).strip()}
end: {str(fields["end"]).strip()}
calendar:
  policy: union_ffill
  max_staleness_days: 7
rebalance:
  frequency: {str(fields["rebalance"]).strip() or "none"}
  timing: after_close
  transaction_cost_bps: {transaction_cost_bps:g}
assets:
{chr(10).join(asset_lines)}
"""


def parse_number(value: str) -> float:
    try:
        return float(value.replace(",", "").strip())
    except ValueError as exc:
        raise ValueError(f"숫자 입력을 확인하세요: {value}") from exc


def simple_asset_rows(fields: dict[str, object]) -> str:
    symbols = fields["symbols"]
    names = fields["names"]
    currencies = fields["currencies"]
    weights = fields["weights"]
    assert isinstance(symbols, list)
    assert isinstance(names, list)
    assert isinstance(currencies, list)
    assert isinstance(weights, list)
    rows = []
    filled_indexes = [
        index
        for index in range(5)
        if str(symbols[index] if index < len(symbols) else "").strip()
        or str(names[index] if index < len(names) else "").strip()
        or str(weights[index] if index < len(weights) else "").strip()
    ]
    visible_until = min(max(2, max(filled_indexes) if filled_indexes else 2), 4)
    for index in range(5):
        symbol = str(symbols[index] if index < len(symbols) else "")
        name = str(names[index] if index < len(names) else "")
        weight = str(weights[index] if index < len(weights) else "")
        currency = str(currencies[index] if index < len(currencies) else "USD")
        is_empty = not symbol.strip() and not name.strip() and not weight.strip()
        hidden_class = " is-hidden" if is_empty and index > visible_until else ""
        rows.append(
            f"""
            <div class="asset-card{hidden_class}" data-asset-card>
              <div class="asset-card-top">
                <span class="asset-index">자산 {index + 1}</span>
                <label class="ticker-field">
                  <span>티커</span>
                  <input name="symbol" value="{escape(symbol)}" placeholder="예: SPY, 069500.KS" list="ticker-suggestions" autocomplete="off">
                </label>
              </div>
              <div class="asset-fields">
                <label>
                  <span>이름</span>
                  <input name="name" value="{escape(name)}" placeholder="선택 입력">
                </label>
                <label>
                  <span>통화</span>
                  <select name="currency">
                    <option value="KRW" {"selected" if currency == "KRW" else ""}>KRW</option>
                    <option value="USD" {"selected" if currency == "USD" else ""}>USD</option>
                  </select>
                </label>
                <label>
                  <span>비중</span>
                  <span class="weight-input">
                    <input name="weight" value="{escape(weight)}" placeholder="40" inputmode="decimal">
                    <em>%</em>
                  </span>
                </label>
              </div>
            </div>
            """
        )
    return "".join(rows)


def select_option(value: str, label: str, selected_value: str) -> str:
    selected = "selected" if value == selected_value else ""
    return f'<option value="{escape(value)}" {selected}>{escape(label)}</option>'


def year_options(selected_value: str, start_year: int = 1990, end_year: int = 2035) -> str:
    selected_year = date_parts(selected_value)[0]
    return "".join(
        select_option(str(year), str(year), str(selected_year)) for year in range(end_year, start_year - 1, -1)
    )


def month_options(selected_value: str) -> str:
    selected_month = date_parts(selected_value)[1]
    return "".join(select_option(str(month), f"{month:02d}", str(selected_month)) for month in range(1, 13))


def date_parts(value: str) -> tuple[int, int, int]:
    try:
        timestamp = pd.Timestamp(value)
    except ValueError:
        timestamp = pd.Timestamp(DEFAULT_SIMPLE_FIELDS["start"])
    return int(timestamp.year), int(timestamp.month), int(timestamp.day)


def render_page(
    yaml_text: str = SAMPLE_YAML,
    prices_csv: str = SAMPLE_PRICES,
    fx_csv: str = SAMPLE_FX,
    input_mode: str = "simple",
    data_source: str = "yfinance",
    simple_fields: dict[str, object] | None = None,
    include_rebalance_attribution: bool = False,
    result_html: str = "",
) -> str:
    simple_fields = simple_fields or DEFAULT_SIMPLE_FIELDS
    simple_checked = "checked" if input_mode != "yaml" else ""
    yaml_checked = "checked" if input_mode == "yaml" else ""
    csv_checked = "checked" if data_source == "csv" else ""
    yfinance_checked = "checked" if data_source == "yfinance" else ""
    rebalance_attribution_checked = "checked" if include_rebalance_attribution else ""
    simple_assets_html = simple_asset_rows(simple_fields)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>krwfolio</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f5f6f8;
      --panel: #ffffff;
      --text: #1f2933;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #146c5c;
      --accent-soft: #e5f2ee;
      --danger: #9f1d35;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    header {{
      padding: 22px 28px 16px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }}
    h1, h2, h3 {{ margin: 0 0 12px; letter-spacing: 0; }}
    h1 {{ font-size: 26px; }}
    h2 {{ font-size: 20px; }}
    h3 {{ font-size: 15px; color: var(--muted); }}
    p {{ max-width: 920px; margin: 0; color: var(--muted); }}
    main {{ padding: 18px 28px 36px; }}
    form, .results, .error {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 20px;
    }}
    .grid {{
      display: grid;
      gap: 16px;
    }}
    .two {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .editor-grid {{
      grid-template-columns: minmax(260px, 0.9fr) minmax(300px, 1.1fr);
      align-items: start;
    }}
    .csv-grid {{
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }}
    .input-grid {{
      grid-template-columns: minmax(140px, 0.8fr) repeat(2, minmax(220px, 1.2fr)) minmax(120px, 0.8fr) minmax(120px, 0.8fr);
      align-items: end;
    }}
    .date-controls {{
      display: grid;
      grid-template-columns: minmax(86px, 0.7fr) minmax(150px, 1.3fr);
      gap: 6px;
    }}
    .date-controls input,
    .date-controls select {{
      min-width: 0;
    }}
    .assets-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin: 18px 0 10px;
    }}
    .assets-head h3 {{ margin: 0; }}
    .asset-list {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      align-items: start;
    }}
    .asset-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
      padding: 12px;
    }}
    .asset-card.is-hidden {{ display: none; }}
    .asset-card-top {{
      display: grid;
      grid-template-columns: 64px minmax(0, 1fr);
      gap: 10px;
      align-items: end;
      margin-bottom: 10px;
    }}
    .asset-index {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 42px;
      border-radius: 6px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 12px;
      font-weight: 800;
    }}
    .asset-fields {{
      display: grid;
      grid-template-columns: minmax(160px, 1fr) 96px 110px;
      gap: 10px;
      align-items: end;
    }}
    .asset-card label {{
      margin: 0;
      min-width: 0;
    }}
    .asset-card label > span:first-child {{
      display: block;
      margin-bottom: 5px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }}
    .ticker-field input {{
      min-height: 42px;
      font-size: 17px;
      font-weight: 800;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    .weight-input {{
      position: relative;
      display: block;
    }}
    .weight-input input {{ padding-right: 30px; }}
    .weight-input em {{
      position: absolute;
      right: 11px;
      top: 50%;
      transform: translateY(-50%);
      color: var(--muted);
      font-style: normal;
      font-weight: 700;
      pointer-events: none;
    }}
    label {{
      display: block;
      font-weight: 700;
      margin-bottom: 8px;
    }}
    input:not([type="radio"]):not([type="checkbox"]), select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      font: inherit;
      background: #fbfcfe;
    }}
    input[type="radio"], input[type="checkbox"] {{
      width: auto;
      flex: 0 0 auto;
      accent-color: var(--accent);
    }}
    .field-help {{
      color: var(--muted);
      font-size: 12px;
      margin-top: -4px;
    }}
    .source-warning, .reconcile-note {{
      margin: 0 0 14px;
      border: 1px solid #f0d58c;
      border-radius: 8px;
      background: #fff9e8;
      color: #694c00;
      padding: 10px 12px;
      font-size: 13px;
    }}
    .reconcile-note {{
      margin-top: -4px;
      background: #fbfcfe;
      border-color: var(--line);
      color: var(--muted);
    }}
    .csv-example {{
      margin: 10px 0 14px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfe;
      padding: 10px 12px;
      color: var(--muted);
      font: 12px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      white-space: pre-wrap;
    }}
    textarea {{
      width: 100%;
      min-height: 170px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 12px;
      font: 13px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      background: #fbfcfe;
    }}
    #yaml {{ min-height: 390px; }}
    button {{
      margin-top: 16px;
      border: 0;
      border-radius: 6px;
      background: var(--accent);
      color: white;
      font-weight: 700;
      padding: 10px 16px;
      cursor: pointer;
    }}
    button:disabled {{
      cursor: wait;
      opacity: 0.72;
    }}
    .secondary-button {{
      margin: 0;
      border: 1px solid var(--line);
      background: #ffffff;
      color: var(--accent);
      padding: 8px 11px;
      font-size: 13px;
    }}
    .source-picker {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin: 0 0 16px;
      border: 0;
      padding: 0;
    }}
    .source-option {{
      display: flex;
      gap: 9px;
      align-items: flex-start;
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 11px 12px;
      background: #fbfcfe;
      font-weight: 600;
    }}
    .source-option input {{ margin-top: 3px; }}
    .source-option strong {{ display: block; min-width: 0; }}
    .source-option span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 400;
      margin-top: 2px;
    }}
    .option-row {{
      display: flex;
      align-items: flex-start;
      gap: 9px;
      margin: 0 0 16px;
      color: var(--muted);
      font-size: 13px;
    }}
    .option-row input {{ margin-top: 3px; }}
    .mode-picker {{
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      margin: 0 0 16px;
      color: var(--muted);
      font-size: 13px;
    }}
    .mode-picker label {{
      display: inline-flex;
      gap: 7px;
      align-items: center;
      margin: 0;
      font-weight: 600;
    }}
    .simple-panel {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: #fbfcfe;
      margin-bottom: 16px;
    }}
    .advanced-panel {{
      border-top: 1px solid var(--line);
      padding-top: 14px;
      margin-top: 14px;
    }}
    .note {{
      margin: -4px 0 14px;
      color: var(--muted);
      font-size: 13px;
    }}
    .results {{ margin-top: 20px; overflow: hidden; }}
    .section-title {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 14px;
    }}
    .metric-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
      gap: 10px;
      margin-bottom: 18px;
    }}
    .metric-grid.compact {{
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    }}
    .metric-card {{
      min-width: 0;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfe;
    }}
    .metric-card span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }}
    .metric-card strong {{
      display: block;
      font-size: 20px;
      overflow-wrap: anywhere;
    }}
    .panel-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(220px, 0.8fr);
      gap: 14px;
      margin-bottom: 18px;
    }}
    .subpanel {{
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      background: #fbfcfe;
    }}
    .chart-wrap {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
      padding: 12px;
      margin-bottom: 16px;
    }}
    .chart-wrap svg {{ display: block; width: 100%; height: auto; }}
    .grid-line {{ stroke: #e6ebf1; stroke-width: 1; }}
    .month-tick {{ stroke: #eef2f6; stroke-width: 0.8; }}
    .axis-line, .axis-tick {{ stroke: #9aa4b2; stroke-width: 1; }}
    .tick-label {{ fill: #667085; font-size: 12px; }}
    .axis-title {{ fill: #3b4652; font-size: 12px; font-weight: 700; }}
    .chart-value-label {{ fill: #146c5c; font-size: 12px; font-weight: 700; }}
    .diagnostics {{
      display: grid;
      gap: 10px;
      margin: 0;
      font-size: 13px;
    }}
    .diagnostics div {{
      min-width: 0;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--line);
    }}
    .diagnostics dt {{ color: var(--muted); font-weight: 700; }}
    .diagnostics dd {{ margin: 2px 0 0; overflow-wrap: anywhere; }}
    details {{
      border-top: 1px solid var(--line);
      padding-top: 12px;
    }}
    summary {{
      cursor: pointer;
      font-weight: 700;
      color: var(--accent);
      margin-bottom: 12px;
    }}
    .error {{ margin-top: 20px; border-color: #ef9a9a; color: var(--danger); }}
    .warning {{
      margin: 0 0 14px;
      border: 1px solid #ef9a9a;
      border-radius: 8px;
      background: #fff5f5;
      color: var(--danger);
      padding: 10px 12px;
      font-size: 13px;
    }}
    table {{
      width: 100%;
      table-layout: fixed;
      border-collapse: collapse;
      margin-bottom: 20px;
      font-size: 12px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 7px 8px;
      text-align: right;
      white-space: normal;
      overflow-wrap: anywhere;
    }}
    th:first-child, td:first-child {{ text-align: left; }}
    @media (max-width: 900px) {{
      header, main {{ padding-left: 16px; padding-right: 16px; }}
      .two, .editor-grid, .csv-grid, .panel-row, .source-picker, .input-grid, .asset-list, .asset-card-top, .asset-fields {{ grid-template-columns: 1fr; }}
      .asset-index {{ justify-content: flex-start; min-height: auto; padding: 7px 9px; }}
      #yaml {{ min-height: 280px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>krwfolio</h1>
    <p>원화 기준 다통화 포트폴리오 성과를 자산 수익, 환율 효과, 교차항, 리밸런싱, 비용으로 분해합니다.</p>
  </header>
  <main>
    <form method="post">
      <div class="mode-picker" aria-label="Input mode">
        <label><input type="radio" name="input_mode" value="simple" {simple_checked}> 간편 입력</label>
        <label><input type="radio" name="input_mode" value="yaml" {yaml_checked}> YAML 직접 입력</label>
      </div>
      <fieldset class="source-picker" aria-label="Data source">
        <label class="source-option">
          <input type="radio" name="data_source" value="yfinance" {yfinance_checked}>
          <strong>yfinance에서 가져오기<span>빠른 체험용입니다. 재현성과 데이터 정확성을 보장하지 않습니다.</span></strong>
        </label>
        <label class="source-option" data-source-option="csv">
          <input type="radio" name="data_source" value="csv" {csv_checked}>
          <strong>CSV 직접 입력<span>분석, 공유, 테스트에 권장되는 재현 가능한 입력입니다.</span></strong>
        </label>
      </fieldset>
      <p class="source-warning">yfinance 결과는 나중에 달라질 수 있습니다. 중요한 분석은 가격/환율 CSV snapshot을 저장한 뒤 CSV 입력으로 다시 실행하세요.</p>
      <section class="simple-panel" id="simple-panel">
        <div class="grid input-grid">
          <div>
            <label for="initial_value">초기 금액</label>
            <input id="initial_value" name="initial_value" value="{escape(str(simple_fields["initial_value"]))}" inputmode="numeric">
          </div>
          <div class="date-field">
            <label for="start">시작일</label>
            <input id="start" name="start" type="hidden" value="{escape(str(simple_fields["start"]))}">
            <div class="date-controls" data-date-group="start">
              <select name="start_year" aria-label="시작 연도" data-date-part="year">
                {year_options(str(simple_fields["start"]))}
              </select>
              <input name="start_date" aria-label="시작 월일" type="date" value="{escape(str(simple_fields["start"]))}" data-date-part="date">
            </div>
          </div>
          <div class="date-field">
            <label for="end">종료일</label>
            <input id="end" name="end" type="hidden" value="{escape(str(simple_fields["end"]))}">
            <div class="date-controls" data-date-group="end">
              <select name="end_year" aria-label="종료 연도" data-date-part="year">
                {year_options(str(simple_fields["end"]))}
              </select>
              <input name="end_date" aria-label="종료 월일" type="date" value="{escape(str(simple_fields["end"]))}" data-date-part="date">
            </div>
          </div>
          <div>
            <label for="rebalance">리밸런싱</label>
            <select id="rebalance" name="rebalance">
              {select_option("none", "없음", str(simple_fields["rebalance"]))}
              {select_option("monthly", "월간", str(simple_fields["rebalance"]))}
              {select_option("quarterly", "분기", str(simple_fields["rebalance"]))}
              {select_option("yearly", "연간", str(simple_fields["rebalance"]))}
            </select>
          </div>
          <div>
            <label for="transaction_cost_bps">거래비용 bps</label>
            <input id="transaction_cost_bps" name="transaction_cost_bps" value="{escape(str(simple_fields["transaction_cost_bps"]))}" inputmode="decimal">
          </div>
        </div>
        <p class="field-help">초기 금액은 10,000,000처럼 콤마를 써도 됩니다. 비중은 % 단위이며 합계가 100이어야 합니다. Name은 선택 입력입니다.</p>
        <div class="assets-head">
          <h3>자산</h3>
          <button class="secondary-button" type="button" id="add-asset-button">자산 추가</button>
        </div>
        <datalist id="ticker-suggestions">
          <option value="069500.KS">
          <option value="SPY">
          <option value="QQQ">
          <option value="TLT">
          <option value="GLD">
        </datalist>
        <div class="asset-list">
          {simple_assets_html}
        </div>
      </section>
      <label class="option-row">
        <input type="checkbox" name="include_rebalance_attribution" {rebalance_attribution_checked}>
        <span>리밸런싱 vs buy-and-hold 비교 계산 포함. 일별 yfinance 데이터에서는 몇 초 더 걸릴 수 있습니다.</span>
      </label>
      <details class="advanced-panel" {"open" if input_mode == "yaml" or data_source == "csv" else ""}>
        <summary>YAML / CSV 고급 입력</summary>
        <p class="field-help">YAML은 포트폴리오 규칙을 파일처럼 남기고 싶을 때 씁니다. 가격 CSV는 각 티커의 현지통화 가격 스냅샷이고, FX CSV는 USD/KRW 같은 환율 스냅샷입니다. FX는 foreign exchange, 즉 외화 가격을 KRW로 환산하기 위한 값입니다.</p>
        <pre class="csv-example">가격 CSV 예시
date,SPY,TLT,069500.KS
2024-01-02,470.2,96.1,38200

FX CSV 예시
date,USD
2024-01-02,1310.5</pre>
      <div class="grid editor-grid" id="advanced-grid">
        <div>
          <label for="yaml">Portfolio YAML</label>
          <textarea id="yaml" name="yaml">{escape(yaml_text)}</textarea>
        </div>
        <div class="grid csv-grid">
          <div>
            <label for="prices">Prices CSV</label>
            <textarea id="prices" name="prices">{escape(prices_csv)}</textarea>
          </div>
          <div>
            <label for="fx">FX CSV</label>
            <textarea id="fx" name="fx">{escape(fx_csv)}</textarea>
          </div>
        </div>
      </div>
      </details>
      <button id="run-button" type="submit">원화 기준 성과 분석 실행</button>
    </form>
    {result_html}
  </main>
  <script>
    const form = document.querySelector("form");
    const runButton = document.querySelector("#run-button");
    const initialValue = document.querySelector("#initial_value");
    const simplePanel = document.querySelector("#simple-panel");
    const advancedPanel = document.querySelector(".advanced-panel");
    const csvOption = document.querySelector("[data-source-option='csv']");
    const addAssetButton = document.querySelector("#add-asset-button");
    const assetCards = Array.from(document.querySelectorAll("[data-asset-card]"));
    const dateGroups = Array.from(document.querySelectorAll("[data-date-group]"));
    const modeRadios = document.querySelectorAll("input[name='input_mode']");
    const sourceRadios = document.querySelectorAll("input[name='data_source']");

    function formatCommaNumber(value) {{
      const cleaned = value.replace(/,/g, "").replace(/[^0-9.]/g, "");
      if (!cleaned) return "";
      const parts = cleaned.split(".");
      parts[0] = parts[0].replace(/\\B(?=(\\d{{3}})+(?!\\d))/g, ",");
      return parts.length > 1 ? `${{parts[0]}}.${{parts.slice(1).join("")}}` : parts[0];
    }}

    function syncMode() {{
      const mode = document.querySelector("input[name='input_mode']:checked").value;
      const source = document.querySelector("input[name='data_source']:checked").value;
      simplePanel.style.display = mode === "simple" ? "block" : "none";
      if (mode === "simple" && source === "yfinance") {{
        advancedPanel.open = false;
      }}
      csvOption.style.opacity = mode === "simple" ? "0.75" : "1";
    }}

    function syncAssetButton() {{
      const hiddenCards = assetCards.filter((card) => card.classList.contains("is-hidden"));
      addAssetButton.disabled = hiddenCards.length === 0;
      addAssetButton.textContent = hiddenCards.length === 0 ? "자산 슬롯 없음" : "자산 추가";
    }}

    function syncDateGroup(group, changedControl = null) {{
      const field = group.dataset.dateGroup;
      const yearSelect = group.querySelector("[data-date-part='year']");
      const dateInput = group.querySelector("[data-date-part='date']");
      if (!dateInput.value) return;
      const parts = dateInput.value.split("-");
      if (parts.length !== 3) return;
      if (changedControl === dateInput && yearSelect.value !== parts[0]) {{
        yearSelect.value = parts[0];
      }}
      if (changedControl === yearSelect && parts[0] !== yearSelect.value) {{
        parts[0] = yearSelect.value;
        dateInput.value = parts.join("-");
      }}
      document.querySelector(`#${{field}}`).value = `${{yearSelect.value}}-${{parts[1]}}-${{parts[2]}}`;
    }}

    initialValue.addEventListener("input", () => {{
      const cursor = initialValue.selectionStart;
      initialValue.value = formatCommaNumber(initialValue.value);
      initialValue.setSelectionRange(initialValue.value.length, initialValue.value.length);
    }});
    addAssetButton.addEventListener("click", () => {{
      const nextCard = assetCards.find((card) => card.classList.contains("is-hidden"));
      if (!nextCard) return;
      nextCard.classList.remove("is-hidden");
      const tickerInput = nextCard.querySelector("input[name='symbol']");
      if (tickerInput) tickerInput.focus();
      syncAssetButton();
    }});
    dateGroups.forEach((group) => {{
      group.querySelectorAll("select, input").forEach((control) => {{
        control.addEventListener("change", () => syncDateGroup(group, control));
        control.addEventListener("input", () => syncDateGroup(group, control));
      }});
      syncDateGroup(group);
    }});
    modeRadios.forEach((radio) => radio.addEventListener("change", syncMode));
    sourceRadios.forEach((radio) => radio.addEventListener("change", syncMode));
    syncMode();
    syncAssetButton();

    form.addEventListener("submit", () => {{
      dateGroups.forEach(syncDateGroup);
      const source = document.querySelector("input[name='data_source']:checked");
      runButton.disabled = true;
      runButton.textContent = source && source.value === "yfinance"
        ? "yfinance 데이터 가져오는 중..."
        : "성과 분석 중...";
    }});
  </script>
</body>
</html>"""
