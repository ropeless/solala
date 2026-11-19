import unittest
from unittest.mock import AsyncMock, Mock, patch

from solala.delegates.power_consumer.dummy_power_consumer.dummy_power_consumer import DummyPowerConsumer
from solala.delegates.power_consumer.tuya_power_consumer.tuya_power_consumer import TuyaPowerConsumer
from solala.register import ReadOnlyError
from solala.settings import DummyConsumerConnection, TuyaConnection


class PowerConsumerContractTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify switching, accumulated energy, and configuration contracts.
    """

    async def test_dummy_switch_and_register(self) -> None:
        consumer = DummyPowerConsumer(current=1, power=120)
        bank = await consumer.get_registers()
        self.assertTrue(consumer.can_switch)
        self.assertTrue(bank['switch'].writable)
        self.assertTrue(await bank['switch'].get())
        await bank['switch'].set(False)
        self.assertFalse(await consumer.get_switch())
        self.assertFalse((await consumer.get_status()).on)
        self.assertEqual((await consumer.get_status()).power, 0)
        await consumer.set_switch(True)
        self.assertTrue(await bank['switch'].get())

    async def test_read_only_switch(self) -> None:
        consumer = DummyPowerConsumer(can_switch=False, on=True)
        bank = await consumer.get_registers()
        self.assertFalse(consumer.can_switch)
        self.assertFalse(bank['switch'].writable)
        self.assertTrue(await consumer.get_switch())
        with self.assertRaises(ReadOnlyError):
            await consumer.set_switch(False)
        with self.assertRaises(ReadOnlyError):
            await bank['switch'].set(False)
        self.assertTrue(await consumer.get_switch())

    async def test_switch_register_rejects_non_boolean(self) -> None:
        consumer = DummyPowerConsumer()
        bank = await consumer.get_registers()
        with self.assertRaises(TypeError):
            await bank['switch'].set(1)

    async def test_dummy_energy_and_uptime(self) -> None:
        clock = [0.0]
        with patch(
                'solala.delegates.power_consumer.dummy_power_consumer.dummy_power_consumer.monotonic',
                side_effect=lambda: clock[0],
        ):
            consumer = DummyPowerConsumer(voltage=240, current=1, power=100)
            clock[0] = 1800
            consumer.power = 200
            clock[0] = 3600
            await consumer.set_switch(False)
            clock[0] = 5400
            status = await consumer.get_status()
            self.assertAlmostEqual(status.accumulated_energy, 150)
            self.assertEqual(status.power, 0)
            self.assertEqual(consumer.uptime, 5400)
            bank = await consumer.get_registers()
            self.assertEqual(await bank['uptime'].get(), 5400)
            self.assertEqual(await bank['energy'].get(), 150)
            self.assertEqual(consumer.get_connection_info()['create_time'], 0)

    async def test_invalid_dummy_power_preserves_energy(self) -> None:
        clock = [0.0]
        with patch(
                'solala.delegates.power_consumer.dummy_power_consumer.dummy_power_consumer.monotonic',
                side_effect=lambda: clock[0],
        ):
            consumer = DummyPowerConsumer(voltage=240, current=1, power=100)
            clock[0] = 1800
            with self.assertRaises(ValueError):
                consumer.power = 300
            self.assertEqual(consumer._energy, 0)
            self.assertEqual(consumer._time, 0)
            self.assertEqual(consumer.power, 100)
            self.assertAlmostEqual(consumer.energy, 50)

    async def test_dummy_energy_can_be_omitted(self) -> None:
        consumer = DummyPowerConsumer(include_accumulated_energy=False)
        self.assertIsNone((await consumer.get_status()).accumulated_energy)

    async def test_settings_round_trip(self) -> None:
        dummy = DummyConsumerConnection(can_switch=False, include_accumulated_energy=False)
        self.assertEqual(DummyConsumerConnection.model_validate_json(dummy.model_dump_json()), dummy)
        tuya = TuyaConnection(
            access_id='test', access_secret='secret', device_id='device',
            include_accumulated_energy=True, cache_duration=42,
        )
        self.assertEqual(TuyaConnection.model_validate_json(tuya.model_dump_json()), tuya)


class TuyaSwitchContractTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify Tuya commands without making cloud API requests.
    """

    def setUp(self) -> None:
        with patch(
                'solala.delegates.power_consumer.tuya_power_consumer.tuya_power_consumer.TuyaOpenAPI',
        ) as api:
            self.consumer = TuyaPowerConsumer('id', 'secret', 'device')
            self.client = api.return_value
        self.consumer._connected = True

    async def test_switch_command_payload(self) -> None:
        self.client.post.return_value = {'success': True}
        await self.consumer.set_switch(False)
        self.client.post.assert_called_once_with(
            '/v1.0/iot-03/devices/device/commands',
            {'commands': [{'code': 'switch_1', 'value': False}]},
        )

    async def test_switch_command_failure_propagates(self) -> None:
        self.client.post.return_value = {'success': False, 'code': 1004}
        with self.assertRaises(ConnectionError):
            await self.consumer.set_switch(True)

    async def test_switch_command_exception_propagates(self) -> None:
        self.client.post.side_effect = TimeoutError('offline')
        with self.assertRaises(TimeoutError):
            await self.consumer.set_switch(True)

    async def test_switch_read_uses_cached_status(self) -> None:
        self.consumer._cache = AsyncMock(return_value={'switch_1': True})
        self.assertTrue(await self.consumer.get_switch())
        self.consumer._cache.assert_awaited_once()

    async def test_tuya_optional_energy(self) -> None:
        values = {
            'cur_voltage': 2400, 'cur_current': 500,
            'cur_power': 1200, 'switch_1': True, 'add_ele': 123,
        }
        self.consumer._cache = AsyncMock(return_value=values)
        self.assertIsNone((await self.consumer.get_status()).accumulated_energy)
        self.consumer._include_accumulated_energy = True
        self.assertEqual((await self.consumer.get_status()).accumulated_energy, 123)

    async def test_missing_enabled_tuya_energy_propagates(self) -> None:
        self.consumer._include_accumulated_energy = True
        self.consumer._cache = AsyncMock(return_value={
            'cur_voltage': 2400, 'cur_current': 500,
            'cur_power': 1200, 'switch_1': True,
        })
        with self.assertRaises(KeyError):
            await self.consumer.get_status()


if __name__ == '__main__':
    unittest.main()
