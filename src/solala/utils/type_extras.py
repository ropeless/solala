import math


def check_str(value: object) -> str:
    """
    Validate and return a string value.

    Args:
        value: Value to check.

    Returns:
        The string value.

    Raises:
        TypeError: If the value is not a string.
    """
    if isinstance(value, str):
        return value
    else:
        raise TypeError(f'Expected a string, got {type(value)}')


def check_num(value: object) -> int | float:
    """
    Validate and return a numeric value.

    Booleans are not accepted, even though `bool` subclasses `int`.

    Args:
        value: Value to check.

    Returns:
        The integer or float value.

    Raises:
        TypeError: If the value is not numeric.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    else:
        raise TypeError(f'Expected a number, got {type(value)}')


def check_finite(value: object) -> int | float:
    """
    Validate and return a numeric value that is finite.

    Booleans are not accepted, even though `bool` subclasses `int`.

    Args:
        value: Value to check.

    Returns:
        The integer or float value.

    Raises:
        TypeError: If the value is not a finite numeric.
    """
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError(f'_Expected a finite number, got {value}')
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise TypeError(f'Expected a finite number, got {type(value)}')


def check_non_negative(value: object) -> int | float:
    """
    Validate and return a numeric value that is finite and non-negative.

    Booleans are not accepted, even though `bool` subclasses `int`.

    Args:
        value: Value to check.

    Returns:
        The integer or float value.

    Raises:
        TypeError: If the value is not a finite, non-negative numeric.
    """
    number = check_finite(value)
    if number >= 0:
        return number
    raise TypeError(f'Expected a finite non-negative number, got {value}')


def check_bool(value: object) -> bool:
    """
    Validate and return a boolean value.

    Args:
        value: Value to check.

    Returns:
        The boolean value.

    Raises:
        TypeError: If the value is not a boolean.
    """
    if isinstance(value, bool):
        return value
    else:
        raise TypeError(f'_Expected a boolean, got {type(value)}')
