import asyncio
import unittest
from threading import Event
from unittest.mock import AsyncMock, patch

from solala.control import control_loop
from solala.delegates.power_consumer.dummy_power_consumer.dummy_power_consumer import DummyPowerConsumer
from solala.delegates.power_consumer.tuya_cloud_power_consumer.tuya_cloud_power_consumer import TuyaCloudPowerConsumer
from solala.register import ReadOnlyError
from solala.register_bank import EMPTY_REGISTER_BANK
from solala.settings import (
    DummyConsumerConnection, MatterConnection, TeslaWallConnectorConnection, TuyaCloudConnection, TuyaLocalConnection,
)


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
        tuya = TuyaCloudConnection(
            access_id='test', access_secret='secret', device_id='device',
            include_accumulated_energy=True, cache_duration=42, connect_timeout=2.5, read_timeout=8.0,
        )
        self.assertEqual(TuyaCloudConnection.model_validate_json(tuya.model_dump_json()), tuya)
        defaults = TuyaCloudConnection.model_validate(tuya.model_dump(exclude={'connect_timeout', 'read_timeout'}))
        self.assertEqual((defaults.connect_timeout, defaults.read_timeout), (5.0, 10.0))

    async def test_factory_forwards_dummy_options(self) -> None:
        config = DummyConsumerConnection(can_switch=False, include_accumulated_energy=False)
        consumer = control_loop._connect_dummy_consumer(config)
        self.assertFalse(consumer.can_switch)
        self.assertIsNone((await consumer.get_status()).accumulated_energy)

    async def test_factory_forwards_tuya_options(self) -> None:
        config = TuyaCloudConnection(
            access_id='test', access_secret='secret', device_id='device',
            include_accumulated_energy=True, cache_duration=42, connect_timeout=2.5, read_timeout=8.0,
        )
        state = control_loop._ControlState()
        with (
            patch.object(control_loop, '_CONTROL_STATE', state),
            patch.object(control_loop, 'log_info'),
            patch('solala.control.control_loop.TuyaCloudPowerConsumer', autospec=True) as factory,
        ):
            factory.return_value.get_connection_info.return_value = {}
            factory.return_value.get_registers.return_value = EMPTY_REGISTER_BANK
            try:
                await control_loop.connect_consumer('plug', config)
            finally:
                await control_loop.disconnect_consumer('plug')
        self.assertEqual(factory.call_args.kwargs['include_accumulated_energy'], True)
        self.assertEqual(factory.call_args.kwargs['cache_duration'], 42)
        self.assertEqual(factory.call_args.kwargs['connect_timeout'], 2.5)
        self.assertEqual(factory.call_args.kwargs['read_timeout'], 8.0)

    async def test_matter_factory_reports_configured_timing(self) -> None:
        config = MatterConnection(
            host='localhost', port=5580, node_id=1, timeout=12.0, cache_duration=0.4, token='secret',
        )
        default_config = MatterConnection.model_validate(config.model_dump(exclude={'cache_duration'}))
        self.assertEqual(default_config.cache_duration, 0.1)
        restored = MatterConnection.model_validate_json(config.model_dump_json())
        consumer = control_loop._connect_matter(restored)
        async with consumer:
            info = consumer.get_connection_info()
            self.assertEqual(info['timeout'], 12.0)
            self.assertEqual(info['cache_duration'], 0.4)
            self.assertNotIn('token', info)

    async def test_tuya_local_factory_reports_configured_timing(self) -> None:
        config = TuyaLocalConnection(
            host='localhost', device_id='device', local_key='secret', timeout=2.5, cache_duration=0.4,
        )
        consumer = control_loop._connect_tuya_local(config)
        async with consumer:
            info = consumer.get_connection_info()
            self.assertEqual(info['timeout'], 2.5)
            self.assertEqual(info['cache_duration'], 0.4)
            self.assertNotIn('local_key', info)

    async def test_tesla_factory_reports_configured_timing(self) -> None:
        config = TeslaWallConnectorConnection(address='127.0.0.1', timeout=2.5, cache_duration=0.4)
        with patch('httpx.AsyncClient', autospec=True) as client:
            consumer = control_loop._connect_tesla_wall_connector(config)
        client.assert_called_once_with(timeout=2.5)
        async with consumer:
            info = consumer.get_connection_info()
            self.assertEqual(info['timeout'], 2.5)
            self.assertEqual(info['cache_duration'], 0.4)
            self.assertNotIn('mac_address', info)


class TuyaSwitchContractTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify Tuya commands without making cloud API requests.
    """

    async def test_close_waits_for_cancelled_request_to_leave_sdk_session(self) -> None:
        started = asyncio.Event()
        release = Event()
        loop = asyncio.get_running_loop()

        def get_status(_: str) -> dict:
            loop.call_soon_threadsafe(started.set)
            if not release.wait(2):
                raise TimeoutError('test did not release request')
            return {'success': True, 'result': []}

        self.client.get.side_effect = get_status
        request = asyncio.create_task(self.consumer.get_status())
        closing = None
        try:
            await asyncio.wait_for(started.wait(), 1)
            request.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await request
            closing = asyncio.create_task(self.consumer.close())
            await asyncio.sleep(0)
            self.client.session.close.assert_not_called()
            self.assertFalse(closing.done())
        finally:
            release.set()
            if closing is not None:
                await closing
        await self.consumer.close()
        self.client.session.close.assert_called_once_with()
        with self.assertRaises(ConnectionError):
            await self.consumer.get_status()
        self.client.get.assert_called_once()

    def setUp(self) -> None:
        with patch(
                'solala.delegates.power_consumer.tuya_cloud_power_consumer.tuya_cloud_power_consumer.TuyaOpenAPI',
        ) as api:
            self.consumer = TuyaCloudPowerConsumer('id', 'secret', 'device')
            self.client = api.return_value
        self.consumer._connected = True

    async def test_concurrent_tuya_connection_initializes_once(self) -> None:
        self.consumer._connected = False
        self.client.connect.return_value = {'success': True}
        await asyncio.gather(self.consumer._connect(), self.consumer._connect())
        self.client.connect.assert_called_once_with()
        self.assertTrue(self.consumer._connected)

    def test_cloud_requests_have_connect_and_read_timeouts(self) -> None:
        for options, expected in (
            ({}, (5.0, 10.0)),
            ({'connect_timeout': 2.5, 'read_timeout': 8.0}, (2.5, 8.0)),
        ):
            with (
                self.subTest(options=options),
                patch(
                    'solala.delegates.power_consumer.tuya_cloud_power_consumer.tuya_cloud_power_consumer.TuyaOpenAPI',
                ) as api,
            ):
                request = api.return_value.session.request
                consumer = TuyaCloudPowerConsumer('id', 'secret', 'device', **options)
                api.return_value.session.request('GET', 'https://example.invalid')
                request.assert_called_once_with('GET', 'https://example.invalid', timeout=expected)
                info = consumer.get_connection_info()
                self.assertEqual((info['connect_timeout'], info['read_timeout']), expected)
                self.assertEqual(info['cache_duration'], 300)
                self.assertNotIn('access_secret', info)

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

    async def test_missing_enabled_tuya_energy_preserves_status(self) -> None:
        self.consumer._include_accumulated_energy = True
        self.consumer._cache = AsyncMock(return_value={
            'cur_voltage': 2400, 'cur_current': 500,
            'cur_power': 1200, 'switch_1': True,
        })
        with self.assertLogs('solala', level='WARNING') as captured:
            status = await self.consumer.get_status()
        self.assertIsNone(status.accumulated_energy)
        self.assertEqual(status.voltage, 240)
        self.assertEqual(status.current, 0.5)
        self.assertEqual(status.power, 120)
        self.assertTrue(status.on)
        self.assertIn('Tuya accumulated energy unavailable', captured.output[0])


if __name__ == '__main__':
    unittest.main()
