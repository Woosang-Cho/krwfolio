# Calculation Model

`krwfolio` uses an auditable daily loop rather than a heavily vectorized strategy engine.

Portfolio NAV on date `t`:

```text
NAV_t = sum(asset_value_base_i_t) + cash_base_t
asset_value_base_i_t = shares_i_t * local_price_i_t * fx_rate_i_t
```

The MVP convention is:

1. On the first close, buy target weights with fractional shares.
2. On each later date, value yesterday's after-trade holdings at today's close.
3. Record local return, FX return, base-currency return, PnL, and attribution.
4. If scheduled, rebalance after close using today's closing prices.
5. Deduct transaction costs before setting final target shares.
6. Use the after-trade holdings as the next day's starting positions.

Rebalancing dates are the last valuation date before a calendar period changes. The
terminal valuation date is not rebalanced by default because there is no later holding
period to benefit from the trade. Set `include_terminal_rebalance=true` explicitly if
that behavior is desired.

Valuation uses a union calendar plus forward-fill, but stale data is bounded. Staleness
is measured on the full union calendar before the effective start is trimmed, so a
portfolio cannot silently begin from an already stale price. If any required price or FX
column is forward-filled for more than `max_staleness_days`, the engine raises
`DataError`.

Initial and scheduled trades use an execution calendar. A date is executable only when
every target asset price and every required FX rate are observed on that date. Scheduled
rebalances are selected from the execution calendar, not from the broader valuation
calendar.

The MVP supports KRW as base currency and KRW/USD assets only. USD/KRW means KRW per
1 USD. If USD/KRW rises from 1300 to 1430, USD appreciated against KRW by 10%.
