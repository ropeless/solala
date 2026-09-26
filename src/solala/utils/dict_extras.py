from typing import TypeVar, Mapping, Dict

_K = TypeVar('_K')
_V = TypeVar('_V')


def dict_merge(*dicts: Mapping[_K, _V]) -> Dict[_K, _V]:
    result: Dict[_K, _V] = {}
    for d in dicts:
        result.update(d)
    return result
