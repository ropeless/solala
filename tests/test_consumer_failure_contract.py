import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from solala.delegates.power_consumer.power_consumer import PowerConsumer
from solala.delegates.power_consumer.tesla_wall_connector.tesla_wall_connector import TeslaWallConnector
from solala.delegates.power_consumer.tuya_cloud_power_consumer.tuya_cloud_power_consumer import TuyaCloudPowerConsumer
from solala.utils.json_extras import JSONValue


class ConsumerFailureContractTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify consumer communication failures, retry behavior, and optional energy handling.
    """

    def _tesla_consumer(self) -> TeslaWallConnector:
        # These tests supply fake HTTP responses, so skip HTTPX's TLS setup.
        with patch('httpx.AsyncClient', autospec=True):
            consumer = TeslaWallConnector('example.invalid')
        self.addAsyncCleanup(consumer.close)
        return consumer

    async def test_tesla_http_failure_propagates_and_retries(self) -> None:
        consumer = self._tesla_consumer()
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
        with self.assertRaises(httpx.ConnectError):
            await consumer.get_status()
        status = await consumer.get_status()
        self.assertEqual(status.voltage, 240.0)
        self.assertEqual(status.current, 2.0)
        self.assertTrue(status.on)
        self.assertEqual(status.accumulated_energy, 1200)
        self.assertEqual(consumer._client.get.await_count, 3)

    async def test_tesla_failed_discovery_does_not_cache_bank(self) -> None:
        consumer = self._tesla_consumer()
        failure = httpx.ConnectError('device unreachable')
        response = Mock()
        response.json.return_value = {'voltageA_v': 240.0}
        lifetime = Mock()
        lifetime.json.return_value = {'energy_wh': 1200}
        consumer._client.get = AsyncMock(side_effect=[failure, response, lifetime])
        with self.assertRaises(httpx.ConnectError):
            await consumer.get_registers()
        self.assertIsNone(consumer._register_bank)
        bank = await consumer.get_registers()
        self.assertIn('vital/voltageA_v', bank)
        self.assertIs(await consumer.get_registers(), bank)

    async def test_tuya_api_failure_propagates_and_retries(self) -> None:
        consumer = TuyaCloudPowerConsumer(
            'test', 'secret', 'test-device',
            voltage_scale_factor=1.0, current_scale_factor=1.0, power_scale_factor=1.0,
        )
        consumer._connected = True
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
        with self.assertRaises(ConnectionError):
            await consumer.get_status()
        status = await consumer.get_status()
        self.assertEqual(status.power, 400)
        self.assertTrue(status.on)
        self.assertEqual(consumer._tuya.get.call_count, 2)

    async def test_tuya_optional_energy_failures_preserve_status(self) -> None:
        consumer = object.__new__(TuyaCloudPowerConsumer)
        PowerConsumer.__init__(consumer, can_switch=True)
        consumer._include_accumulated_energy = True
        consumer._voltage_scale_factor = 1.0
        consumer._current_scale_factor = 1.0
        consumer._power_scale_factor = 1.0
        consumer._calibration_factor = 1.0
        status = {
            'cur_voltage': 240, 'cur_current': 2,
            'cur_power': 400, 'switch_1': True,
        }
        for energy in (None, -1, float('nan'), float('inf'), True, 'invalid'):
            with self.subTest(energy=energy):
                data: dict[str, JSONValue] = dict(status)
                if energy is not None:
                    data['add_ele'] = energy
                consumer._cache = AsyncMock(return_value=data)
                with self.assertLogs('solala', level='WARNING') as captured:
                    result = await consumer.get_status()
                self.assertIsNone(result.accumulated_energy)
                self.assertEqual(result.power, 400)
                self.assertTrue(result.on)
                self.assertIn('Tuya accumulated energy unavailable', captured.output[0])

        consumer._cache = AsyncMock(return_value={**status, 'add_ele': 0})
        self.assertEqual((await consumer.get_status()).accumulated_energy, 0)

        consumer._cache = AsyncMock(return_value={**status, 'add_ele': 25})
        self.assertEqual((await consumer.get_status()).accumulated_energy, 25)

        consumer._cache = AsyncMock(return_value={'add_ele': 25, 'switch_1': True})
        with self.assertRaises(KeyError):
            await consumer.get_status()

    async def test_tuya_large_accumulated_energy(self) -> None:
        consumer = object.__new__(TuyaCloudPowerConsumer)
        PowerConsumer.__init__(consumer, can_switch=True)
        consumer._include_accumulated_energy = True
        consumer._voltage_scale_factor = 1.0
        consumer._current_scale_factor = 1.0
        consumer._power_scale_factor = 1.0
        consumer._calibration_factor = 1.0
        large_energy = 10 ** 400
        consumer._cache = AsyncMock(return_value={
            'cur_voltage': 240, 'cur_current': 2,
            'cur_power': 400, 'switch_1': True,
            'add_ele': large_energy,
        })

        status = await consumer.get_status()
        self.assertEqual(status.accumulated_energy, large_energy)
        self.assertEqual(status.power, 400)
        self.assertTrue(status.on)

    async def test_tuya_failed_discovery_does_not_cache_bank(self) -> None:
        consumer = TuyaCloudPowerConsumer('test', 'secret', 'test-device')
        consumer._connected = True
        consumer._tuya = Mock()
        consumer._tuya.get.side_effect = [
            {'success': False, 'code': 1004, 'msg': 'sign invalid'},
            {'success': True, 'result': [{'code': 'cur_power', 'value': 400}]},
        ]
        with self.assertRaises(ConnectionError):
            await consumer.get_registers()
        self.assertIsNone(consumer._register_bank)
        bank = await consumer.get_registers()
        self.assertIn('cur_power', bank)
        self.assertIs(await consumer.get_registers(), bank)

    async def test_register_bank_captures_read_error_without_hiding_it(self) -> None:
        consumer = self._tesla_consumer()
        response = Mock()
        response.json.return_value = {'voltageA_v': 240.0}
        lifetime = Mock()
        lifetime.json.return_value = {'energy_wh': 1200}
        consumer._client.get = AsyncMock(side_effect=[response, lifetime])
        bank = await consumer.get_registers()
        consumer._vitals_cache = AsyncMock(side_effect=httpx.ConnectError('device unreachable'))
        values = await bank.get_register_values()
        self.assertIsInstance(values['vital/voltageA_v'], httpx.ConnectError)


if __name__ == '__main__':
    unittest.main()
