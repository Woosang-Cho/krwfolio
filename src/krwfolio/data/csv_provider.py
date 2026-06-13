from pathlib import Path

import pandas as pd

from krwfolio.assets import Asset
from krwfolio.exceptions import DataError
from krwfolio.portfolio import MarketData


class CSVProvider:
    def __init__(self, price_csv: str | Path, fx_csv: str | Path):
        self.price_csv = Path(price_csv)
        self.fx_csv = Path(fx_csv)

    def load(self, assets: list[Asset], start: str, end: str) -> MarketData:
        prices = pd.read_csv(self.price_csv, index_col=0, parse_dates=True)
        fx = pd.read_csv(self.fx_csv, index_col=0, parse_dates=True)
        symbols = [asset.symbol for asset in assets]
        missing_prices = sorted(set(symbols) - set(prices.columns))
        if missing_prices:
            raise DataError(f"Missing price columns in CSV: {missing_prices}")
        missing_fx = sorted({asset.currency for asset in assets} - set(fx.columns) - {"KRW"})
        if missing_fx:
            raise DataError(f"Missing FX columns in CSV for currencies: {missing_fx}")
        prices = prices.loc[start:end, symbols]
        fx = fx.loc[start:end]
        if "KRW" not in fx.columns:
            fx["KRW"] = 1.0
        return MarketData(
            prices=prices,
            fx=fx,
            metadata={
                "provider": "csv",
                "price_csv": str(self.price_csv),
                "fx_csv": str(self.fx_csv),
            },
        )
