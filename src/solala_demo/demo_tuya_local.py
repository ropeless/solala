import asyncio
from pprint import pprint
from time import monotonic

from solala.delegates.power_consumer.tuya_local_power_consumer.tuya_local_power_consumer import TuyaLocalPowerConsumer
from solala.utils.local_config_help import config


async def main() -> None:
    """
    Exercise the Tuya LAN consumer without changing the plug state.
    """
    consumer = TuyaLocalPowerConsumer(
        config.TUYA_LOCAL_HOST,
        config.TUYA_LOCAL_DEVICE_ID,
        config.TUYA_LOCAL_KEY,
        version=float(config.TUYA_LOCAL_VERSION),
        calibration_factor=0.8,
        cache_duration=0.1,
    )

    # Count physical requests without printing credentials or raw device configuration.
    request = consumer._request
    request_count = 0

    def counted_request(switch: bool | None = None) -> dict:
        nonlocal request_count
        request_count += 1
        return request(switch)

    consumer._request = counted_request

    try:
        print('Consumer status (calibrated):')
        pprint(await consumer.get_status())
        print('Diagnostic registers:')
        bank = await consumer.get_registers()
        before = request_count
        start = monotonic()
        pprint(await bank.get_register_values())
        print(f'Register scan: {request_count - before} LAN requests in {monotonic() - start:.3f}s')

        # Wait for the cache to expire before measuring the next experiment.
        await asyncio.sleep(0.2)
        before = request_count
        await asyncio.gather(consumer.get_status(), consumer.get_status())
        print(f'Concurrent status reads: {request_count - before} LAN requests (expected 1)')

        await asyncio.sleep(0.2)
        before = request_count
        await consumer.get_status()
        await asyncio.sleep(0.2)
        await consumer.get_status()
        print(f'Separated status reads: {request_count - before} LAN requests (expected 2)')
        print(f'Total LAN requests: {request_count}')
        print('Read-only test complete; no switch commands sent.')
    finally:
        await consumer.close()


if __name__ == '__main__':
    asyncio.run(main())
