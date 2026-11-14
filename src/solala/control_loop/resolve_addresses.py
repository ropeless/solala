from dataclasses import dataclass

from solala.control_loop.errors import ControlLoopError
from solala.utils.network import find_ip_by_mac


@dataclass
class ResolvedAddress:
    """
    Represent an input address and its resolved network identifiers.

    Attributes:
        raw_address: Original MAC or IP address supplied by the caller.
        mac_address: MAC address, if the input was a MAC address.
        ip_address: Input IP address or the IP address resolved from a MAC address.
    """
    raw_address: str
    mac_address: str = ''
    ip_address: str = ''


def resolve_addresses(raw_addresses: list[str]) -> list[ResolvedAddress]:
    """
    Resolve a sequence of MAC or IP addresses.

    IP address inputs are retained as supplied. MAC address inputs are looked up
    on the local network. The returned objects retain the original input and
    the resolved identifiers.

    Args:
        raw_addresses: Input MAC or IP addresses.

    Returns:
        Resolved addresses in the same order as the input.

    Raises:
        ControlLoopError: If an address has an unsupported format or a MAC
            address cannot be resolved to an IP address.
    """
    addresses: list[ResolvedAddress] = [ResolvedAddress(address) for address in raw_addresses]
    invalid_addresses: list[str] = []
    # Identify MAC and IP address inputs.
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

    # Fail if any MAC addresses could not be resolved.
    if len(invalid_addresses) > 0:
        raise ControlLoopError('could not find IP address for MAC address', errors=invalid_addresses)

    return addresses
