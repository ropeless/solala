import inspect
import json
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from datetime import datetime, date, timedelta
from enum import Enum
from itertools import chain
from types import NoneType
from typing import Any

from pydantic import BaseModel

from solala.utils.time_extras import render_timedelta

# Non-container JSON value types
type JSONPrimitive = str | int | float | bool | None

# Define the recursive JSON value type
type JSONValue = JSONPrimitive | Sequence[JSONValue] | Mapping[str, JSONValue]

# The explicit types for JSON containers
type JSONDict = Mapping[str, JSONValue]
type JSONList = Sequence[JSONValue]
type JSONContainer = JSONDict | JSONList


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
    Render JSON-compatible values as readable, indented text.

    Dictionaries use key = value, with key: for nested dictionaries.
    Key quoting is determined before underscores are replaced with spaces.
    Empty dictionaries are omitted recursively; empty lists are retained.
    Tuples render as lists. Lists with at most nine scalar elements use
    one line unless a string contains a comma or square bracket, or its
    rendered length exceeds 20 characters. Other lists use one-based
    numbered entries. Units apply to numeric dictionary values at any
    depth, using original keys, but never to booleans.

    Args:
        value: JSON-compatible value to render.
        indent: Spaces per nesting level.
        float_format: Python format specification for nonintegral floats.
        units: Optional mapping from original keys to numeric unit suffixes.
        remove_key_underscores: Replace underscores in displayed keys.
        remove_value_underscores: Replace underscores in string values.
        ensure_ascii: Escape non-ASCII characters in displayed strings.

    Returns:
        Human-readable text, or an empty string for an empty dictionary.
    """
    unit_map = units if units is not None else {}
    spacing = ' ' * indent

    def quoted(text: str) -> str:
        quote = '"' if "'" in text else "'"
        if ensure_ascii:
            escaped = json.dumps(text, ensure_ascii=True)[1:-1]
            if quote == "'":
                escaped = escaped.replace('\\"', '"')
        else:
            escaped = text.replace('\\', '\\\\')
            escaped = escaped.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
        if quote == '"' and not ensure_ascii:
            escaped = escaped.replace('"', '\\"')
        return f'{quote}{escaped}{quote}'

    def display_key(key: str) -> str:
        text = key.replace('_', ' ') if remove_key_underscores else key
        if (not key or any(char.isspace() for char in key)
                or ': ' in key or ' = ' in key):
            return quoted(text)
        return text

    def scalar(item: JSONPrimitive, key: str | None = None) -> str:
        if item is None:
            return 'none'
        if isinstance(item, bool):
            return 'true' if item else 'false'
        if isinstance(item, str):
            text = item.replace('_', ' ') if remove_value_underscores else item
            return quoted(text)
        if isinstance(item, float):
            if item.is_integer() and 'e' not in str(item).lower():
                text = str(int(item))
            else:
                text = format(item, float_format)
                if '.' in text and 'e' not in text.lower():
                    text = text.rstrip('0').rstrip('.')
                if text == '-0':
                    text = '0'
                if text == '0' and abs(item) > 1e-7:
                    text = format(item, '.2g')
        else:
            text = str(item)
        return text + unit_map.get(key, '') if key is not None else text

    def visible(item: JSONValue) -> bool:
        if isinstance(item, Mapping):
            return any(visible(child) for child in item.values())
        return True

    def simple(items: Sequence[JSONValue]) -> bool:
        if len(items) > 9:
            return False
        for item in items:
            if isinstance(item, (Mapping, Sequence)) and not isinstance(item, str):
                return False
            if isinstance(item, str):
                if any(char in item for char in ',[]') or len(scalar(item)) > 20:
                    return False
        return True

    def render(item: JSONValue, level: int, key: str | None = None) -> str:
        if isinstance(item, Mapping):
            lines: list[str] = []
            for child_key, child in item.items():
                if not visible(child):
                    continue
                label = display_key(child_key)
                if isinstance(child, Mapping):
                    lines.append(f'{spacing * (level + 1)}{label}:')
                    lines.append(render(child, level + 1))
                else:
                    prefix = f'{spacing * (level + 1)}{label} = '
                    lines.append(prefix + render(child, level + 1, child_key))
            return '\n'.join(lines)

        if isinstance(item, Sequence) and not isinstance(item, str):
            if simple(item):
                return '[' + ', '.join(scalar(child) for child in item) + ']'
            lines = ['[']
            for index, child in enumerate(item, 1):
                if not visible(child):
                    continue
                prefix = f'{spacing * (level + 1)}{index}:'
                if isinstance(child, Mapping):
                    lines.append(prefix)
                    lines.append(render(child, level + 1))
                else:
                    lines.append(prefix + ' ' + render(child, level + 1))
            lines.append(f'{spacing * level}]')
            return '\n'.join(lines)

        return scalar(item, key)

    return render(value, 0)


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
    Enum values are represented by their names; `date`, `datetime`, and
    `timedelta` objects are formatted as strings.

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
        elif isinstance(value, timedelta):
            result[name] = render_timedelta(value)
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


def _remove_underscores(value: str) -> str:
    """
    Replace underscores with spaces in display text.

    Args:
        value: Text to transform.

    Returns:
        Text with underscores replaced by spaces.
    """
    return value.replace('_', ' ')
