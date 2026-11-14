import inspect
import json
import re
from datetime import datetime, date
from enum import Enum
from itertools import chain
from types import NoneType
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from typing import Any

from pydantic import BaseModel

# Non-container JSON value types
type JSONPrimitive = str | int | float | bool | None

# Define the recursive JSON value type
type JSONValue = JSONPrimitive | Sequence[JSONValue] | Mapping[str, JSONValue]

# The explicit types for JSON containers
type JSONDict = Mapping[str, JSONValue]
type JSONList = Sequence[JSONValue]
type JSONContainer = JSONDict | JSONList

_LINE_ENDINGS_PATTERN = re.compile(r'[,{} \t]*\s*(?=\n|$)')
_BLANK_LINES_PATTERN = re.compile(r'^[ \t]*\r?\n', flags=re.MULTILINE)
_DICT_ENTRY_SEPARATOR_PATTERN = re.compile(r'(\s*[\w+"]): ')


def json_str(value: JSONValue) -> str:
    """
    Validate and return a JSON string value.

    Args:
        value: JSON value to check.

    Returns:
        The string value.

    Raises:
        TypeError: If the value is not a string.
    """
    if isinstance(value, str):
        return value
    else:
        raise TypeError(f"Expected a string, got {type(value)}")


def json_num(value: JSONValue) -> int | float:
    """
    Validate and return a JSON numeric value.

    Booleans are also accepted because `bool` is a subclass of `int`.

    Args:
        value: JSON value to check.

    Returns:
        The integer or float value.

    Raises:
        TypeError: If the value is not numeric.
    """
    if isinstance(value, (int, float)):
        return value
    else:
        raise TypeError(f"Expected a number, got {type(value)}")


def json_bool(value: JSONValue) -> bool:
    """
    Validate and return a JSON boolean value.

    Args:
        value: JSON value to check.

    Returns:
        The boolean value.

    Raises:
        TypeError: If the value is not a boolean.
    """
    if isinstance(value, bool):
        return value
    else:
        raise TypeError(f"Expected a number, got {type(value)}")


def json_dict(value: JSONValue) -> JSONDict:
    """
    Validate and return a JSON mapping.

    Args:
        value: JSON value to check.

    Returns:
        The mapping, without copying it.

    Raises:
        TypeError: If the value is not a mapping.
    """
    if isinstance(value, Mapping):
        return value
    else:
        raise TypeError(f"Expected a dictionary, got {type(value)}")


def follow_json(data: JSONDict, path: str | None) -> JSONValue:
    """
    Follow a slash-separated sequence of keys through a JSON mapping.

    A `None` path returns the original mapping. Path components select
    dictionary keys, not list indices.

    Args:
        data: Mapping from which to start.
        path: Slash-separated key path, or None.

    Returns:
        The value at the selected path.

    Raises:
        KeyError: If a path component is not found.
        TypeError: If an intermediate value is not a mapping.
    """
    if path is not None:
        parts: list[str] = path.split('/')
        for i, part in enumerate(parts):
            if not isinstance(data, (dict, Mapping)):
                raise TypeError('/'.join(parts[:i + 1]))
            if part not in data.keys():
                raise KeyError('/'.join(parts[:i + 1]))
            data = data[part]
    return data


def filter_json(data: JSONDict, match: str | None) -> JSONDict:
    """
    Select top-level entries whose keys contain a substring.

    Args:
        data: Mapping to filter.
        match: Substring to match, or None to return the original mapping.

    Returns:
        A new mapping of matching entries, or the original mapping if
        `match` is None.
    """
    if match is None:
        return data
    else:
        return {
            key: value
            for key, value in data.items()
            if match in key
        }


def flatten(data: JSONContainer, sep: str = '/', prefix: str = '') -> dict[str, JSONPrimitive]:
    """
    Flatten nested JSON mappings and sequences into path-keyed values.

    Sequence indices become string path components. Only leaf values are
    included; empty containers do not produce entries.

    Args:
        data: JSON mapping or sequence to flatten.
        sep: Separator inserted between path components.
        prefix: Prefix prepended to generated keys.

    Returns:
        A dictionary mapping flattened paths to primitive values.

    Raises:
        TypeError: If the top-level value is not a supported container.
    """
    if isinstance(data, (dict, Mapping)):
        return dict(_flatten(data.items(), sep, prefix))
    elif isinstance(data, (list, tuple)):
        return dict(_flatten(enumerate(data), sep, prefix))
    else:
        raise TypeError()


def _flatten(
        data: Iterable[tuple[str | int, JSONValue]],
        sep: str,
        prefix: str,
) -> Iterator[tuple[str, JSONPrimitive]]:
    for key, value in data:
        key = prefix + str(key)
        if isinstance(value, Mapping):
            yield from _flatten(value.items(), sep, key + sep)
        elif isinstance(value, Sequence) and not isinstance(value, str):
            yield from _flatten(enumerate(value), sep, key + sep)
        else:
            yield str(key), value


def render_json(
        value: JSONValue,
        *,
        indent: int = 2,
        float_format: str = '.2g',
        units: Mapping[str, str] | None = None,
        remove_key_underscores: bool = True,
        remove_value_underscores: bool = True,
        ensure_ascii: bool = False,
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
        ensure_ascii: passed to `json.dumps`.
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

    text = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    text = _LINE_ENDINGS_PATTERN.sub('', text)
    text = _BLANK_LINES_PATTERN.sub('', text).rstrip()
    text = _DICT_ENTRY_SEPARATOR_PATTERN.sub(r'\1 = ', text)

    text = text.replace('""', "''")  # empty string ->  ''
    text = text.replace('"', '')

    return text


def to_json(
        thing: object,
        *,
        exclude_names: Collection[str] = (),
        exclude_values: Collection[Any] = (),
        datetime_format: str = '%Y-%m-%d %H:%M:%S',
        date_format: str = '%Y-%m-%d',
) -> JSONDict:
    """
    Extract public attributes and properties into a JSON-compatible mapping.

    Supports Pydantic models, classes, and objects with a `__dict__`.
    Private names, excluded entries, and unsupported value types are skipped.
    Enum values are represented by their names; dates and datetimes are
    formatted as strings.

    Args:
        thing: Object or class whose attributes should be extracted.
        exclude_names: Attribute names to omit.
        exclude_values: Attribute values to omit.
        datetime_format: Format used for datetime values.
        date_format: Format used for date values.

    Returns:
        A mapping of extracted attribute names to converted values.
    """
    return _to_json(thing, exclude_names, exclude_values, datetime_format, date_format)


def _to_json(
        thing: object,
        exclude_names: Collection[str],
        exclude_values: Collection[Any],
        datetime_format: str,
        date_format: str,
) -> JSONDict:
    if isinstance(thing, BaseModel):
        items = thing.__dict__.items()
        exclude_names = set(exclude_names)
        exclude_names.add('model_config')
    elif isinstance(thing, type):
        items = thing.__dict__.items()
    else:
        items = chain(thing.__dict__.items(), thing.__class__.__dict__.items())
    result: dict[str, JSONValue] = {}
    for name, value in items:
        if name in result.keys():
            continue
        if name.startswith('_') or name in exclude_names:
            continue
        if isinstance(value, property):
            value = value.__get__(thing, type(thing))
        if value in exclude_values:
            continue
        if _ignore(value):
            continue

        if isinstance(value, Enum):
            result[name] = value.name
        elif isinstance(value, (int, float, str, bool, NoneType)):
            result[name] = value
        elif isinstance(value, datetime):
            result[name] = value.strftime(datetime_format)
        elif isinstance(value, date):
            result[name] = value.strftime(date_format)
        elif isinstance(value, (Sequence, set, frozenset)):
            result[name] = [
                _to_json(item, exclude_names, exclude_values, datetime_format, date_format)
                for item in value
            ]
        elif isinstance(value, Mapping):
            result[name] = {
                key: _to_json(value, exclude_names, exclude_values, datetime_format, date_format)
                for key, value in value.items()
            }
    return result


def _ignore(value: Any) -> bool:
    """
    Identify runtime objects that should be omitted from JSON extraction.

    Returns:
        True for code, callable, generator, coroutine, and related runtime
        objects that cannot be represented as JSON data.
    """
    return (
            inspect.iscode(value)
            or inspect.isroutine(value)
            or inspect.ismodule(value)
            or inspect.isgenerator(value)
            or inspect.isgeneratorfunction(value)
            or inspect.iscoroutine(value)
            or inspect.iscoroutinefunction(value)
            or inspect.isasyncgen(value)
            or inspect.isasyncgenfunction(value)
            or inspect.isframe(value)
            or inspect.istraceback(value)
    )


def _stringify_values(
        key: str | None,
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
    if isinstance(value, Mapping):
        if remove_key_underscores:
            key_f = _remove_underscores
        else:
            key_f = lambda k: k

        return {
            key_f(k): _stringify_values(k, v, float_format, units, remove_key_underscores, remove_value_underscores)
            for k, v in value.items()
        }
    elif isinstance(value, Sequence) and not isinstance(value, str):
        return [
            _stringify_values(None, v, float_format, units, remove_key_underscores, remove_value_underscores)
            for v in value
        ]

    # Stringify values
    value_str: str
    if isinstance(value, float):
        value_str = f'{value:{float_format}}'
        if '.' in value_str:
            # Clean up trailing zeros and decimal point for rendered float
            value_str = value_str.rstrip('0').rstrip('.')
        if value_str == '-0':
            value_str = '0'
        # Check for misleading formatting
        if value_str == '0' and abs(value) > 0.0000001:
            value_str = f'{value:.2g}'
    elif isinstance(value, bool):
        # Always show booleans in lower case
        value_str = str(value).lower()
    else:
        value_str = str(value)

    # Add units.
    # noinspection PyTypeChecker
    unit_str: str | None = units.get(key)
    if unit_str is not None:
        value_str += unit_str

    # Remove underscores
    if remove_value_underscores:
        value_str = _remove_underscores(value_str)

    return value_str


def _remove_underscores(value: str) -> str:
    """
    Replace underscores with spaces in display text.

    Args:
        value: Text to transform.

    Returns:
        Text with underscores replaced by spaces.
    """
    return value.replace('_', ' ')
