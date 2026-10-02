import re
from typing import List

_ADDRESS_DELIMITERS_PATTERN = re.compile(r'[,;&\s]+')


def split_addresses(addresses: str) -> List[str]:
    """
    Split address separated by commas, semicolons, ampersands, or whitespace.
    Helper for connecting to devices.
    """
    return _ADDRESS_DELIMITERS_PATTERN.split(addresses)


