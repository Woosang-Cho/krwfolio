from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from krwfolio.assets import Asset
from krwfolio.analytics.metrics import compute_metrics
from krwfolio.core.accounting import drawdown
from krwfolio.core.fx import asset_fx_frame, base_returns, validate_asset_currencies
from krwfolio.core.rebalancing import rebalance_dates
from krwfolio.exceptions import DataError, ValidationError
from krwfolio.portfolio import BacktestResult, MarketData, PortfolioSpec


@dataclass
class BacktestEngine:
    calendar_policy: str = "union_ffill"
    max_staleness_days: int = 7
    include_terminal_rebalance: bool = False
    include_rebalance_attribution: bool = True

    def run(
        self,
        assets: list[Asset],
        spec: PortfolioSpec,
        data: MarketData,
        *,
        _cost_mode: str = "all",
    ) -> BacktestResult:
        spec.validate()
        self._validate_assets(assets, spec)
        if _cost_mode not in {"all", "none", "initial_only"}:
            raise ValidationError("_cost_mode must be all, none, or initial_only.")

        prepared = self._prepare_data(assets, data)
        prepared = self._trim_to_first_execution(prepared)
        prices = prepared.prices
        fx = prepared.fx
        fx_by_asset = asset_fx_frame(assets, fx)
        local_returns = prices.pct_change().fillna(0.0)
        fx_returns = fx_by_asset.pct_change().fillna(0.0)
        symbols = [asset.symbol for asset in assets]
        target_weights = pd.Series(spec.weights, dtype=float).reindex(symbols)
        target_weight_values = target_weights.to_numpy(dtype=float)
        execution_index = prepared.execution_mask.index[prepared.execution_mask]
        first_execution_date = execution_index[0]
        scheduled_rebal_dates = rebalance_dates(
            prices.index,
            spec.rebalance,
            include_terminal_rebalance=self.include_terminal_rebalance,
        ) - {first_execution_date}
        mapped_rebal_dates, skipped_rebal_dates = self._map_rebalance_dates(
            scheduled_rebal_dates,
            execution_index,
            prices.index[-1],
        )
        rebal_dates = mapped_rebal_dates
        executed_rebal_dates: set[pd.Timestamp] = set()

        dates = prices.index
        price_values = prices.to_numpy(dtype=float)
        fx_values = fx_by_asset.to_numpy(dtype=float)
        local_return_values = local_returns.to_numpy(dtype=float)
        fx_return_values = fx_returns.to_numpy(dtype=float)
        asset_base_return_values = base_returns(local_returns, fx_returns).to_numpy(dtype=float)

        shares = np.zeros(len(symbols), dtype=float)
        cash = 0.0
        previous_values = np.zeros(len(symbols), dtype=float)
        previous_nav = spec.initial_value
        previous_weight = target_weight_values.copy()

        equity_records: list[dict[str, float | pd.Timestamp]] = []
        holdings_records: list[dict[str, float | pd.Timestamp]] = []
        weights_records: list[dict[str, float | pd.Timestamp]] = []
        trade_records: list[dict[str, float | str | pd.Timestamp]] = []
        daily_attr_records: list[dict[str, float | pd.Timestamp]] = []

        for position, date in enumerate(dates):
            price_row = price_values[position]
            fx_row = fx_values[position]
            before_values = shares * price_row * fx_row
            nav_before_trade = float(before_values.sum() + cash)

            if position == 0:
                nav_before_trade = float(spec.initial_value)
                before_values = np.zeros(len(symbols), dtype=float)
                total_cost = self._rebalance_arrays(
                    date,
                    symbols,
                    target_weight_values,
                    before_values,
                    nav_before_trade,
                    price_row,
                    fx_row,
                    self._cost_bps_for_trade(spec.transaction_cost_bps, "initial", _cost_mode),
                    trade_records,
                    trade_type="initial",
                )
                nav_after_trade = nav_before_trade - total_cost
                shares = target_weight_values * nav_after_trade / (price_row * fx_row)
                cash = 0.0
                after_values = shares * price_row * fx_row
                asset_pnl = np.zeros(len(symbols), dtype=float)
                local_pnl = np.zeros(len(symbols), dtype=float)
                fx_pnl = np.zeros(len(symbols), dtype=float)
                cross_pnl = np.zeros(len(symbols), dtype=float)
                portfolio_return = (nav_after_trade / spec.initial_value) - 1.0
                risk_portfolio_return = 0.0
            else:
                asset_pnl = before_values - previous_values
                local_pnl = previous_values * local_return_values[position]
                fx_pnl = previous_values * fx_return_values[position]
                cross_pnl = (
                    previous_values
                    * local_return_values[position]
                    * fx_return_values[position]
                )
                should_rebalance = date in rebal_dates
                total_cost = 0.0
                if should_rebalance:
                    total_cost = self._rebalance_arrays(
                        date,
                        symbols,
                        target_weight_values,
                        before_values,
                        nav_before_trade,
                        price_row,
                        fx_row,
                        self._cost_bps_for_trade(spec.transaction_cost_bps, "rebalance", _cost_mode),
                        trade_records,
                        trade_type="rebalance",
                    )
                    executed_rebal_dates.add(date)
                    nav_after_trade = nav_before_trade - total_cost
                    shares = target_weight_values * nav_after_trade / (price_row * fx_row)
                    cash = 0.0
                    after_values = shares * price_row * fx_row
                else:
                    nav_after_trade = nav_before_trade
                    after_values = before_values
                portfolio_return = (nav_after_trade / previous_nav) - 1.0
                risk_portfolio_return = portfolio_return

            cost_pnl = -float(total_cost)
            daily_attr_records.append(
                self._daily_attribution_record_arrays(
                    date=date,
                    symbols=symbols,
                    asset_pnl=asset_pnl,
                    local_pnl=local_pnl,
                    fx_pnl=fx_pnl,
                    cross_pnl=cross_pnl,
                    cost_pnl=cost_pnl,
                    cash_pnl=0.0,
                    previous_nav=previous_nav,
                    previous_weight=previous_weight,
                    base_returns_row=asset_base_return_values[position],
                    local_returns_row=local_return_values[position],
                    fx_returns_row=fx_return_values[position],
                )
            )

            after_nav = float(after_values.sum() + cash)
            after_weight = (
                after_values / after_nav
                if after_nav
                else np.full(len(symbols), np.nan, dtype=float)
            )
            equity_records.append(
                {
                    "date": date,
                    "nav": after_nav,
                    "cash": cash,
                    "transaction_cost": float(total_cost),
                    "daily_return": float(portfolio_return),
                    "risk_daily_return": float(risk_portfolio_return),
                }
            )
            holdings_records.append(
                {"date": date} | {symbol: float(value) for symbol, value in zip(symbols, after_values)}
            )
            weights_records.append(
                {"date": date} | {symbol: float(value) for symbol, value in zip(symbols, after_weight)}
            )

            previous_values = after_values.copy()
            previous_nav = after_nav
            previous_weight = after_weight.copy()

        equity_curve = pd.DataFrame(equity_records).set_index("date")
        equity_curve["drawdown"] = drawdown(equity_curve["nav"])
        holdings = pd.DataFrame(holdings_records).set_index("date")
        weights = pd.DataFrame(weights_records).set_index("date")
        trades = pd.DataFrame(trade_records)
        if not trades.empty:
            trades = trades.set_index("date")
        daily_attr = pd.DataFrame(daily_attr_records).set_index("date")
        cumulative_attr = self._cumulative_attribution(daily_attr, spec.initial_value)
        metrics = compute_metrics(
            equity_curve["nav"],
            equity_curve["risk_daily_return"],
            trades,
            initial_value=spec.initial_value,
        )
        if self.include_rebalance_attribution:
            rebalance_attr = self._rebalance_attribution(
                assets,
                spec,
                data,
                actual_return=metrics["total_return"],
            )
        else:
            rebalance_attr = pd.DataFrame([{}])
        metrics.update(rebalance_attr.iloc[0].to_dict())

        diagnostics = self._diagnostics(
            prepared,
            scheduled_rebal_dates,
            mapped_rebal_dates,
            executed_rebal_dates,
            skipped_rebal_dates,
        )
        return BacktestResult(
            equity_curve=equity_curve,
            holdings=holdings,
            weights=weights,
            trades=trades,
            daily_returns=equity_curve["daily_return"],
            attribution={
                "daily": daily_attr,
                "cumulative": cumulative_attr,
                "rebalance": rebalance_attr,
            },
            metrics=metrics,
            diagnostics=diagnostics,
        )

    def _validate_assets(self, assets: list[Asset], spec: PortfolioSpec) -> None:
        if not assets:
            raise ValidationError("assets must not be empty.")
        validate_asset_currencies(assets)
        symbols = [asset.symbol for asset in assets]
        if len(symbols) != len(set(symbols)):
            raise ValidationError("asset symbols must be unique.")
        if set(symbols) != set(spec.weights):
            raise ValidationError("Portfolio weights must match asset symbols exactly.")

    def _prepare_data(
        self, assets: list[Asset], data: MarketData
    ) -> "PreparedMarketData":
        if self.calendar_policy != "union_ffill":
            raise ValidationError("MVP supports calendar_policy='union_ffill' only.")
        symbols = [asset.symbol for asset in assets]
        prices_raw = self._validate_frame(data.prices, "prices").copy()
        fx_raw = self._validate_frame(data.fx, "fx").copy()
        missing_prices = sorted(set(symbols) - set(prices_raw.columns))
        if missing_prices:
            raise DataError(f"Missing price columns: {missing_prices}")
        needed_fx_columns = sorted({asset.currency for asset in assets} | {"KRW"})
        missing_fx = sorted(set(needed_fx_columns) - set(fx_raw.columns) - {"KRW"})
        if missing_fx:
            raise DataError(f"Missing FX columns for currencies: {missing_fx}")
        unused_fx_columns = sorted(set(fx_raw.columns) - set(needed_fx_columns))
        fx_raw = fx_raw.reindex(columns=[column for column in needed_fx_columns if column != "KRW"])
        fx_raw["KRW"] = 1.0

        index = prices_raw.index.union(fx_raw.index).sort_values()
        full_price_observed = prices_raw.reindex(index)[symbols].notna()
        full_fx_observed = fx_raw.reindex(index)[needed_fx_columns].notna()
        full_fx_observed["KRW"] = True
        full_price_staleness = self._staleness_days(full_price_observed)
        full_fx_staleness = self._staleness_days(full_fx_observed)
        prices = prices_raw.reindex(index)[symbols].ffill()
        fx = fx_raw.reindex(index)[needed_fx_columns].ffill()
        fx["KRW"] = 1.0

        prices = prices.dropna(how="any")
        fx = fx.loc[prices.index].dropna(how="any")
        prices = prices.loc[fx.index]
        price_observed = full_price_observed.loc[prices.index]
        fx_observed = full_fx_observed.loc[prices.index, fx.columns]
        price_staleness = full_price_staleness.loc[prices.index]
        fx_staleness = full_fx_staleness.loc[prices.index, fx.columns]

        self._validate_positive(prices, "prices")
        self._validate_positive(fx, "fx")
        self._raise_on_stale(price_staleness, "price")
        self._raise_on_stale(fx_staleness, "FX")
        if len(prices) < 2:
            raise DataError("At least two aligned valuation dates are required.")
        usd_fx = fx["USD"] if "USD" in fx.columns else pd.Series(dtype=float)
        fx_warnings = []
        if not usd_fx.empty and usd_fx.median() < 10:
            fx_warnings.append(
                "USD FX values look small for KRW base currency. Expected KRW per 1 USD."
            )
        return PreparedMarketData(
            prices=prices.astype(float),
            fx=fx.astype(float),
            price_observed=price_observed,
            fx_observed=fx_observed,
            price_staleness_days=price_staleness,
            fx_staleness_days=fx_staleness,
            all_prices_observed_today=price_observed.all(axis=1),
            execution_mask=price_observed.all(axis=1) & fx_observed[needed_fx_columns].all(axis=1),
            missing_price_cells_before_fill=int(prices_raw[symbols].isna().sum().sum()),
            missing_fx_cells_before_fill=int(fx_raw.isna().sum().sum()),
            unused_fx_columns=unused_fx_columns,
            fx_warnings=fx_warnings,
            metadata=dict(data.metadata),
        )

    def _trim_to_first_execution(self, prepared: "PreparedMarketData") -> "PreparedMarketData":
        execution_dates = prepared.execution_mask.index[prepared.execution_mask]
        if execution_dates.empty:
            raise DataError("No execution date has observed prices and FX for all assets.")
        first_execution = execution_dates[0]
        index = prepared.prices.index[prepared.prices.index >= first_execution]
        if len(index) < 2:
            raise DataError("At least two valuation dates are required after first execution date.")
        return prepared.loc(index)

    def _validate_frame(self, frame: pd.DataFrame, name: str) -> pd.DataFrame:
        if not isinstance(frame.index, pd.DatetimeIndex):
            raise DataError(f"{name} index must be a DatetimeIndex.")
        if frame.index.has_duplicates:
            raise DataError(f"{name} index contains duplicate dates.")
        if not frame.index.is_monotonic_increasing:
            frame = frame.sort_index()
        return frame

    def _validate_positive(self, frame: pd.DataFrame, name: str) -> None:
        numeric = frame.apply(pd.to_numeric, errors="coerce")
        if numeric.isna().any().any():
            raise DataError(f"{name} must contain numeric values only.")
        if (numeric <= 0).any().any():
            raise DataError(f"{name} must contain positive values only.")

    def _staleness_days(self, observed: pd.DataFrame) -> pd.DataFrame:
        rows: dict[str, pd.Series] = {}
        for column in observed.columns:
            last_seen = pd.Series(pd.NaT, index=observed.index, dtype="datetime64[ns]")
            last_seen.loc[observed[column]] = observed.index[observed[column]]
            last_seen = last_seen.ffill()
            rows[column] = pd.Series(
                (observed.index.to_series(index=observed.index) - last_seen).dt.days,
                index=observed.index,
            )
        return pd.DataFrame(rows, index=observed.index).fillna(0).astype(int)

    def _raise_on_stale(self, staleness: pd.DataFrame, label: str) -> None:
        too_stale = staleness > self.max_staleness_days
        if not too_stale.any().any():
            return
        date = too_stale.any(axis=1).idxmax()
        columns = sorted(too_stale.columns[too_stale.loc[date]].tolist())
        details = []
        for column in columns:
            stale_days = int(staleness.loc[date, column])
            last_observed = date - pd.Timedelta(days=stale_days)
            details.append(f"{column}: last_observed={last_observed.date()}, stale_days={stale_days}")
        raise DataError(
            f"{label} data is stale beyond max_staleness_days={self.max_staleness_days} "
            f"on {date.date()}: {'; '.join(details)}"
        )

    def _map_rebalance_dates(
        self,
        scheduled_dates: set[pd.Timestamp],
        execution_index: pd.DatetimeIndex,
        terminal_date: pd.Timestamp,
    ) -> tuple[set[pd.Timestamp], set[pd.Timestamp]]:
        mapped_dates: set[pd.Timestamp] = set()
        skipped_dates: set[pd.Timestamp] = set()
        for scheduled_date in sorted(scheduled_dates):
            position = execution_index.searchsorted(scheduled_date)
            if position >= len(execution_index):
                skipped_dates.add(scheduled_date)
                continue
            mapped_date = pd.Timestamp(execution_index[position])
            if not self.include_terminal_rebalance and mapped_date == terminal_date:
                skipped_dates.add(scheduled_date)
                continue
            mapped_dates.add(mapped_date)
        return mapped_dates, skipped_dates

    def _cost_bps_for_trade(self, bps: float, trade_type: str, cost_mode: str) -> float:
        if cost_mode == "none":
            return 0.0
        if cost_mode == "initial_only" and trade_type != "initial":
            return 0.0
        return bps

    def _rebalance(
        self,
        date: pd.Timestamp,
        target_weights: pd.Series,
        current_values: pd.Series,
        nav_before_trade: float,
        prices: pd.Series,
        fx: pd.Series,
        transaction_cost_bps: float,
        trade_records: list[dict[str, float | str | pd.Timestamp]],
        trade_type: str,
    ) -> float:
        raw_targets = target_weights * nav_before_trade
        raw_trade_values = raw_targets - current_values
        total_cost = float(raw_trade_values.abs().sum() * transaction_cost_bps / 10_000.0)
        nav_after_cost = nav_before_trade - total_cost
        if nav_after_cost <= 0:
            raise DataError("Transaction cost is greater than or equal to NAV before trade.")
        final_targets = target_weights * nav_after_cost
        final_trade_values = final_targets - current_values
        total_intended_turnover = float(raw_trade_values.abs().sum())
        for symbol, trade_value in final_trade_values.items():
            intended_trade_value = float(raw_trade_values[symbol])
            cost_base = (
                total_cost * abs(intended_trade_value) / total_intended_turnover
                if total_intended_turnover
                else 0.0
            )
            if abs(trade_value) < 1e-12 and abs(intended_trade_value) < 1e-12:
                continue
            trade_records.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "trade_type": trade_type,
                    "intended_trade_value_base": intended_trade_value,
                    "executed_trade_value_base": float(trade_value),
                    "trade_value_base": float(trade_value),
                    "cost_base": float(cost_base),
                    "turnover_basis_base": abs(intended_trade_value),
                    "price_local": float(prices[symbol]),
                    "fx_to_base": float(fx[symbol]),
                    "shares_delta": float(trade_value / (prices[symbol] * fx[symbol])),
                }
            )
        return total_cost

    def _rebalance_arrays(
        self,
        date: pd.Timestamp,
        symbols: list[str],
        target_weights: np.ndarray,
        current_values: np.ndarray,
        nav_before_trade: float,
        prices: np.ndarray,
        fx: np.ndarray,
        transaction_cost_bps: float,
        trade_records: list[dict[str, float | str | pd.Timestamp]],
        trade_type: str,
    ) -> float:
        raw_targets = target_weights * nav_before_trade
        raw_trade_values = raw_targets - current_values
        total_cost = float(np.abs(raw_trade_values).sum() * transaction_cost_bps / 10_000.0)
        nav_after_cost = nav_before_trade - total_cost
        if nav_after_cost <= 0:
            raise DataError("Transaction cost is greater than or equal to NAV before trade.")
        final_targets = target_weights * nav_after_cost
        final_trade_values = final_targets - current_values
        total_intended_turnover = float(np.abs(raw_trade_values).sum())
        for index, symbol in enumerate(symbols):
            trade_value = float(final_trade_values[index])
            intended_trade_value = float(raw_trade_values[index])
            cost_base = (
                total_cost * abs(intended_trade_value) / total_intended_turnover
                if total_intended_turnover
                else 0.0
            )
            if abs(trade_value) < 1e-12 and abs(intended_trade_value) < 1e-12:
                continue
            trade_records.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "trade_type": trade_type,
                    "intended_trade_value_base": intended_trade_value,
                    "executed_trade_value_base": trade_value,
                    "trade_value_base": trade_value,
                    "cost_base": float(cost_base),
                    "turnover_basis_base": abs(intended_trade_value),
                    "price_local": float(prices[index]),
                    "fx_to_base": float(fx[index]),
                    "shares_delta": float(trade_value / (prices[index] * fx[index])),
                }
            )
        return total_cost

    def _daily_attribution_record(
        self,
        *,
        date: pd.Timestamp,
        symbols: list[str],
        asset_pnl: pd.Series,
        local_pnl: pd.Series,
        fx_pnl: pd.Series,
        cross_pnl: pd.Series,
        cost_pnl: float,
        cash_pnl: float,
        previous_nav: float,
        previous_weight: pd.Series,
        base_returns_row: pd.Series,
        local_returns_row: pd.Series,
        fx_returns_row: pd.Series,
    ) -> dict[str, float | pd.Timestamp]:
        record: dict[str, float | pd.Timestamp] = {
            "date": date,
            "local_pnl": float(local_pnl.sum()),
            "fx_pnl": float(fx_pnl.sum()),
            "cross_pnl": float(cross_pnl.sum()),
            "asset_pnl": float(asset_pnl.sum()),
            "cash_pnl": float(cash_pnl),
            "cost_pnl": float(cost_pnl),
            "total_pnl": float(asset_pnl.sum() + cash_pnl + cost_pnl),
            "local_contribution": float(local_pnl.sum() / previous_nav),
            "fx_contribution": float(fx_pnl.sum() / previous_nav),
            "cross_contribution": float(cross_pnl.sum() / previous_nav),
            "cash_contribution": float(cash_pnl / previous_nav),
            "cost_contribution": float(cost_pnl / previous_nav),
        }
        record["asset_total_contribution"] = (
            record["local_contribution"]
            + record["fx_contribution"]
            + record["cross_contribution"]
        )
        record["portfolio_contribution"] = (
            record["asset_total_contribution"]
            + record["cash_contribution"]
            + record["cost_contribution"]
        )
        for symbol in symbols:
            record[f"{symbol}_local_contribution"] = float(
                previous_weight[symbol] * local_returns_row[symbol]
            )
            record[f"{symbol}_fx_contribution"] = float(
                previous_weight[symbol] * fx_returns_row[symbol]
            )
            record[f"{symbol}_cross_contribution"] = float(
                previous_weight[symbol] * local_returns_row[symbol] * fx_returns_row[symbol]
            )
            record[f"{symbol}_asset_total_contribution"] = float(
                previous_weight[symbol] * base_returns_row[symbol]
            )
            record[f"{symbol}_local_pnl"] = float(local_pnl[symbol])
            record[f"{symbol}_fx_pnl"] = float(fx_pnl[symbol])
            record[f"{symbol}_cross_pnl"] = float(cross_pnl[symbol])
            record[f"{symbol}_asset_pnl"] = float(asset_pnl[symbol])
        return record

    def _daily_attribution_record_arrays(
        self,
        *,
        date: pd.Timestamp,
        symbols: list[str],
        asset_pnl: np.ndarray,
        local_pnl: np.ndarray,
        fx_pnl: np.ndarray,
        cross_pnl: np.ndarray,
        cost_pnl: float,
        cash_pnl: float,
        previous_nav: float,
        previous_weight: np.ndarray,
        base_returns_row: np.ndarray,
        local_returns_row: np.ndarray,
        fx_returns_row: np.ndarray,
    ) -> dict[str, float | pd.Timestamp]:
        local_pnl_sum = float(local_pnl.sum())
        fx_pnl_sum = float(fx_pnl.sum())
        cross_pnl_sum = float(cross_pnl.sum())
        asset_pnl_sum = float(asset_pnl.sum())
        record: dict[str, float | pd.Timestamp] = {
            "date": date,
            "local_pnl": local_pnl_sum,
            "fx_pnl": fx_pnl_sum,
            "cross_pnl": cross_pnl_sum,
            "asset_pnl": asset_pnl_sum,
            "cash_pnl": float(cash_pnl),
            "cost_pnl": float(cost_pnl),
            "total_pnl": float(asset_pnl_sum + cash_pnl + cost_pnl),
            "local_contribution": float(local_pnl_sum / previous_nav),
            "fx_contribution": float(fx_pnl_sum / previous_nav),
            "cross_contribution": float(cross_pnl_sum / previous_nav),
            "cash_contribution": float(cash_pnl / previous_nav),
            "cost_contribution": float(cost_pnl / previous_nav),
        }
        record["asset_total_contribution"] = (
            record["local_contribution"]
            + record["fx_contribution"]
            + record["cross_contribution"]
        )
        record["portfolio_contribution"] = (
            record["asset_total_contribution"]
            + record["cash_contribution"]
            + record["cost_contribution"]
        )
        for index, symbol in enumerate(symbols):
            record[f"{symbol}_local_contribution"] = float(
                previous_weight[index] * local_returns_row[index]
            )
            record[f"{symbol}_fx_contribution"] = float(
                previous_weight[index] * fx_returns_row[index]
            )
            record[f"{symbol}_cross_contribution"] = float(
                previous_weight[index] * local_returns_row[index] * fx_returns_row[index]
            )
            record[f"{symbol}_asset_total_contribution"] = float(
                previous_weight[index] * base_returns_row[index]
            )
            record[f"{symbol}_local_pnl"] = float(local_pnl[index])
            record[f"{symbol}_fx_pnl"] = float(fx_pnl[index])
            record[f"{symbol}_cross_pnl"] = float(cross_pnl[index])
            record[f"{symbol}_asset_pnl"] = float(asset_pnl[index])
        return record

    def _cumulative_attribution(
        self, daily_attr: pd.DataFrame, initial_value: float
    ) -> pd.DataFrame:
        fields = ["local_pnl", "fx_pnl", "cross_pnl", "asset_pnl", "cash_pnl", "cost_pnl", "total_pnl"]
        rows = {
            field.replace("_pnl", "_contribution"): daily_attr[field].sum() / initial_value
            for field in fields
        }
        return pd.DataFrame([rows])

    def _rebalance_attribution(
        self,
        assets: list[Asset],
        spec: PortfolioSpec,
        data: MarketData,
        *,
        actual_return: float,
    ) -> pd.DataFrame:
        if getattr(self, "_running_counterfactual", False):
            return pd.DataFrame([{}])
        no_cost_spec = PortfolioSpec(
            base_currency=spec.base_currency,
            initial_value=spec.initial_value,
            weights=spec.weights,
            rebalance=spec.rebalance,
            transaction_cost_bps=0.0,
        )
        buy_hold_spec = PortfolioSpec(
            base_currency=spec.base_currency,
            initial_value=spec.initial_value,
            weights=spec.weights,
            rebalance="none",
            transaction_cost_bps=0.0,
        )
        self._running_counterfactual = True
        try:
            rebalanced_no_cost = self.run(assets, no_cost_spec, data, _cost_mode="none")
            buy_hold = self.run(assets, buy_hold_spec, data, _cost_mode="none")
            rebalanced_with_initial_cost = self.run(assets, spec, data, _cost_mode="initial_only")
        finally:
            self._running_counterfactual = False
        gross = rebalanced_no_cost.metrics["total_return"] - buy_hold.metrics["total_return"]
        implementation_cost_drag = (
            rebalanced_with_initial_cost.metrics["total_return"]
            - rebalanced_no_cost.metrics["total_return"]
        )
        total_cost_drag = actual_return - rebalanced_no_cost.metrics["total_return"]
        rebalance_trading_cost_drag = (
            actual_return - rebalanced_with_initial_cost.metrics["total_return"]
        )
        return pd.DataFrame(
            [
                {
                    "buy_and_hold_return": buy_hold.metrics["total_return"],
                    "rebalanced_no_cost_return": rebalanced_no_cost.metrics["total_return"],
                    "rebalanced_with_initial_cost_return": rebalanced_with_initial_cost.metrics[
                        "total_return"
                    ],
                    "actual_return": actual_return,
                    "gross_rebalance_effect": gross,
                    "implementation_cost_drag": implementation_cost_drag,
                    "rebalance_trading_cost_drag": rebalance_trading_cost_drag,
                    "transaction_cost_drag": total_cost_drag,
                    "total_transaction_cost_drag": total_cost_drag,
                    "net_rebalance_policy_effect": gross + rebalance_trading_cost_drag,
                    "rebalanced_vs_buy_hold_effect": gross + rebalance_trading_cost_drag,
                    "net_rebalance_effect": gross + rebalance_trading_cost_drag,
                }
            ]
        )

    def _diagnostics(
        self,
        prepared: "PreparedMarketData",
        scheduled_rebal_dates: set[pd.Timestamp],
        mapped_rebal_dates: set[pd.Timestamp],
        executed_rebal_dates: set[pd.Timestamp],
        skipped_rebal_dates: set[pd.Timestamp],
    ) -> dict[str, object]:
        return {
            "calendar_policy": self.calendar_policy,
            "max_staleness_days": self.max_staleness_days,
            "include_terminal_rebalance": self.include_terminal_rebalance,
            "rebalance_attribution_included": self.include_rebalance_attribution,
            "price_columns": list(prepared.prices.columns),
            "fx_columns": list(prepared.fx.columns),
            "unused_fx_columns": prepared.unused_fx_columns,
            "missing_price_cells_before_fill": prepared.missing_price_cells_before_fill,
            "missing_fx_cells_before_fill": prepared.missing_fx_cells_before_fill,
            "max_price_staleness_by_symbol": prepared.price_staleness_days.max().to_dict(),
            "max_fx_staleness_by_currency": prepared.fx_staleness_days.max().to_dict(),
            "effective_start": prepared.prices.index[0].strftime("%Y-%m-%d"),
            "effective_end": prepared.prices.index[-1].strftime("%Y-%m-%d"),
            "first_execution_date": prepared.execution_mask.index[
                prepared.execution_mask
            ][0].strftime("%Y-%m-%d"),
            "valuation_dates": len(prepared.prices.index),
            "risk_return_note": (
                "risk_daily_return sets the initial implementation-cost day to 0.0 so volatility "
                "and Sharpe are not driven by initial deployment cost."
            ),
            "scheduled_rebalance_dates": [
                date.strftime("%Y-%m-%d") for date in sorted(scheduled_rebal_dates)
            ],
            "mapped_rebalance_dates": [
                date.strftime("%Y-%m-%d") for date in sorted(mapped_rebal_dates)
            ],
            "scheduled_rebalance_candidates": [
                date.strftime("%Y-%m-%d") for date in sorted(scheduled_rebal_dates)
            ],
            "rebalance_dates": [date.strftime("%Y-%m-%d") for date in sorted(executed_rebal_dates)],
            "executed_rebalance_dates": [
                date.strftime("%Y-%m-%d") for date in sorted(executed_rebal_dates)
            ],
            "skipped_rebalance_dates": [
                date.strftime("%Y-%m-%d") for date in sorted(skipped_rebal_dates)
            ],
            "skipped_rebalance_dates_due_to_stale_prices": [
                date.strftime("%Y-%m-%d") for date in sorted(skipped_rebal_dates)
            ],
            "fx_warnings": prepared.fx_warnings,
            "market_data_metadata": prepared.metadata,
            "provider_warnings": self._provider_warnings(prepared.metadata),
            "rebalance_calendar_note": (
                "scheduled_rebalance_dates are derived from the valuation calendar. "
                "mapped_rebalance_dates are the first later dates with observed prices and FX for all assets."
            ),
            "price_source_note": "Use adjusted close consistently; do not add dividends again.",
            "fx_quote_note": "USD/KRW is KRW per 1 USD.",
        }

    def _provider_warnings(self, metadata: dict[str, object]) -> list[str]:
        if metadata.get("provider") != "yfinance":
            return []
        warning = metadata.get("reproducibility_warning")
        if isinstance(warning, str):
            return [warning]
        return [
            "Yahoo/yfinance data can change over time. Save the downloaded prices and FX as CSV "
            "if this run must be reproduced."
        ]


@dataclass
class PreparedMarketData:
    prices: pd.DataFrame
    fx: pd.DataFrame
    price_observed: pd.DataFrame
    fx_observed: pd.DataFrame
    price_staleness_days: pd.DataFrame
    fx_staleness_days: pd.DataFrame
    all_prices_observed_today: pd.Series
    execution_mask: pd.Series
    missing_price_cells_before_fill: int
    missing_fx_cells_before_fill: int
    unused_fx_columns: list[str]
    fx_warnings: list[str]
    metadata: dict[str, object]

    def loc(self, index: pd.DatetimeIndex) -> "PreparedMarketData":
        return PreparedMarketData(
            prices=self.prices.loc[index],
            fx=self.fx.loc[index],
            price_observed=self.price_observed.loc[index],
            fx_observed=self.fx_observed.loc[index],
            price_staleness_days=self.price_staleness_days.loc[index],
            fx_staleness_days=self.fx_staleness_days.loc[index],
            all_prices_observed_today=self.all_prices_observed_today.loc[index],
            execution_mask=self.execution_mask.loc[index],
            missing_price_cells_before_fill=self.missing_price_cells_before_fill,
            missing_fx_cells_before_fill=self.missing_fx_cells_before_fill,
            unused_fx_columns=self.unused_fx_columns,
            fx_warnings=self.fx_warnings,
            metadata=self.metadata,
        )
