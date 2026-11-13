import re

_ADDRESS_DELIMITERS_PATTERN = re.compile(r"[,;&\\s]+")


def split_addresses(addresses: str) -> list[str]:
    """
    Split addresses separated by commas, semicolons, ampersands, or whitespace.

    Helper for connecting to devices.
    """
    return _ADDRESS_DELIMITERS_PATTERN.split(addresses)
