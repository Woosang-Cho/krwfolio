from __future__ import annotations

import argparse
import sys
from pathlib import Path

from krwfolio.core.engine import BacktestEngine
from krwfolio.data.csv_provider import CSVProvider
from krwfolio.data.yfinance_provider import YFinanceProvider
from krwfolio.io.exporters import export_result
from krwfolio.io.spec_loader import load_run_config
from krwfolio.web import run_web_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="krwfolio")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="Run a backtest from a YAML spec.")
    run_parser.add_argument("spec")
    run_parser.add_argument("--out", required=True)
    run_parser.add_argument("--format", default="csv,json")
    run_parser.add_argument(
        "--provider",
        choices=["csv", "yfinance"],
        default="csv",
        help="Market data source. csv uses paths in YAML; yfinance downloads by symbol.",
    )
    web_parser = subparsers.add_parser("web", help="Start the local web UI.")
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args(argv)

    if args.command == "run":
        config = load_run_config(args.spec)
        if args.provider == "yfinance":
            provider = YFinanceProvider()
        else:
            if not config.price_csv or not config.fx_csv:
                raise SystemExit("YAML must include data.prices and data.fx CSV paths for CSV mode.")
            provider = CSVProvider(config.price_csv, config.fx_csv)
        data = provider.load(config.assets, config.start, config.end)
        result = BacktestEngine(
            calendar_policy=config.calendar_policy,
            max_staleness_days=config.max_staleness_days,
            include_terminal_rebalance=config.include_terminal_rebalance,
        ).run(config.assets, config.spec, data)
        export_result(result, args.out, set(args.format.split(",")))
        if args.provider == "yfinance":
            out_dir = Path(args.out)
            out_dir.mkdir(parents=True, exist_ok=True)
            data.prices.to_csv(out_dir / "market_prices_yfinance.csv")
            data.fx.to_csv(out_dir / "market_fx_yfinance.csv")
        print(f"Total return: {result.metrics['total_return']:.2%}")
        print(f"CAGR: {result.metrics['cagr']:.2%}")
        print(f"MDD: {result.metrics['mdd']:.2%}")
        print(f"Local contribution: {result.attribution['cumulative'].iloc[0]['local_contribution']:.2%}")
        print(f"FX contribution: {result.attribution['cumulative'].iloc[0]['fx_contribution']:.2%}")
        print(f"Cross contribution: {result.attribution['cumulative'].iloc[0]['cross_contribution']:.2%}")
        print(f"Cost contribution: {result.attribution['cumulative'].iloc[0]['cost_contribution']:.2%}")
        print(f"Executed rebalances: {len(result.diagnostics['executed_rebalance_dates'])}")
        print(f"Annualization periods/year: {result.metrics['annualization_periods_per_year']:.0f}")
        for warning in result.diagnostics.get("fx_warnings", []):
            print(f"WARNING: {warning}", file=sys.stderr)
        for warning in result.diagnostics.get("provider_warnings", []):
            print(f"WARNING: {warning}", file=sys.stderr)
    elif args.command == "web":
        run_web_server(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
