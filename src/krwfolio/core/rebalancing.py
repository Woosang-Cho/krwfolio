import pandas as pd

from krwfolio.portfolio import RebalanceFrequency


def rebalance_dates(
    index: pd.DatetimeIndex,
    frequency: RebalanceFrequency,
    *,
    include_terminal_rebalance: bool = False,
) -> set[pd.Timestamp]:
    if frequency == "none" or len(index) <= 1:
        return set()

    dates: list[pd.Timestamp] = []
    periods = {
        "monthly": index.to_period("M"),
        "quarterly": index.to_period("Q"),
        "yearly": index.to_period("Y"),
    }[frequency]

    for i in range(1, len(index)):
        if periods[i] != periods[i - 1]:
            dates.append(index[i - 1])
    if include_terminal_rebalance:
        dates.append(index[-1])
    return set(dates)
