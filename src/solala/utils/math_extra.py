def safe_divide(numerator: int | float, denominator: int | float) -> int | float:
    """
    TODO
    """
    if numerator == 0:
        return 0

    if isinstance(numerator, int):
        try:
            return numerator / denominator
        except OverflowError:
            fraction = (numerator % denominator) / denominator
            whole = numerator // denominator
            if fraction < -0.5:
                whole -= 1
            elif fraction > 0.5:
                whole += 1
            return whole

    return numerator / denominator
