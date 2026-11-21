"""Tests for the TinyTuya LAN power consumer."""

import asyncio
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

    async def test_status_cache(self) -> None:
        await self.consumer.get_status()
        await self.consumer.get_status()
        await self.consumer.get_switch()
        self.device.status.assert_called_once()

    async def test_switch_invalidates_status_cache(self) -> None:
        await self.consumer.get_status()
        await self.consumer.set_switch(False)
        await self.consumer.get_status()
        self.assertEqual(self.device.status.call_count, 2)

    async def test_cancelled_request_waits_for_thread(self) -> None:
        started = asyncio.Event()
        finish = asyncio.Event()
        calls = 0

        async def delayed_request(function, switch=None):
            nonlocal calls
            calls += 1
            started.set()
            await finish.wait()
            return {'dps': {'1': True, '18': 0, '19': 0, '20': 2400}}

        with patch(
                'solala.delegates.power_consumer.tuya_local_power_consumer.tuya_local_power_consumer.asyncio.to_thread',
                side_effect=delayed_request,
        ):
            first = asyncio.create_task(self.consumer.get_status())
            await started.wait()
            first.cancel()
            second = asyncio.create_task(self.consumer.get_status())
            await asyncio.sleep(0)
            self.assertEqual(calls, 1)
            finish.set()
            with self.assertRaises(asyncio.CancelledError):
                await first
            await second
            self.assertEqual(calls, 2)

    async def test_switch_failure_invalidates_cache(self) -> None:
        await self.consumer.get_status()
        self.device.set_status.side_effect = ConnectionError('response lost')
        with self.assertRaises(ConnectionError):
            await self.consumer.set_switch(False)
        await self.consumer.get_status()
        self.assertEqual(self.device.status.call_count, 2)

    def test_validation_and_secret(self) -> None:
        with self.assertRaises(ValueError):
            TuyaLocalPowerConsumer('host', 'id', 'key', calibration_factor=0)
        with self.assertRaises(ValueError):
            TuyaLocalPowerConsumer('host', 'id', 'key', calibration_factor=float('nan'))
        self.assertNotIn('test-key', str(self.consumer.get_connection_info()))
