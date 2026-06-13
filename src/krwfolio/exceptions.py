class KrwfolioError(Exception):
    """Base exception for krwfolio."""


class ValidationError(KrwfolioError):
    """Raised when user input violates the MVP accounting model."""


class DataError(KrwfolioError):
    """Raised when market data cannot support a reproducible backtest."""

