from typing import TypeAlias, Dict, List, LiteralString

# Define the recursive JSON value type
JSONValue: TypeAlias = str | int | float | bool | None | List["JSONValue"] | Dict[str, "JSONValue"]

# The explicit type for a JSON dictionary
JSONDict: TypeAlias = Dict[str, JSONValue]


def json_str(value: JSONValue) -> str:
    """
    Get a JSON value that is a string.
    """
    if isinstance(value, str):
        return value
    else:
        raise TypeError(f"Expected a string, got {type(value)}")


def json_num(value: JSONValue) -> int | float:
    """
    Get a JSON value that is a number.
    """
    if isinstance(value, (int, float)):
        return value
    else:
        raise TypeError(f"Expected a number, got {type(value)}")


def json_bool(value: JSONValue) -> bool:
    """
    Get a JSON value that is a boolean.
    """
    if isinstance(value, bool):
        return value
    else:
        raise TypeError(f"Expected a number, got {type(value)}")


def json_dict(value: JSONValue) -> JSONDict:
    """
    Get a JSON value that is a dict.
    """
    if isinstance(value, dict):
        return value
    else:
        raise TypeError(f"Expected a dictionary, got {type(value)}")


