import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from solala.delegates.power_consumer.power_consumer import PowerConsumer
from solala.delegates.power_consumer.tesla_wall_connector.tesla_wall_connector import TeslaWallConnector
from solala.delegates.power_consumer.tuya_power_consumer.tuya_power_consumer import TuyaPowerConsumer
from solala.utils.micro_cache import AsyncMicroCache


class ConsumerFailureContractTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Specify strict consumer communication errors and retryable register discovery.

    These tests describe the proposed contract and are expected to fail until
    the consumer implementations stop returning synthetic fallback readings.
    """

    async def test_tesla_http_failure_propagates_and_retries(self) -> None:
        consumer = TeslaWallConnector('example.invalid')
        failure = httpx.ConnectError('device unreachable')
        vitals = {
            'grid_v': 240.0,
            'voltageA_v': 240.0, 'currentA_a': 2.0,
            'voltageB_v': 240.0, 'currentB_a': 0.0,
            'voltageC_v': 240.0, 'currentC_a': 0.0,
            'contactor_closed': True,
        }
        response = Mock()
        response.json.return_value = vitals
        lifetime = Mock()
        lifetime.json.return_value = {'energy_wh': 1200}
        consumer._client.get = AsyncMock(side_effect=[failure, response, lifetime])
        try:
            with self.assertRaises(httpx.ConnectError):
                await consumer.get_status()
            status = await consumer.get_status()
            self.assertEqual(status.voltage, 240.0)
            self.assertEqual(status.current, 2.0)
            self.assertTrue(status.on)
            self.assertEqual(status.accumulated_energy, 1200)
            self.assertEqual(consumer._client.get.await_count, 3)
        finally:
            await consumer.close()

    async def test_tesla_failed_discovery_does_not_cache_bank(self) -> None:
        consumer = TeslaWallConnector('example.invalid')
        failure = httpx.ConnectError('device unreachable')
        response = Mock()
        response.json.return_value = {'voltageA_v': 240.0}
        lifetime = Mock()
        lifetime.json.return_value = {'energy_wh': 1200}
        consumer._client.get = AsyncMock(side_effect=[failure, response, lifetime])
        try:
            with self.assertRaises(httpx.ConnectError):
                await consumer.get_registers()
            self.assertIsNone(consumer._register_bank)
            bank = await consumer.get_registers()
            self.assertIn('vital/voltageA_v', bank)
            self.assertIs(await consumer.get_registers(), bank)
        finally:
            await consumer.close()

    async def test_tuya_api_failure_propagates_and_retries(self) -> None:
        consumer = object.__new__(TuyaPowerConsumer)
        PowerConsumer.__init__(consumer, can_switch=True)
        consumer._include_accumulated_energy = False
        consumer._connected = True
        consumer._status_url = '/test/status'
        consumer._connection_info = {'device_id': 'test-device'}
        consumer._voltage_scale_factor = 1.0
        consumer._current_scale_factor = 1.0
        consumer._power_scale_factor = 1.0
        consumer._tuya = Mock()
        consumer._tuya.get.side_effect = [
            {'success': False, 'code': 1004, 'msg': 'sign invalid'},
            {'success': True, 'result': [
                {'code': 'cur_voltage', 'value': 240},
                {'code': 'cur_current', 'value': 2},
                {'code': 'cur_power', 'value': 400},
                {'code': 'switch_1', 'value': True},
            ]},
        ]
        consumer._cache = AsyncMicroCache(consumer._TuyaPowerConsumer__get_device_status, 300)
        with self.assertRaises(ConnectionError):
            await consumer.get_status()
        status = await consumer.get_status()
        self.assertEqual(status.power, 400)
        self.assertTrue(status.on)
        self.assertEqual(consumer._tuya.get.call_count, 2)

    async def test_tuya_failed_discovery_does_not_cache_bank(self) -> None:
        consumer = object.__new__(TuyaPowerConsumer)
        PowerConsumer.__init__(consumer, can_switch=True)
        consumer._include_accumulated_energy = False
        consumer._connected = True
        consumer._status_url = '/test/status'
        consumer._connection_info = {'device_id': 'test-device'}
        consumer._register_bank = None
        consumer._register_bank_lock = asyncio.Lock()
        consumer._tuya = Mock()
        consumer._tuya.get.side_effect = [
            {'success': False, 'code': 1004, 'msg': 'sign invalid'},
            {'success': True, 'result': [{'code': 'cur_power', 'value': 400}]},
        ]
        consumer._cache = AsyncMicroCache(consumer._TuyaPowerConsumer__get_device_status, 300)
        with self.assertRaises(ConnectionError):
            await consumer.get_registers()
        self.assertIsNone(consumer._register_bank)
        bank = await consumer.get_registers()
        self.assertIn('cur_power', bank)
        self.assertIs(await consumer.get_registers(), bank)

    async def test_register_bank_captures_read_error_without_hiding_it(self) -> None:
        consumer = TeslaWallConnector('example.invalid')
        response = Mock()
        response.json.return_value = {'voltageA_v': 240.0}
        lifetime = Mock()
        lifetime.json.return_value = {'energy_wh': 1200}
        consumer._client.get = AsyncMock(side_effect=[response, lifetime])
        try:
            bank = await consumer.get_registers()
            consumer._vitals_cache = AsyncMock(side_effect=httpx.ConnectError('device unreachable'))
            values = await bank.get_register_values()
            self.assertIsInstance(values['vital/voltageA_v'], httpx.ConnectError)
        finally:
            await consumer.close()


if __name__ == '__main__':
    unittest.main()
