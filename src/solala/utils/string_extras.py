"""
Provide string parsing helpers for device connection settings.
"""

import re

_ADDRESS_DELIMITERS_PATTERN = re.compile(r'[,;&\s]+')


def split_addresses(addresses: str) -> list[str]:
    """
    Split a device address string on common separators.

    Commas, semicolons, ampersands, and consecutive whitespace characters
    are treated as delimiters. Leading or trailing delimiters can produce
    empty strings; this function does not remove them.

    Args:
        addresses: String containing one or more device addresses.

    Returns:
        Address substrings in their original order, including any empty
        substrings produced by leading or trailing delimiters.
    """
    return _ADDRESS_DELIMITERS_PATTERN.split(addresses)
