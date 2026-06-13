import pytest

from krwfolio.assets import Asset
from krwfolio.data.csv_provider import CSVProvider
from krwfolio.exceptions import DataError


def test_csv_provider_rejects_missing_price_columns(tmp_path):
    prices = tmp_path / "prices.csv"
    fx = tmp_path / "fx.csv"
    prices.write_text("date,SPY\n2024-01-02,100\n")
    fx.write_text("date,USD\n2024-01-02,1300\n")
    assets = [
        Asset(symbol="SPY", name="SPY", currency="USD"),
        Asset(symbol="TLT", name="TLT", currency="USD"),
    ]

    with pytest.raises(DataError, match="Missing price columns in CSV: \\['TLT'\\]"):
        CSVProvider(prices, fx).load(assets, "2024-01-02", "2024-01-03")


def test_csv_provider_rejects_missing_fx_columns(tmp_path):
    prices = tmp_path / "prices.csv"
    fx = tmp_path / "fx.csv"
    prices.write_text("date,SPY\n2024-01-02,100\n")
    fx.write_text("date,KRW\n2024-01-02,1\n")
    assets = [Asset(symbol="SPY", name="SPY", currency="USD")]

    with pytest.raises(DataError, match="Missing FX columns in CSV for currencies: \\['USD'\\]"):
        CSVProvider(prices, fx).load(assets, "2024-01-02", "2024-01-03")
