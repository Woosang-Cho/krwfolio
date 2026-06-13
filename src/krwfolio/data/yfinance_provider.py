from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from krwfolio.assets import Asset
from krwfolio.exceptions import DataError
from krwfolio.portfolio import MarketData


class YFinanceProvider:
    """Optional research/education provider backed by Yahoo Finance data."""

    def __init__(self, fx_tickers: dict[str, str] | None = None, timeout_seconds: int = 10):
        self.fx_tickers = fx_tickers or {"USD": "KRW=X"}
        self.timeout_seconds = timeout_seconds

    def load(self, assets: list[Asset], start: str, end: str) -> MarketData:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise DataError("Install krwfolio[yfinance] to use YFinanceProvider.") from exc

        download_end = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        asset_symbols = [asset.symbol for asset in assets]
        price_history = download_history(yf, asset_symbols, start, download_end, self.timeout_seconds)
        price_series = []
        for asset in assets:
            close = close_series(
                price_history,
                asset.symbol,
                allow_single_ticker_fallback=len(asset_symbols) == 1,
            )
            if close.dropna().empty:
                raise DataError(f"No yfinance price data for {asset.symbol}.")
            price_series.append(close.rename(asset.symbol))
        prices = pd.concat(price_series, axis=1, join="outer").sort_index()

        fx_series = [pd.Series(1.0, index=prices.index, name="KRW")]
        fx_history = download_history(
            yf, list(self.fx_tickers.values()), start, download_end, self.timeout_seconds
        )
        for currency, ticker in self.fx_tickers.items():
            close = close_series(
                fx_history,
                ticker,
                allow_single_ticker_fallback=len(self.fx_tickers) == 1,
            )
            if close.dropna().empty:
                raise DataError(f"No yfinance FX data for {ticker}.")
            fx_series.append(close.rename(currency))
        fx = pd.concat(fx_series, axis=1, join="outer").sort_index()
        return MarketData(
            prices=prices,
            fx=fx,
            metadata={
                "provider": "yfinance",
                "downloaded_at": datetime.now(UTC).isoformat(),
                "auto_adjust": True,
                "threads": True,
                "timeout_seconds": self.timeout_seconds,
                "asset_symbols": asset_symbols,
                "fx_tickers": self.fx_tickers,
                "reproducibility_warning": (
                    "Yahoo/yfinance data can change over time. Save the downloaded prices and FX "
                    "as CSV if this run must be reproduced."
                ),
            },
        )


def download_history(
    yf: object, tickers: list[str], start: str, end: str, timeout_seconds: int
) -> pd.DataFrame:
    try:
        history = yf.download(
            tickers=tickers,
            start=start,
            end=end,
            auto_adjust=True,
            progress=False,
            threads=True,
            timeout=timeout_seconds,
        )
    except Exception as exc:
        joined = ", ".join(tickers)
        raise DataError(f"yfinance download failed for {joined}: {exc}") from exc
    if history.empty:
        joined = ", ".join(tickers)
        raise DataError(f"No yfinance data for {joined}.")
    return history


def close_series(
    history: pd.DataFrame, symbol: str, *, allow_single_ticker_fallback: bool = False
) -> pd.Series:
    if isinstance(history.columns, pd.MultiIndex):
        return multi_index_close_series(
            history, symbol, allow_single_ticker_fallback=allow_single_ticker_fallback
        )
    close = history["Close"]
    if isinstance(close, pd.DataFrame):
        if symbol in close.columns:
            close = close[symbol]
        elif allow_single_ticker_fallback and len(close.columns) == 1:
            close = close.iloc[:, 0]
        else:
            raise DataError(f"Missing yfinance Close column for {symbol}.")
    return close


def multi_index_close_series(
    history: pd.DataFrame, symbol: str, *, allow_single_ticker_fallback: bool = False
) -> pd.Series:
    columns = history.columns
    if "Close" in columns.get_level_values(0):
        close = history["Close"]
        if isinstance(close, pd.DataFrame):
            if symbol in close.columns:
                return close[symbol]
            if allow_single_ticker_fallback and len(close.columns) == 1:
                return close.iloc[:, 0]
            raise DataError(f"Missing yfinance Close column for {symbol}.")
        return close
    if symbol in columns.get_level_values(0):
        symbol_frame = history[symbol]
        if "Close" not in symbol_frame.columns:
            raise DataError(f"Missing yfinance Close column for {symbol}.")
        close = symbol_frame["Close"]
        if isinstance(close, pd.DataFrame):
            if not allow_single_ticker_fallback and len(close.columns) != 1:
                raise DataError(f"Ambiguous yfinance Close columns for {symbol}.")
            return close.iloc[:, 0]
        return close
    raise DataError(f"Missing yfinance data for {symbol}.")
