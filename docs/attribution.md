# Attribution Model

For a USD asset:

```text
1 + R_base = (1 + R_local) * (1 + R_fx)
R_base = R_local + R_fx + R_local * R_fx
```

Daily return contribution uses previous after-trade weight:

```text
asset_total_contribution_i_t = weight_i_t-1 * R_base_i_t
local_contribution_i_t = weight_i_t-1 * R_local_i_t
fx_contribution_i_t = weight_i_t-1 * R_fx_i_t
cross_contribution_i_t = weight_i_t-1 * R_local_i_t * R_fx_i_t
```

Cumulative attribution is PnL based:

```text
cumulative_local_contribution = sum(local_pnl_t) / initial_nav
cumulative_fx_contribution = sum(fx_pnl_t) / initial_nav
cumulative_cross_contribution = sum(cross_pnl_t) / initial_nav
cumulative_cost_contribution = sum(cost_pnl_t) / initial_nav
```

This keeps final total return reconciled with contribution totals.

Rebalancing effect is defined against a counterfactual:

```text
gross_rebalance_effect =
  return(rebalanced, no transaction cost) - return(buy_and_hold, no transaction cost)

transaction_cost_drag =
  return(rebalanced, with transaction cost) - return(rebalanced, no transaction cost)

implementation_cost_drag =
  return(rebalanced, with initial cost only) - return(rebalanced, no cost)

rebalance_trading_cost_drag =
  return(rebalanced, with all costs) - return(rebalanced, with initial cost only)

net_rebalance_effect = gross_rebalance_effect + rebalance_trading_cost_drag
```

`implementation_cost_drag` is the initial portfolio construction cost. It is not counted
as rebalancing drag. This keeps `rebalance="none"` from reporting a negative net
rebalancing effect just because the initial purchase had transaction cost.

This should be described as rebalancing contribution versus buy-and-hold baseline, not
as rebalancing alpha.
