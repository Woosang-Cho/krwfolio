import pandas as pd

from krwfolio.assets import Asset
from krwfolio.exceptions import DataError, ValidationError


def validate_asset_currencies(assets: list[Asset]) -> None:
    unsupported = sorted({asset.currency for asset in assets} - {"KRW", "USD"})
    if unsupported:
        raise ValidationError(f"MVP supports KRW and USD assets only: {unsupported}")


def asset_fx_frame(assets: list[Asset], fx: pd.DataFrame) -> pd.DataFrame:
    missing = sorted({asset.currency for asset in assets if asset.currency not in fx.columns})
    if missing:
        raise DataError(f"Missing FX columns for currencies: {missing}")
    return pd.DataFrame({asset.symbol: fx[asset.currency] for asset in assets}, index=fx.index)


def base_returns(local_returns: pd.DataFrame, fx_returns: pd.DataFrame) -> pd.DataFrame:
    return (1.0 + local_returns) * (1.0 + fx_returns) - 1.0

