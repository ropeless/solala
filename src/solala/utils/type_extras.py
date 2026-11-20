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
        raise TypeError(f"Expected a string, got {type(value)}")


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
        raise TypeError(f"Expected a number, got {type(value)}")


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
        raise TypeError(f"Expected a boolean, got {type(value)}")


