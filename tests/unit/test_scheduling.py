import pandas as pd

from krwfolio.core.scheduling import build_rebalance_plan


def test_scheduler_maps_same_executable_date():
    valuation_index = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-29"])
    execution_index = valuation_index

    plan = build_rebalance_plan(
        valuation_index,
        execution_index,
        "monthly",
        include_terminal_rebalance=False,
        first_execution_date=valuation_index[0],
    )

    assert [date.strftime("%Y-%m-%d") for date in plan.scheduled_dates] == ["2024-02-29"]
    assert [date.strftime("%Y-%m-%d") for date in plan.mapped_dates] == ["2024-02-29"]
    assert plan.mappings[0].reason == "mapped_same_date"


def test_scheduler_maps_to_next_executable_date():
    valuation_index = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-01", "2024-03-29"])
    execution_index = pd.to_datetime(["2024-01-31", "2024-03-01", "2024-03-29"])

    plan = build_rebalance_plan(
        valuation_index,
        execution_index,
        "monthly",
        include_terminal_rebalance=False,
        first_execution_date=valuation_index[0],
    )

    assert [date.strftime("%Y-%m-%d") for date in plan.scheduled_dates] == ["2024-02-29"]
    assert [date.strftime("%Y-%m-%d") for date in plan.mapped_dates] == ["2024-03-01"]
    assert plan.mappings[0].reason == "mapped_next_executable_date"


def test_scheduler_skips_mapping_to_terminal_date_when_disabled():
    valuation_index = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-01"])
    execution_index = pd.to_datetime(["2024-01-31", "2024-03-01"])

    plan = build_rebalance_plan(
        valuation_index,
        execution_index,
        "monthly",
        include_terminal_rebalance=False,
        first_execution_date=valuation_index[0],
    )

    assert [date.strftime("%Y-%m-%d") for date in plan.skipped_dates] == ["2024-02-29"]
    assert plan.mappings[0].reason == "terminal_rebalance_disabled"


def test_scheduler_skips_when_no_later_executable_date_exists():
    valuation_index = pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-01"])
    execution_index = pd.to_datetime(["2024-01-31"])

    plan = build_rebalance_plan(
        valuation_index,
        execution_index,
        "monthly",
        include_terminal_rebalance=False,
        first_execution_date=valuation_index[0],
    )

    assert [date.strftime("%Y-%m-%d") for date in plan.skipped_dates] == ["2024-02-29"]
    assert plan.mappings[0].reason == "no_later_executable_date"
