"""Explore a Tapo P110M smart plug using its local LAN interface."""

import argparse
import asyncio
import os

from kasa import Credentials, Discover


async def main() -> None:
    """Connect to the plug, report its features, and optionally switch it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("TAPO_HOST"), help="Reserved LAN IP address")
    parser.add_argument("--action", choices=("status", "on", "off"), default="status")
    args = parser.parse_args()

    if not args.host:
        parser.error("Supply --host or set TAPO_HOST")

    username = os.getenv("TAPO_USERNAME")
    password = os.getenv("TAPO_PASSWORD")
    if not username or not password:
        parser.error("Set TAPO_USERNAME and TAPO_PASSWORD for local authentication")

    device = await Discover.discover_single(
        args.host,
        credentials=Credentials(username, password),
    )
    if device is None:
        raise RuntimeError(f"No supported device found at {args.host}")

    try:
        await device.update()
        print(f"Alias: {device.alias}")
        print(f"Model: {device.model}")
        print(f"On: {device.is_on}")

        if args.action == "on":
            await device.turn_on()
            await device.update()
        elif args.action == "off":
            await device.turn_off()
            await device.update()

        if args.action != "status":
            print(f"On after {args.action}: {device.is_on}")

        print("Available features:")
        for feature_id, feature in sorted(device.features.items()):
            try:
                print(f"  {feature_id}: {feature.value!r}")
            except Exception as exc:
                print(f"  {feature_id}: unavailable ({exc!r})")
    finally:
        await device.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
