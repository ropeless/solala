"""Discover Tuya devices and read a smart plug's status over the LAN.

Set TUYA_LOCAL_IP, TUYA_LOCAL_DEVICE_ID, TUYA_LOCAL_KEY, and
TUYA_LOCAL_VERSION in your untracked local_config.py.

The local key is never printed. The demo does not change device state.
"""

import tinytuya

from solala.utils.local_config_help import config


def main() -> None:
    """Discover local Tuya devices and read the configured plug's status."""
    tinytuya.deviceScan()

    device = tinytuya.OutletDevice(
        config.TUYA_LOCAL_DEVICE_ID,
        config.TUYA_LOCAL_IP,
        config.TUYA_LOCAL_KEY,
    )
    device.set_version(float(config.TUYA_LOCAL_VERSION))
    device.set_socketTimeout(5)
    device.set_socketPersistent(False)
    try:
        status = device.status()
        print(status)
        if isinstance(status, dict) and "Error" in status:
            raise RuntimeError("Local Tuya status request failed")
    finally:
        device.close()


if __name__ == "__main__":
    main()
