"""
This module provides access to local configuration variables.

Local configuration variables are {variable} = {value} pairs that
are defined externally to CK for the purposes of adapting
to the local environment that CK is installed in. Local
configuration variables are not expected to modify the
behaviour of algorithms implemented in CK.

The primary method to access local configuration is `get`. Various
other getter methods wrap `get`.

The `get` method will search for a value for a requested variable
using the following steps.

1) Check the `programmatic config` which is a dictionary that
can be directly updated.

2) Check the PYTHONPATH for a module called `local_config` (i.e., a
`local_config.py` file) for global variables defined in that module.

3) Check the system environment variables (`os.environ`).

Variable names must be a valid Python identifier. Only valid
value types are supported, as per the function `valid_value`.

Usage:
    from {...}.local_config_help import config

    # assume `local_config.py` is in the PYTHONPATH and contains:
    #    ABC = 123
    #    DEF = 456

    val = config.ABC                  # val = 123
    val = config.XYZ                  # will raise an exception
    val = config.get('ABC')           # val = 123
    val = config['DEF']               # val = 456
    val = config['XYZ']               # will raise an exception
    val = config.get('XYZ')           # val = None
    val = config.get('XYZ', 999)      # val = 999

    from {...}.local_config import get_params

    val = get_params('ABC')                  # val = ('ABC', 123)
    val = get_params('ABC', 'DEF')           # val = (('ABC', 123), ('DEF', 456))
    val = get_params('ABC', 'DEF', sep='=')  # val = ('ABC=123', 'DEF=456')
    val = get_params('ABC;DEF', delim=';')   # val = 'ABC=123;DEF=456'

"""

import inspect
import os
from ast import literal_eval
from itertools import chain
from collections.abc import Iterable, Sequence
from typing import Any

try:
    # Try to import the user's `local_config.py`
    import local_config as _local_config
except ImportError:
    _local_config = None

# Sentinel object
_NIL = object()


class Config:

    def __init__(self) -> None:
        self._programmatic_config: dict[str, Any] = {}

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get the value of the given local configuration variable.
        If the configuration variable is not available, return the given default value.
        """
        if not key.isidentifier():
            raise KeyError(f'invalid local configuration parameter: {key!r}')

        # Check the programmatic config
        value = self._programmatic_config.get(key, _NIL)
        if value is not _NIL:
            return value

        # Check config.py
        if _local_config is not None:
            value = vars(_local_config).get(key, _NIL)
            if value is not _NIL:
                if not valid_value(value):
                    raise KeyError(f'user configuration file contains an invalid value for variable: {key!r}')
                return value

        # Check the OS environment
        value = os.environ.get(key, _NIL)
        if value is not _NIL:
            return value

        # Not found - return the default value
        return default

    def __contains__(self, key: str) -> bool:
        return self.get(key, _NIL) is not _NIL

    def __setitem__(self, key: str, value: Any) -> None:
        """
        Programmatically overwrite a local configuration variable.
        """
        if not key.isidentifier():
            raise KeyError(f'invalid local configuration parameter: {key!r}')
        if not valid_value(value):
            raise ValueError(f'invalid local configuration parameter value: {value!r}')
        self._programmatic_config[key] = value

    def __getitem__(self, key: str) -> Any:
        """
        Get the value of the given configuration variable.
        If the configuration variable is not available, raise a KeyError.
        """
        value = self.get(key, _NIL)
        if value is _NIL:
            raise KeyError(f'undefined local configuration parameter: {key}')
        return value

    def __getattr__(self, key: str) -> Any:
        """
        Get the value of the given configuration variable.
        If the configuration variable is not available, raise a KeyError.
        """
        value = self.get(key, _NIL)
        if value is _NIL:
            raise KeyError(f'undefined local configuration parameter: {key}')
        return value


# The global local config object.
config = Config()


def valid_value(value: Any) -> bool:
    """
    Does the given value have an acceptable type for
    a configuration variable?
    """
    if isinstance(value, (list, tuple, set)):
        return all(valid_value(elem) for elem in value)
    if isinstance(value, dict):
        return all(valid_value(elem) for elem in chain(value.keys(), value.values()))
    if callable(value) or inspect.isfunction(value) or inspect.ismodule(value):
        return False
    # All tests pass
    return True


def get_params(
        *keys: str,
        sep: str | None = None,
        delim: str | None = None,
        local_config: Config = config,
) -> str | tuple[tuple[str, Any], ...] | tuple[str, ...] | tuple[str, Any]:
    """
    Return one or more configuration parameter as key-value pairs.

    If `sep` is None then each key-value pair is returned as a tuple, otherwise
    each key-value pair is returned as a string with `sep` as the separator.

    If `delim` is None then each key is treated as is. If one key is provided then
    its value is returned. If multiple keys are provided, then multiple values
    are returned in a tuple.

    If `delim` is not None, then keys are split using `delim`, and results
    are returned as a single string with `delim` as the delimiter. If
    `delim` is not None then the default value for `sep` is '='.

    For example, assume `config.py` contains: `ABC = 123` and `DEF = 456`,
    then::

        get_params('ABC') -> ('ABC', 123)
        get_params('ABC', 'DEF') -> ('ABC', 123), ('DEF', 456)
        get_params('ABC', sep='=') = 'ABC=123'
        get_params('ABC', 'DEF', sep='=') = 'ABC=123', 'DEF=456'
        get_params('ABC;DEF', delim=';') = 'ABC=123;DEF=456'
        get_params('ABC;DEF', sep='==', delim=';') = 'ABC==123;DEF==456'

    Args:
        keys: the names of variables to access.
        sep: the separator character between {variable} and {value}.
        delim: the delimiter character between key-value pairs.
        local_config: a Config instance to update. Default is the global `config` object.

    Returns:
        the requested parameter values.
    """
    if delim is not None:
        keys = (elem for iterable in (key.split(delim) for key in keys) for elem in iterable)
        if sep is None:
            sep = '='

    if sep is None:
        items = ((key, local_config[key]) for key in keys)
    else:
        items = (f'{key}{sep}{local_config[key]!r}' for key in keys)

    if delim is None:
        result = tuple(items)
        if len(result) == 1:
            result = result[0]
    else:
        result = delim.join(str(item) for item in items)

    return result


def update_config(
        argv: Sequence[str],
        valid_keys: Iterable[str] | None = None,
        *,
        sep: str = '=',
        strip_whitespace: bool = True,
        local_config: Config = config,
) -> None:
    """
    Programmatically overwrite a local configuration variable from a command line `argv`.

    Variable values are interpreted as per a Python literal.

    Example usage:
        import sys
        from {...}.local_config import update_config

        def main():
            ...

        if __name__ == '__main__':
            update_config(sys.argv, ['in_name', 'out_name'])
            main()

    Args:
        argv: a collection of strings in the form '{variable}={value}'.
            Variables not in `valid_keys` will raise a ValueError.
        valid_keys: an optional collection of strings that are valid variables to
            process from argv, or None to accept all variables.
        sep: the separator character between {variable} and {value}.
            Defaults is '='.
        strip_whitespace: If True, then whitespace is stripped from
            the value before updating the config. Whitespace is always stripped
            from the variable name.
        local_config: a Config instance to update. Default is the global config.
    """
    if valid_keys is not None:
        valid_keys = set(valid_keys)

    for arg in argv:
        var_val = str(arg).split(sep, maxsplit=1)
        if len(var_val) != 2:
            raise ValueError(f'cannot split argument: {arg!r} using separator {sep!r}')

        var, val = var_val
        var = var.strip()
        if strip_whitespace:
            val = val.strip()

        if valid_keys is not None and var not in valid_keys:
            raise KeyError(f'invalid key: {arg!r}')

        try:
            interpreted = literal_eval(val)
        except (ValueError, SyntaxError) as err:
            # Some operating systems strip quotes off
            # strings, so we try to recover.
            if '"' in val or "'" in val:
                # Too hard... forget it.
                raise err
            interpreted = str(val)

        local_config[var] = interpreted
