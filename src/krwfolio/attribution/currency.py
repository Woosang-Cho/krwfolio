def split_base_return(local_return: float, fx_return: float) -> tuple[float, float, float]:
    cross = local_return * fx_return
    return local_return, fx_return, cross

