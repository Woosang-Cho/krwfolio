from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from krwfolio.portfolio import BacktestResult


def export_result(result: BacktestResult, out_dir: str | Path, formats: set[str]) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if "csv" in formats:
        result.equity_curve.to_csv(out / "equity_curve.csv")
        result.holdings.to_csv(out / "holdings.csv")
        result.weights.to_csv(out / "weights.csv")
        result.trades.to_csv(out / "trades.csv")
        for name, frame in result.attribution.items():
            frame.to_csv(out / f"attribution_{name}.csv", index=name == "daily")
    if "json" in formats:
        payload = {
            "schema_version": result.schema_version,
            "metrics": result.metrics,
            "diagnostics": result.diagnostics,
            "attribution": {
                name: _json_records(frame, include_index=name == "daily")
                for name, frame in result.attribution.items()
            },
        }
        (out / "result.json").write_text(json.dumps(payload, indent=2, default=str))


def _json_records(frame: pd.DataFrame, include_index: bool) -> list[dict[str, object]]:
    if include_index:
        return frame.reset_index().to_dict(orient="records")
    return frame.to_dict(orient="records")
