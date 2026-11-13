from collections.abc import Mapping


def dict_merge[K, V](*dicts: Mapping[K, V]) -> dict[K, V]:
    """Merge mappings from left to right, with later mappings taking precedence."""
    result: dict[K, V] = {}
    for mapping in dicts:
        result.update(mapping)
    return result
