import math


def safe_divide(numerator: int | float, denominator: int | float) -> int | float:
    """
    Divide numbers, preserving a useful integer result on float overflow.

    Use normal division whenever possible. If converting a very large integer
    numerator to float overflows, round the exact quotient to the nearest
    integer, with ties to even. The fallback returns an int and therefore does
    not preserve fractional precision.

    Args:
        numerator: Dividend.
        denominator: Divisor.

    Returns:
        The normal division result, or a rounded integer when float conversion
        of an integer numerator overflows.

    Raises:
        ZeroDivisionError: If the denominator is zero.
        OverflowError: If the quotient cannot be represented by the fallback.
    """
    if denominator == 0:
        raise ZeroDivisionError('division by zero')

    try:
        return numerator / denominator
    except OverflowError:
        if not isinstance(numerator, int) or isinstance(numerator, bool):
            raise

        if isinstance(denominator, int):
            divisor_numerator, divisor_denominator = denominator, 1
        elif math.isfinite(denominator):
            divisor_numerator, divisor_denominator = denominator.as_integer_ratio()
        else:
            raise

        # Integer arithmetic avoids converting either large operand to float.
        dividend = abs(numerator) * divisor_denominator
        divisor = abs(divisor_numerator)
        whole, remainder = divmod(dividend, divisor)
        comparison = 2 * remainder - divisor
        if comparison > 0 or (comparison == 0 and whole % 2):
            whole += 1
        return -whole if (numerator < 0) != (denominator < 0) else whole
