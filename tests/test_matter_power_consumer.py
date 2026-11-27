import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

import aiohttp

from solala.control import control_loop
from solala.delegates.power_consumer.matter_power_consumer.matter_power_consumer import MatterPowerConsumer
from solala.settings import ConsumerConnection, MatterConnection, Settings
from solala.utils.json_extras import JSONValue


class MatterPowerConsumerTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify Matter measurements, switching, errors, and configuration.
    """

    def setUp(self) -> None:
        self.consumer = MatterPowerConsumer('localhost', 5580, node_id=1, endpoint_id=1)
        self.attributes: dict[str, JSONValue] = {
            '1/6/0': True,
            '1/144/8': 125000,
            '1/144/11': 239000,
            '1/144/12': 530,
            '1/145/1': {'0': 1234000},
        }
        self.request = AsyncMock(return_value=[
            {'node_id': 1, 'available': True, 'attributes': self.attributes},
        ])
        self.consumer._request = self.request

    async def test_unrelated_events_do_not_extend_command_deadline(self) -> None:
        consumer = MatterPowerConsumer('localhost', 5580, node_id=1, endpoint_id=1, timeout=0.02)

        async def receive(**_kwargs: float) -> aiohttp.WSMessage:
            await asyncio.sleep(0.001)
            return aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, '{"event": "attribute_updated"}', '')

        socket = Mock(send_json=AsyncMock(), receive=AsyncMock(side_effect=receive))
        with (
            patch.object(consumer, '_ensure_connected', return_value=socket),
            patch.object(consumer, '_disconnect') as disconnect,
        ):
            done, pending = await asyncio.wait(
                [task := asyncio.create_task(consumer._request('get_nodes'))], timeout=0.5,
            )
            if pending:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.assertIn(task, done, 'Matter request kept waiting after its deadline')
            with self.assertRaises(TimeoutError):
                task.result()
            disconnect.assert_awaited_once()

    async def test_status_converts_milliunits(self) -> None:
        status = await self.consumer.get_status()
        self.assertTrue(status.on)
        self.assertEqual(status.power, 125)
        self.assertEqual(status.voltage, 239)
        self.assertEqual(status.current, 0.53)
        self.assertEqual(status.accumulated_energy, 1234)

    async def test_optional_energy(self) -> None:
        self.attributes.pop('1/145/1')
        self.assertIsNone((await self.consumer.get_status()).accumulated_energy)

    async def test_invalid_optional_energy_warns_without_hiding_status(self) -> None:
        invalid_values = ({'0': -1}, {'0': float('nan')},
                          {'0': float('inf')}, {'0': True},
                          {'0': 'invalid'})
        for energy in invalid_values:
            with self.subTest(energy=energy):
                self.attributes['1/145/1'] = energy
                await self.consumer._attributes_cache.invalidate()
                with self.assertLogs('solala', level='WARNING') as captured:
                    status = await self.consumer.get_status()
                self.assertIsNone(status.accumulated_energy)
                self.assertEqual(status.power, 125)
                self.assertTrue(status.on)
                self.assertIn('Matter accumulated energy unavailable', captured.output[0])

    async def test_unavailable_optional_energy_is_silent(self) -> None:
        for energy in ({}, None):
            with self.subTest(energy=energy):
                self.attributes['1/145/1'] = energy
                await self.consumer._attributes_cache.invalidate()
                status = await self.consumer.get_status()
                self.assertIsNone(status.accumulated_energy)
                self.assertEqual(status.power, 125)

    async def test_huge_integer_energy_uses_wh_fallback(self) -> None:
        raw_energy = 10 ** 400 + 999
        self.attributes['1/145/1'] = {'0': raw_energy}
        status = await self.consumer.get_status()
        self.assertEqual(status.accumulated_energy, raw_energy // 1000 + 1)
        self.assertIsInstance(status.accumulated_energy, int)

    async def test_zero_optional_energy_is_valid(self) -> None:
        self.attributes['1/145/1'] = {'0': 0}
        self.assertEqual((await self.consumer.get_status()).accumulated_energy, 0)

    async def test_nonfinite_required_measurements_raise(self) -> None:
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.subTest(value=value):
                self.attributes['1/144/8'] = value
                await self.consumer._attributes_cache.invalidate()
                with self.assertRaises(ConnectionError):
                    await self.consumer.get_status()

    async def test_switch_command(self) -> None:
        await self.consumer.set_switch(False)
        self.request.assert_awaited_once_with(
            'device_command', node_id=1, endpoint_id=1,
            cluster_id=6, command_name='Off', payload={},
        )

    async def test_switch_register_and_measurements(self) -> None:
        bank = await self.consumer.get_registers()
        self.assertIs(bank, await self.consumer.get_registers())
        self.assertTrue(bank['1/6/0'].writable)
        self.assertTrue(await bank['1/6/0'].get())
        self.assertEqual(await bank['1/144/8'].get(), 125000)
        self.assertEqual(await bank['1/144/11'].get(), 239000)
        self.assertEqual(await bank['1/144/12'].get(), 530)
        self.assertNotIn('switch', bank)
        self.assertNotIn('power', bank)
        self.assertNotIn('voltage', bank)
        self.assertNotIn('current', bank)

    async def test_missing_node_and_unavailable_node(self) -> None:
        self.request.return_value = []
        with self.assertRaises(ConnectionError):
            await self.consumer.get_status()
        await self.consumer._attributes_cache.invalidate()
        self.request.return_value = [
            {'node_id': 1, 'available': False, 'attributes': self.attributes},
        ]
        with self.assertRaises(ConnectionError):
            await self.consumer.get_status()

    async def test_missing_or_invalid_required_attribute(self) -> None:
        self.attributes.pop('1/144/8')
        with self.assertRaises(ConnectionError):
            await self.consumer.get_status()
        self.attributes['1/144/8'] = 'invalid'
        await self.consumer._attributes_cache.invalidate()
        with self.assertRaises(ConnectionError):
            await self.consumer.get_status()

    async def test_server_error_propagates(self) -> None:
        self.request.side_effect = ConnectionError('server unavailable')
        with self.assertRaises(ConnectionError):
            await self.consumer.get_status()

    async def test_cached_snapshot_and_invalidation(self) -> None:
        await self.consumer.get_status()
        await self.consumer.get_status()
        self.request.assert_awaited_once()
        await self.consumer.set_switch(False)
        await self.consumer.get_status()
        self.assertEqual(self.request.await_count, 3)

    async def test_diagnostic_registers_and_flattening(self) -> None:
        self.attributes['0/40/1'] = 'Vendor'
        self.attributes['1/145/1'] = {'0': 1234000}
        excluded_clusters = (31, 48, 49, 53, 54, 62)
        for cluster in excluded_clusters:
            self.attributes[f'0/{cluster}/0'] = 'sensitive'
        self.attributes['1/99/0'] = ['unsupported']
        with patch(
                'solala.delegates.power_consumer.matter_power_consumer.'
                'matter_power_consumer._EXCLUDED_CLUSTERS', set(excluded_clusters),
        ):
            bank = await self.consumer.get_registers()
        self.assertEqual(await bank['0/40/1'].get(), 'Vendor')
        self.assertEqual(await bank['1/145/1/0'].get(), 1234000)
        self.assertFalse(bank['1/145/1/0'].writable)
        self.assertFalse(bank['1/144/8'].writable)
        for cluster in excluded_clusters:
            self.assertNotIn(f'0/{cluster}/0', bank)
        self.assertNotIn('1/99/0', bank)

    async def test_invalid_measurement_raises_connection_error(self) -> None:
        self.attributes['1/144/8'] = 'bad'
        with self.assertRaisesRegex(ConnectionError, 'bad'):
            await self.consumer.get_status()

    async def test_settings_and_factory(self) -> None:
        config = MatterConnection(host='localhost', port=5580, node_id=1, token='test')
        consumers: dict[str, ConsumerConnection] = {'plug': config}
        settings = Settings(consumers=consumers)
        restored = Settings.model_validate_json(settings.model_dump_json())
        self.assertEqual(restored.consumers, consumers)

        with patch('solala.control.control_loop.MatterPowerConsumer') as factory:
            control_loop._connect_matter(config)
        self.assertEqual(factory.call_args.kwargs['host'], 'localhost')
        self.assertEqual(factory.call_args.kwargs['token'], 'test')
        self.assertEqual(factory.call_args.kwargs['node_id'], 1)

    async def test_close_is_idempotent(self) -> None:
        await self.consumer.close()
        await self.consumer.close()


if __name__ == '__main__':
    unittest.main()
