def transaction_cost(turnover_value: float, bps: float) -> float:
    return abs(turnover_value) * bps / 10_000.0

