# Data Policy

Use adjusted close consistently. Do not mix Close and Adj Close, and do not add
dividends again when adjusted close already includes them.

The optional `YFinanceProvider` is an example provider for research and education. It
should not be described as an official, verified, or reproducibility-guaranteed data
source.

Provider responsibilities are intentionally narrow:

- load raw price and FX data into DataFrames
- preserve source metadata and warnings
- keep ticker and column names visible to the engine

The engine owns calendar alignment, forward-fill, staleness checks, execution masks,
and accounting validation. CSV snapshots are the reproducible input format; yfinance is
only a convenience source for quick local exploration.

Common risks:

- USD/KRW quote direction can be inverted by mistake.
- KRW and USD asset holidays do not fully overlap.
- Union calendar plus forward fill creates stale prices; the engine fails when
  staleness exceeds `max_staleness_days`.
- Rebalancing on stale prices can create impossible trades; scheduled rebalances are
  mapped to the first later date where all target asset prices and required FX rates are
  observed.
- FX and equity closes happen in different time zones.
- Current ETF universes can introduce survivorship bias when used for past periods.
