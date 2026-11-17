import asyncio
import unittest
from unittest.mock import patch

from solala.delegates.power_controller.dummy_power_controller.dummy_power_controller import DummyPowerController
from solala.delegates.power_consumer.tuya_power_consumer.tuya_power_consumer import TuyaPowerConsumer


class DelegateRegisterBankTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify stable register banks and independently bound register getters.
    """

    async def test_dummy_controller_registers_read_their_own_fields(self) -> None:
        controller = DummyPowerController(
            inverter_limit=8000, house_power=2000,
            max_charge_param=3000, max_discharge_param=3000,
        )
        bank = await controller.get_registers()
        info = controller.get_connection_info()
        self.assertEqual(await bank['connection'].get(), info['connection'])
        self.assertEqual(await bank['house_power'].get(), info['house_power'])
        self.assertEqual(await bank['inverter_limit'].get(), info['inverter_limit'])
        self.assertIs(await controller.get_registers(), bank)

    async def test_tuya_concurrent_discovery_reuses_one_bank(self) -> None:
        consumer = object.__new__(TuyaPowerConsumer)
        consumer._register_bank = None
        consumer._register_bank_lock = asyncio.Lock()
        started = asyncio.Event()
        release = asyncio.Event()
        discoveries = 0

        async def discover(_self):
            nonlocal discoveries
            discoveries += 1
            started.set()
            await release.wait()
            yield 'cur_power', float
            yield 'switch_1', bool

        with patch.object(TuyaPowerConsumer, '_get_register_keys', discover):
            first = asyncio.create_task(consumer.get_registers())
            await asyncio.wait_for(started.wait(), timeout=1)
            second = asyncio.create_task(consumer.get_registers())
            try:
                await asyncio.sleep(0)
            finally:
                release.set()
            bank1, bank2 = await asyncio.gather(first, second)
            self.assertIs(bank1, bank2)
            self.assertIs(await consumer.get_registers(), bank1)
            self.assertEqual(discoveries, 1)
            self.assertEqual(set(bank1), {'cur_power', 'switch_1'})


if __name__ == '__main__':
    unittest.main()
