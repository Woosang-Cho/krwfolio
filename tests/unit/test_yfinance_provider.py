import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from krwfolio.assets import Asset
from krwfolio.data.yfinance_provider import YFinanceProvider
from krwfolio.exceptions import DataError


def test_yfinance_provider_batches_downloads_and_sets_timeout(monkeypatch):
    calls = []

    def fake_download(**kwargs):
        calls.append(kwargs)
        dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
        tickers = kwargs["tickers"]
        if tickers == ["SPY", "TLT"]:
            columns = pd.MultiIndex.from_product([["Close"], tickers])
            return pd.DataFrame([[100.0, 90.0], [101.0, 91.0]], index=dates, columns=columns)
        if tickers == ["KRW=X"]:
            columns = pd.MultiIndex.from_product([["Close"], tickers])
            return pd.DataFrame([[1300.0], [1310.0]], index=dates, columns=columns)
        raise AssertionError(f"unexpected tickers: {tickers}")

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))
    assets = [
        Asset(symbol="SPY", name="SPY", currency="USD", asset_class=None),
        Asset(symbol="TLT", name="TLT", currency="USD", asset_class=None),
    ]

    data = YFinanceProvider().load(assets, "2024-01-02", "2024-01-03")

    assert list(data.prices.columns) == ["SPY", "TLT"]
    assert list(data.fx.columns) == ["KRW", "USD"]
    assert data.prices.loc[pd.Timestamp("2024-01-03"), "SPY"] == 101.0
    assert data.fx.loc[pd.Timestamp("2024-01-03"), "USD"] == 1310.0
    assert len(calls) == 2
    assert all(call["threads"] is False for call in calls)
    assert all(call["timeout"] == 10 for call in calls)
    assert calls[0]["end"] == "2024-01-04"
    assert data.metadata["provider"] == "yfinance"
    assert data.metadata["auto_adjust"] is True
    assert data.metadata["threads"] is False


def test_yfinance_provider_rejects_missing_price_ticker(monkeypatch):
    def fake_download(**kwargs):
        dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
        tickers = kwargs["tickers"]
        if tickers == ["SPY", "TLT"]:
            columns = pd.MultiIndex.from_product([["Close"], ["SPY"]])
            return pd.DataFrame([[100.0], [101.0]], index=dates, columns=columns)
        if tickers == ["KRW=X"]:
            columns = pd.MultiIndex.from_product([["Close"], tickers])
            return pd.DataFrame([[1300.0], [1310.0]], index=dates, columns=columns)
        raise AssertionError(f"unexpected tickers: {tickers}")

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))
    assets = [
        Asset(symbol="SPY", name="SPY", currency="USD", asset_class=None),
        Asset(symbol="TLT", name="TLT", currency="USD", asset_class=None),
    ]

    with pytest.raises(DataError, match="Missing yfinance Close column for TLT"):
        YFinanceProvider().load(assets, "2024-01-02", "2024-01-03")


def test_yfinance_provider_reads_symbol_first_multiindex(monkeypatch):
    def fake_download(**kwargs):
        dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
        tickers = kwargs["tickers"]
        if tickers == ["SPY", "TLT"]:
            columns = pd.MultiIndex.from_tuples(
                [("SPY", "Close"), ("SPY", "Open"), ("TLT", "Close"), ("TLT", "Open")]
            )
            return pd.DataFrame(
                [[100.0, 99.0, 90.0, 89.0], [101.0, 100.0, 91.0, 90.0]],
                index=dates,
                columns=columns,
            )
        if tickers == ["KRW=X"]:
            columns = pd.MultiIndex.from_tuples([("KRW=X", "Close"), ("KRW=X", "Open")])
            return pd.DataFrame([[1300.0, 1299.0], [1310.0, 1309.0]], index=dates, columns=columns)
        raise AssertionError(f"unexpected tickers: {tickers}")

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))
    assets = [
        Asset(symbol="SPY", name="SPY", currency="USD", asset_class=None),
        Asset(symbol="TLT", name="TLT", currency="USD", asset_class=None),
    ]

    data = YFinanceProvider().load(assets, "2024-01-02", "2024-01-03")

    assert data.prices.loc[pd.Timestamp("2024-01-03"), "TLT"] == 91.0
    assert data.fx.loc[pd.Timestamp("2024-01-03"), "USD"] == 1310.0


def test_yfinance_provider_rejects_missing_fx_ticker(monkeypatch):
    def fake_download(**kwargs):
        dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
        tickers = kwargs["tickers"]
        if tickers == ["SPY"]:
            columns = pd.MultiIndex.from_product([["Close"], tickers])
            return pd.DataFrame([[100.0], [101.0]], index=dates, columns=columns)
        if tickers == ["KRW=X", "EURKRW=X"]:
            columns = pd.MultiIndex.from_product([["Close"], ["KRW=X"]])
            return pd.DataFrame([[1300.0], [1310.0]], index=dates, columns=columns)
        raise AssertionError(f"unexpected tickers: {tickers}")

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))
    assets = [Asset(symbol="SPY", name="SPY", currency="USD", asset_class=None)]

    with pytest.raises(DataError, match="Missing yfinance Close column for EURKRW=X"):
        YFinanceProvider(fx_tickers={"USD": "KRW=X", "EUR": "EURKRW=X"}).load(
            assets, "2024-01-02", "2024-01-03"
        )


def test_yfinance_provider_wraps_download_errors(monkeypatch):
    def fake_download(**kwargs):
        raise TimeoutError("network timed out")

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(download=fake_download))
    assets = [Asset(symbol="SPY", name="SPY", currency="USD", asset_class=None)]

    with pytest.raises(DataError, match="yfinance download failed for SPY"):
        YFinanceProvider(timeout_seconds=1).load(assets, "2024-01-02", "2024-01-03")
