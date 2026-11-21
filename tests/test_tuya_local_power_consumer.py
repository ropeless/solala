"""Tests for the TinyTuya LAN power consumer."""

import unittest
from unittest.mock import MagicMock, patch

from solala.delegates.power_consumer.tuya_local_power_consumer.tuya_local_power_consumer import TuyaLocalPowerConsumer


class TuyaLocalPowerConsumerTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Exercise local status, calibration, switching, and errors without hardware.
    """

    def setUp(self) -> None:
        self.device = MagicMock()
        self.device.status.return_value = {
            'dps': {'1': True, '18': 9418, '19': 23743, '20': 2391},
        }
        self.device.set_status.return_value = {'dps': {'1': False}}
        self.patcher = patch(
            'solala.delegates.power_consumer.tuya_local_power_consumer.tuya_local_power_consumer.tinytuya.OutletDevice',
            return_value=self.device,
        )
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.consumer = TuyaLocalPowerConsumer('192.0.2.1', 'device-id', 'test-key', calibration_factor=0.8)

    async def test_status_calibration(self) -> None:
        status = await self.consumer.get_status()
        self.assertTrue(status.on)
        self.assertAlmostEqual(status.current, 9.418 * 0.8)
        self.assertAlmostEqual(status.power, 2374.3 * 0.8)
        self.assertAlmostEqual(status.voltage, 239.1)
        self.assertIsNone(status.accumulated_energy)
        self.device.close.assert_called_once()

    async def test_switch(self) -> None:
        await self.consumer.set_switch(False)
        self.device.set_status.assert_called_once_with(False, 1)
        self.device.close.assert_called_once()

    async def test_switch_read(self) -> None:
        self.assertTrue(await self.consumer.get_switch())

    async def test_error(self) -> None:
        self.device.status.return_value = {'Error': 'Unexpected Payload', 'Err': '904'}
        with self.assertRaises(ConnectionError):
            await self.consumer.get_status()
        self.device.close.assert_called_once()

    async def test_missing_measurement(self) -> None:
        self.device.status.return_value = {'dps': {'1': True, '18': 1000, '20': 2400}}
        with self.assertRaises(KeyError):
            await self.consumer.get_status()

    async def test_registers(self) -> None:
        bank = await self.consumer.get_registers()
        self.assertIs(bank, await self.consumer.get_registers())
        self.assertIsNotNone(bank)

    def test_validation_and_secret(self) -> None:
        with self.assertRaises(ValueError):
            TuyaLocalPowerConsumer('host', 'id', 'key', calibration_factor=0)
        with self.assertRaises(ValueError):
            TuyaLocalPowerConsumer('host', 'id', 'key', calibration_factor=float('nan'))
        self.assertNotIn('test-key', str(self.consumer.get_connection_info()))
