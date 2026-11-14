"""
Discover local IPv4 addresses and devices using network routing and ARP.
"""

import socket
from collections.abc import Iterable

from scapy.layers.l2 import ARP, Ether
from scapy.sendrecv import srp


def find_ip_by_mac(mac_addresses: Iterable[str], timeout: float = 3) -> dict[str, str]:
    """
    Find IPv4 addresses associated with the requested MAC addresses.

    Broadcast an ARP request across the /24 subnet inferred from the local
    IPv4 address. MAC address matching is case-insensitive, but the returned
    dictionary uses the original input strings as keys. Devices outside that
    subnet, or devices that do not respond to ARP, are not discovered.

    Args:
        mac_addresses: MAC addresses to look up.
        timeout: Number of seconds to wait for ARP responses.

    Returns:
        Mapping from matched input MAC addresses to discovered IPv4 addresses.
        Unmatched addresses are omitted. An empty input returns an empty mapping
        without performing a network scan.
    """
    mac_addresses: list[str] = list(mac_addresses)
    if len(mac_addresses) == 0:
        # Don't do any work if there are no MAC addresses to look up
        return {}

    my_ip = get_local_ip()
    ip_parts = my_ip.split('.')
    ip_range = f'{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0/24'

    # Create an ARP request packet inside an Ethernet broadcast frame
    arp_request = ARP(pdst=ip_range)
    broadcast_frame = Ether(dst='ff:ff:ff:ff:ff:ff')
    packet = broadcast_frame / arp_request

    # Send the packet and capture responses
    answered_list = srp(packet, timeout=timeout, verbose=False)[0]

    result: dict[str, str] = {}
    for target_mac_addr in mac_addresses:
        target_mac_addr_lower = target_mac_addr.lower()
        for _, received in answered_list:
            host_ip = received.psrc
            host_mac = received.hwsrc.lower()
            if host_mac == target_mac_addr_lower:
                result[target_mac_addr] = host_ip
    return result


def get_local_ip() -> str:
    """
    Determine the local IPv4 address selected for an outbound UDP route.

    Connecting a UDP socket to 8.8.8.8:80 selects a local interface without
    sending application data or establishing a connection. This does not
    necessarily identify the interface used for every local network.

    Returns:
        The selected local IPv4 address, or '192.168.1.1' if the socket
        operation raises an OSError.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not actually establish a connection; used to find routing path IP
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except IOError:
        ip = '192.168.1.1'  # Fallback if offline
    finally:
        s.close()
    return ip
