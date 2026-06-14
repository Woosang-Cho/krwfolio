# Calculation Contract v0.2

This document fixes the public accounting contract for the current MVP. New features
should not change these meanings without a schema version bump.

## Supported Scope

- base currency: KRW
- asset currencies: KRW, USD
- positions: long-only, fractional shares
- prices: adjusted close or an equivalent total-return price series
- FX quote: KRW per 1 foreign currency unit, for example `USD = 1300`
- calendar: union calendar with forward-fill bounded by `max_staleness_days`
- rebalance timing: after close
- transaction cost: bps applied to pre-cost intended turnover

Unsupported cases include deposits, withdrawals, dividends as separate cash events,
taxes, short positions, integer share rounding, broker execution, and non-USD foreign
currencies.

## Core Reconciliation

Daily accounting must satisfy:

```text
NAV_t = sum(holdings_value_base_t) + cash_t
asset_pnl_t = local_pnl_t + fx_pnl_t + cross_pnl_t
total_pnl_t = asset_pnl_t + cash_pnl_t + cost_pnl_t
daily_return_t = total_pnl_t / previous_NAV_t
sum(total_pnl) / initial_value = final_NAV / initial_value - 1
```

`daily_return` is the accounting return after costs. `risk_daily_return` is used for
volatility and Sharpe. It sets the initial implementation-cost day to `0.0` so initial
deployment cost does not look like market risk.

## Output Schema

`BacktestResult.schema_version` is currently `0.2`.

`equity_curve` must include:

- `nav`
- `cash`
- `transaction_cost`
- `daily_return`
- `risk_daily_return`
- `drawdown`

`trades` must include:

- `symbol`
- `trade_type`
- `intended_trade_value_base`
- `executed_trade_value_base`
- `trade_value_base`
- `cost_base`
- `turnover_basis_base`
- `price_local`
- `fx_to_base`
- `shares_delta`

`attribution["daily"]` must include:

- `local_pnl`
- `fx_pnl`
- `cross_pnl`
- `asset_pnl`
- `cash_pnl`
- `cost_pnl`
- `total_pnl`
- `local_contribution`
- `fx_contribution`
- `cross_contribution`
- `cash_contribution`
- `cost_contribution`
- `portfolio_contribution`

`attribution["cumulative"]` is PnL-based. It is not a compounded attribution model. Its
`total_contribution` must reconcile to final total return.

`diagnostics` must include scheduled, mapped, executed, and skipped rebalance dates so
users can see whether a policy date was delayed or skipped because no executable date
was available. It must also include `rebalance_mapping`, a row-oriented table with:

- `scheduled_date`
- `mapped_date`
- `status`
- `reason`

`rebalance_mapping.reason` is the canonical skip/mapping explanation. Current reasons
are `mapped_same_date`, `mapped_next_executable_date`, `terminal_rebalance_disabled`,
and `no_later_executable_date`. Older list-style diagnostics may remain for
compatibility, but new consumers should prefer the row-oriented mapping table.
