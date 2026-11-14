from collections.abc import Mapping


def dict_merge[K, V](*dicts: Mapping[K, V]) -> dict[K, V]:
    """
    Merge mappings from left to right into a new dictionary.

    When a key occurs in multiple mappings, the value from the last mapping
    containing that key will be used. The input mappings are not modified.

    Args:
        *dicts: Mappings to merge, in order of increasing precedence.

    Returns:
        A new dictionary containing the merged key-value pairs.
    """
    result: dict[K, V] = {}
    for mapping in dicts:
        result.update(mapping)
    return result
