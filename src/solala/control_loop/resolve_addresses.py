from dataclasses import dataclass

from solala.control_loop.errors import ControlLoopError
from solala.utils.network import find_ip_by_mac


@dataclass
class ResolvedAddress:
    """
    Track an input address and its resolved MAC and IP addresses.
    """
    raw_address: str
    mac_address: str = ''
    ip_address: str = ''


def resolve_addresses(raw_addresses: list[str]) -> list[ResolvedAddress]:
    """
    Resolve MAC or IP addresses to their corresponding IP addresses.

    Args:
        raw_addresses: Input MAC or IP addresses.

    Returns:
        Resolved addresses in the same order as the input.

    Raises:
        ControlLoopError: If an address is invalid or a MAC address cannot be resolved.
    """
    addresses: list[ResolvedAddress] = [ResolvedAddress(address) for address in raw_addresses]
    invalid_addresses: list[str] = []
    # Work out what address are MAC address
    found_mac_addresses: list[str] = []
    for address in addresses:
        raw_address = address.raw_address
        is_mac = ':' in raw_address
        is_ip = '.' in raw_address
        if is_mac and not is_ip:
            address.mac_address = raw_address
            found_mac_addresses.append(raw_address)
        elif is_ip and not is_mac:
            address.ip_address = raw_address
        else:
            invalid_addresses.append(raw_address)

    # Fail if there are any invalid addresses
    if len(invalid_addresses) > 0:
        raise ControlLoopError('invalid address', errors=invalid_addresses)

    # Look up IP address for MAC address
    mac_lookup: dict[str, str] = find_ip_by_mac(found_mac_addresses)
    for address in addresses:
        if address.ip_address == '':
            mac_address = address.mac_address
            ip_address: str | None = mac_lookup.get(mac_address)
            if ip_address is None:
                invalid_addresses.append(mac_address)
            else:
                address.ip_address = ip_address

    # Fail if there are any invalid ip addresses
    if len(invalid_addresses) > 0:
        raise ControlLoopError('could not find IP address for MAC address', errors=invalid_addresses)

    return addresses
