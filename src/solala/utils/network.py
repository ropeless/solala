import socket
from typing import Iterable, Dict, List

from scapy.layers.l2 import ARP, Ether
from scapy.sendrecv import srp


def find_ip_by_mac(mac_addresses: Iterable[str], timeout=3) -> Dict[str, str]:
    """
    Scans the local network for specific MAC addresses and returns a mapping to their IP addresses.
    """
    mac_addresses: List[str] = list(mac_addresses)
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

    result: Dict[str, str] = {}
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
    Dynamically fetches the local IP address of this machine.
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
