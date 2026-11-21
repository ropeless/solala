"""Discover Tuya devices and read a plug's status over the LAN.

Install: python -m pip install tinytuya
Discover: python demo/tuya_local.py --scan
Read: python demo/tuya_local.py --ip 192.168.0.X --device-id ID --version 3.3

The local key is requested interactively and is never printed or stored.
"""

import argparse
from getpass import getpass

import tinytuya


def main() -> None:
    """Discover devices or retrieve a single device's status."""
    parser = argparse.ArgumentParser(description="Read Tuya smart plug status over LAN")
    parser.add_argument("--scan", action="store_true", help="Discover Tuya devices")
    parser.add_argument("--ip", help="Plug's LAN IP address")
    parser.add_argument("--device-id", help="Tuya device ID")
    parser.add_argument("--version", type=float, help="Protocol version from scan (e.g. 3.3)")
    args = parser.parse_args()

    if args.scan:
        tinytuya.deviceScan()
        return

    if not all((args.ip, args.device_id, args.version)):
        parser.error("Provide --scan or all of --ip, --device-id and --version")

    local_key = getpass("Tuya local key: ")
    device = tinytuya.OutletDevice(args.device_id, args.ip, local_key)
    device.set_version(args.version)
    device.set_socketTimeout(5)
    device.set_socketPersistent(False)
    try:
        status = device.status()
        print(status)
        if isinstance(status, dict) and "Error" in status:
            raise SystemExit("Local status request failed")
    finally:
        device.close()


if __name__ == "__main__":
    main()
