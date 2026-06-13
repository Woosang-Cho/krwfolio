import pandas as pd


def union_calendar(*indexes: pd.DatetimeIndex) -> pd.DatetimeIndex:
    result = pd.DatetimeIndex([])
    for index in indexes:
        result = result.union(index)
    return result.sort_values()

