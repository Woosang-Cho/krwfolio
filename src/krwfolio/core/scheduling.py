from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from krwfolio.core.rebalancing import rebalance_dates
from krwfolio.portfolio import RebalanceFrequency

RebalanceMappingStatus = Literal["mapped", "skipped"]
RebalanceMappingReason = Literal[
    "mapped_same_date",
    "mapped_next_executable_date",
    "terminal_rebalance_disabled",
    "no_later_executable_date",
]


@dataclass(frozen=True)
class RebalanceMapping:
    scheduled_date: pd.Timestamp
    mapped_date: pd.Timestamp | None
    status: RebalanceMappingStatus
    reason: RebalanceMappingReason

    def to_diagnostic(self) -> dict[str, str | None]:
        return {
            "scheduled_date": self.scheduled_date.strftime("%Y-%m-%d"),
            "mapped_date": self.mapped_date.strftime("%Y-%m-%d") if self.mapped_date is not None else None,
            "status": self.status,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RebalancePlan:
    scheduled_dates: tuple[pd.Timestamp, ...]
    mapped_dates: tuple[pd.Timestamp, ...]
    skipped_dates: tuple[pd.Timestamp, ...]
    mappings: tuple[RebalanceMapping, ...]


def build_rebalance_plan(
    valuation_index: pd.DatetimeIndex,
    execution_index: pd.DatetimeIndex,
    frequency: RebalanceFrequency,
    *,
    include_terminal_rebalance: bool,
    first_execution_date: pd.Timestamp,
) -> RebalancePlan:
    scheduled_dates = sorted(
        rebalance_dates(
            valuation_index,
            frequency,
            include_terminal_rebalance=include_terminal_rebalance,
        )
        - {first_execution_date}
    )
    mappings = tuple(
        _map_scheduled_date(
            scheduled_date,
            execution_index,
            terminal_date=valuation_index[-1],
            include_terminal_rebalance=include_terminal_rebalance,
        )
        for scheduled_date in scheduled_dates
    )
    return RebalancePlan(
        scheduled_dates=tuple(scheduled_dates),
        mapped_dates=tuple(mapping.mapped_date for mapping in mappings if mapping.mapped_date is not None),
        skipped_dates=tuple(mapping.scheduled_date for mapping in mappings if mapping.status == "skipped"),
        mappings=mappings,
    )


def _map_scheduled_date(
    scheduled_date: pd.Timestamp,
    execution_index: pd.DatetimeIndex,
    *,
    terminal_date: pd.Timestamp,
    include_terminal_rebalance: bool,
) -> RebalanceMapping:
    position = execution_index.searchsorted(scheduled_date)
    if position >= len(execution_index):
        return RebalanceMapping(
            scheduled_date=scheduled_date,
            mapped_date=None,
            status="skipped",
            reason="no_later_executable_date",
        )
    mapped_date = pd.Timestamp(execution_index[position])
    if not include_terminal_rebalance and mapped_date == terminal_date:
        return RebalanceMapping(
            scheduled_date=scheduled_date,
            mapped_date=None,
            status="skipped",
            reason="terminal_rebalance_disabled",
        )
    reason: RebalanceMappingReason = (
        "mapped_same_date" if mapped_date == scheduled_date else "mapped_next_executable_date"
    )
    return RebalanceMapping(
        scheduled_date=scheduled_date,
        mapped_date=mapped_date,
        status="mapped",
        reason=reason,
    )
