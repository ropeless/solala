import json
import re
from typing import TypeAlias, Dict, List, Optional, Mapping

# Define the recursive JSON value type
JSONValue: TypeAlias = str | int | float | bool | None | List["JSONValue"] | Dict[str, "JSONValue"]

# The explicit types for JSON containers
JSONDict: TypeAlias = Dict[str, JSONValue]
JSONList: TypeAlias = List[JSONValue]
JSONContainer: TypeAlias = JSONDict | JSONList

_LINE_ENDINGS_PATTERN = re.compile(r'[,{} \t]*\s*(?=\n|$)')
_BLANK_LINES_PATTERN = re.compile(r'^[ \t]*\r?\n', flags=re.MULTILINE)
_DICT_ENTRY_SEPARATOR_PATTERN = re.compile(r'(\s*[\w+"]): ')


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


def follow_json(data: JSONDict, path: Optional[str]) -> JSONValue:
    """
    Follow a path through a JSON dictionary.

    Returns:
         the value (if the path exists).
    Raises:
        KeyError if the path does not exist in `data`.
    """
    if path:
        parts = path.split('/')
        for i, part in enumerate(parts):
            if part not in data:
                raise KeyError('/'.join(parts[:i + 1]))
            data = data[part]
    return data


def filter_json(data: JSONDict, match: Optional[str]) -> JSONDict:
    """
    Filter a JSON dictionary by keys containing a given substring.
    """
    if match is None:
        return data
    else:
        return {
            key: value
            for key, value in data.items()
            if match in key
        }


def render_json(
        value: JSONValue,
        *,
        indent: int = 2,
        float_format: str = '.2g',
        units: Optional[Mapping[str, str]] = None,
        remove_key_underscores: bool = True,
        remove_value_underscores: bool = True,
) -> str:
    """
    Custom function to render JSON data as a formatted string for a human to read.

    Args:
        value: The value to stringify.
        indent: Indentation used for dictionaries and lists.
        float_format: Format string for floats.
        units: A lookup table of units to append to values.
        remove_key_underscores: if true, remove underscores from keys.
        remove_value_underscores: if true, remove underscores from values.
    Returns:
        JSON value rendered as a string.
    """
    if units is None:
        units = {}

    # Replace floats with formatted strings, add units, remove underscores.
    data = _stringify_values(
        key=None,
        value=value,
        float_format=float_format,
        units=units,
        remove_key_underscores=remove_key_underscores,
        remove_value_underscores=remove_value_underscores,
    )

    text = json.dumps(data, indent=indent)
    text = _LINE_ENDINGS_PATTERN.sub('', text)
    text = _BLANK_LINES_PATTERN.sub('', text)
    text = _DICT_ENTRY_SEPARATOR_PATTERN.sub(r'\1 = ', text)

    text = text.replace('"', '')

    return text


def _stringify_values(
        key: Optional[str],
        value: JSONValue,
        float_format: str,
        units: Mapping[str, str],
        remove_key_underscores: bool,
        remove_value_underscores: bool,
) -> JSONValue:
    """
    If `value` is a number, return a string rendering of it, including appending units if
    the key is in the `units` dictionary.
    If `value` is a container, return a copy with the items recursively stringified.

    Args:
        key: The key for this value - used to look up units.
        value: The value to stringify.
        float_format: Format string for floats.
        units: A lookup table of units to append to values.
        remove_key_underscores: if true, remove underscores from keys.
        remove_value_underscores: if true, remove underscores from values.
    Returns:
        transformed JSON value.
    """
    # Recursive cases: dictionary and list.
    if isinstance(value, dict):
        if remove_key_underscores:
            key_f = _remove_underscores
        else:
            key_f = lambda k: k

        return {
            key_f(k): _stringify_values(k, v, float_format, units, remove_key_underscores, remove_value_underscores)
            for k, v in value.items()
        }
    elif isinstance(value, list):
        return [
            _stringify_values(None, v, float_format, units, remove_key_underscores, remove_value_underscores)
            for v in value
        ]

    # Stringify values
    value_str: str
    if isinstance(value, float):
        value_str = f'{value:{float_format}}'.rstrip('0').rstrip('.')
    elif isinstance(value, bool):
        # Always show booleans in lower case
        value_str = str(value).lower()
    else:
        value_str = str(value)

    # Add units.
    # noinspection PyTypeChecker
    unit_str: Optional[str] = units.get(key)
    if unit_str is not None:
        value_str += unit_str

    # Remove underscores
    if remove_value_underscores:
        value_str = _remove_underscores(value_str)

    return value_str


def _remove_underscores(value: str) -> str:
    return value.replace('_', ' ')
