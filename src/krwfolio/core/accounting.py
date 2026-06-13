import pandas as pd


def drawdown(nav: pd.Series) -> pd.Series:
    return nav / nav.cummax() - 1.0


def values_base(shares: pd.Series, prices: pd.Series, fx: pd.Series) -> pd.Series:
    return shares * prices * fx

