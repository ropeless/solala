import unittest
from unittest.mock import AsyncMock, patch

from solala.delegates.power_consumer.matter_power_consumer import MatterPowerConsumer
from solala.settings import MatterConnection, Settings


class MatterPowerConsumerTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify Matter measurements, switching, errors, and configuration.
    """

    def setUp(self) -> None:
        self.consumer = MatterPowerConsumer('localhost', 5580, 1, endpoint_id=1)
        self.attributes = {
            '1/6/0': True,
            '1/144/8': 125000,
            '1/144/11': 239000,
            '1/144/12': 530,
            '1/145/1': {'0': 1234000},
        }
        self.consumer._request = AsyncMock(return_value=[
            {'node_id': 1, 'available': True, 'attributes': self.attributes},
        ])

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

    async def test_switch_command(self) -> None:
        await self.consumer.set_switch(False)
        self.consumer._request.assert_awaited_once_with(
            'device_command', node_id=1, endpoint_id=1,
            cluster_id=6, command_name='Off', payload={},
        )

    async def test_switch_register_and_measurements(self) -> None:
        bank = await self.consumer.get_registers()
        self.assertIs(bank, await self.consumer.get_registers())
        self.assertTrue(bank['switch'].writable)
        self.assertTrue(await bank['switch'].get())
        self.assertEqual(await bank['power'].get(), 125)
        self.assertEqual(await bank['voltage'].get(), 239)
        self.assertEqual(await bank['current'].get(), 0.53)

    async def test_missing_node_and_unavailable_node(self) -> None:
        self.consumer._request.return_value = []
        with self.assertRaises(ConnectionError):
            await self.consumer.get_status()
        self.consumer._request.return_value = [
            {'node_id': 1, 'available': False, 'attributes': self.attributes},
        ]
        with self.assertRaises(ConnectionError):
            await self.consumer.get_status()

    async def test_missing_or_invalid_required_attribute(self) -> None:
        self.attributes.pop('1/144/8')
        with self.assertRaises(ConnectionError):
            await self.consumer.get_status()
        self.attributes['1/144/8'] = 'invalid'
        with self.assertRaises(ConnectionError):
            await self.consumer.get_status()

    async def test_server_error_propagates(self) -> None:
        self.consumer._request.side_effect = ConnectionError('server unavailable')
        with self.assertRaises(ConnectionError):
            await self.consumer.get_status()

    async def test_settings_and_factory(self) -> None:
        config = MatterConnection(host='localhost', port=5580, node_id=1, token='test')
        settings = Settings(consumers={'plug': config})
        restored = Settings.model_validate_json(settings.model_dump_json())
        self.assertEqual(restored.consumers['plug'], config)

        import importlib
        control_loop = importlib.import_module('solala.control_loop.control_loop')
        with patch.object(control_loop, 'MatterPowerConsumer') as factory:
            control_loop._connect_matter(config)
        self.assertEqual(factory.call_args.kwargs['host'], 'localhost')
        self.assertEqual(factory.call_args.kwargs['token'], 'test')
        self.assertEqual(factory.call_args.kwargs['node_id'], 1)

    async def test_close_is_idempotent(self) -> None:
        await self.consumer.close()
        await self.consumer.close()


if __name__ == '__main__':
    unittest.main()
