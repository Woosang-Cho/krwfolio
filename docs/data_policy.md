# Data Policy

Use adjusted close consistently. Do not mix Close and Adj Close, and do not add
dividends again when adjusted close already includes them.

The optional `YFinanceProvider` is an example provider for research and education. It
should not be described as an official, verified, or reproducibility-guaranteed data
source.

Common risks:

- USD/KRW quote direction can be inverted by mistake.
- KRW and USD asset holidays do not fully overlap.
- Union calendar plus forward fill creates stale prices; the engine fails when
  staleness exceeds `max_staleness_days`.
- Rebalancing on stale prices can create impossible trades; scheduled rebalances are
  selected from dates where all target asset prices and required FX rates are observed.
- FX and equity closes happen in different time zones.
- Current ETF universes can introduce survivorship bias when used for past periods.
