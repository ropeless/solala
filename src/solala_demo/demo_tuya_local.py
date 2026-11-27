import asyncio
from pprint import pprint
from time import monotonic

from solala.delegates.power_consumer.tuya_local_power_consumer.tuya_local_power_consumer import TuyaLocalPowerConsumer
from solala.utils.json_extras import JSONDict
from solala.utils.local_config_help import config


SWITCH_TEST: bool = False
INCLUDE_SLEEP: bool = False


async def test_switch(consumer: TuyaLocalPowerConsumer) -> None:
    """
    Switch the unloaded plug off and on, restoring its initial state on failure.
    """
    initial = await consumer.get_status()
    if initial.power != 0 or initial.current != 0:
        raise RuntimeError('Switch test refused: the plug is drawing power')
    if not initial.on:
        raise RuntimeError('Switch test expects the plug to be initially ON')

    print('Switch test: turning OFF')
    try:
        await consumer.set_switch(False)
        if (await consumer.get_status()).on:
            raise AssertionError('Switch remained ON after OFF command')
        print('Switch OFF confirmed')

        if INCLUDE_SLEEP:
            await asyncio.sleep(5)  # helps with visual confirmation

        print('Switch test: turning ON')
        await consumer.set_switch(True)
        if not (await consumer.get_status()).on:
            raise AssertionError('Switch remained OFF after ON command')
        print('Switch ON confirmed; cache invalidation verified')
    finally:
        # A command may have succeeded even if its response was lost.
        # Always attempt to restore the initial ON state.
        try:
            if not (await consumer.get_status()).on:
                await consumer.set_switch(True)
            if not (await consumer.get_status()).on:
                raise RuntimeError('Plug did not return to its initial ON state')
            print('Initial ON state confirmed')
        except Exception as error:
            print(f'WARNING: Could not confirm restoration of initial switch state: {error}')
            raise


async def main() -> None:
    """
    Exercise the Tuya LAN consumer; switch only when explicitly requested.
    """
    if 'TUYA_LOCAL_HOST' not in config:
        print('TUYA_LOCAL_HOST not set')
        return

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

    def counted_request(switch: bool | None = None) -> JSONDict:
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
        if SWITCH_TEST:
            await test_switch(consumer)
    finally:
        await consumer.close()


if __name__ == '__main__':
    asyncio.run(main())
