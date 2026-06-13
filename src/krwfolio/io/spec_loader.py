from pathlib import Path
from typing import Any

import yaml

from krwfolio.assets import Asset
from krwfolio.config import RunConfig
from krwfolio.exceptions import ValidationError
from krwfolio.portfolio import PortfolioSpec


def load_run_config(path: str | Path) -> RunConfig:
    config_path = Path(path)
    raw = yaml.safe_load(config_path.read_text()) or {}
    return parse_run_config(raw, base_dir=config_path.parent)


def load_run_config_text(text: str) -> RunConfig:
    raw = yaml.safe_load(text) or {}
    return parse_run_config(raw)


def parse_run_config(raw: dict[str, Any], base_dir: Path | None = None) -> RunConfig:
    if not isinstance(raw, dict):
        raise ValidationError("YAML root must be a mapping/object.")
    allowed = {
        "base_currency",
        "initial_value",
        "start",
        "end",
        "rebalance",
        "calendar",
        "data",
        "assets",
        "fx",
    }
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValidationError(f"Unknown YAML keys: {unknown}")

    assets_raw = _required(raw, "assets")
    if not isinstance(assets_raw, list) or not assets_raw:
        raise ValidationError("assets must be a non-empty list.")
    rebalance = _mapping(raw.get("rebalance", {}), "rebalance")
    calendar = _mapping(raw.get("calendar", {}), "calendar")
    data = _mapping(raw.get("data", {}), "data")

    _validate_keys(
        rebalance,
        {
            "frequency",
            "timing",
            "transaction_cost_bps",
            "include_terminal_rebalance",
        },
        "rebalance",
    )
    _validate_keys(calendar, {"policy", "max_staleness_days"}, "calendar")
    _validate_keys(data, {"prices", "fx"}, "data")

    for item in assets_raw:
        if not isinstance(item, dict):
            raise ValidationError("assets entries must be mappings/objects.")
    assets = [
        _asset_from_dict(item)
        for item in assets_raw
    ]
    weights = {
        str(_required(item, "symbol", "asset")): _float(_required(item, "weight", "asset"), "asset.weight")
        for item in assets_raw
    }
    timing = rebalance.get("timing", "after_close")
    if timing != "after_close":
        raise ValidationError("MVP supports rebalance.timing='after_close' only.")
    if calendar.get("policy", "union_ffill") != "union_ffill":
        raise ValidationError("MVP supports calendar.policy='union_ffill' only.")
    include_terminal_rebalance = _bool(
        rebalance.get("include_terminal_rebalance", False),
        "rebalance.include_terminal_rebalance",
    )
    spec = PortfolioSpec(
        base_currency=raw.get("base_currency", "KRW"),
        initial_value=_float(_required(raw, "initial_value"), "initial_value"),
        weights=weights,
        rebalance=rebalance.get("frequency", "none"),
        transaction_cost_bps=_float(
            rebalance.get("transaction_cost_bps", 0.0), "rebalance.transaction_cost_bps"
        ),
    )
    return RunConfig(
        assets=assets,
        spec=spec,
        start=str(_required(raw, "start")),
        end=str(_required(raw, "end")),
        price_csv=_resolve_path(data.get("prices"), base_dir),
        fx_csv=_resolve_path(data.get("fx"), base_dir),
        calendar_policy=calendar.get("policy", "union_ffill"),
        max_staleness_days=_int(calendar.get("max_staleness_days", 7), "calendar.max_staleness_days"),
        rebalance_timing=timing,
        include_terminal_rebalance=include_terminal_rebalance,
    )


def _asset_from_dict(item: dict[str, Any]) -> Asset:
    if not isinstance(item, dict):
        raise ValidationError("assets entries must be mappings/objects.")
    _validate_keys(
        item,
        {"symbol", "name", "currency", "asset_class", "source", "weight"},
        f"asset {item.get('symbol', '<unknown>')}",
    )
    return Asset(
        symbol=str(_required(item, "symbol", "asset")),
        name=item.get("name"),
        currency=_currency(_required(item, "currency", "asset"), "asset.currency"),
        asset_class=item.get("asset_class"),
        source=item.get("source", "csv"),
    )


def _validate_keys(section: dict[str, Any], allowed: set[str], name: str) -> None:
    if not isinstance(section, dict):
        raise ValidationError(f"{name} must be a mapping/object.")
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ValidationError(f"Unknown {name} keys: {unknown}")


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValidationError(f"{name} must be a mapping/object.")
    return value


def _required(section: dict[str, Any], key: str, prefix: str | None = None) -> Any:
    if key not in section:
        path = f"{prefix}.{key}" if prefix else key
        raise ValidationError(f"Missing required YAML field: {path}")
    return section[key]


def _float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"{name} must be a number.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be a number.") from exc


def _int(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{name} must be an integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name} must be an integer.") from exc


def _bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{name} must be boolean.")
    return value


def _currency(value: Any, name: str) -> str:
    if value not in {"KRW", "USD"}:
        raise ValidationError(f"{name} must be KRW or USD.")
    return value


def _resolve_path(value: str | None, base_dir: Path | None) -> str | None:
    if value is None:
        return None
    path = Path(value)
    if path.is_absolute() or base_dir is None:
        return str(path)
    return str(base_dir / path)
