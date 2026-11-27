import unittest
from unittest.mock import AsyncMock, patch

from solala.control import control_loop
from solala.control.control_loop_error import ControlLoopError
from solala.settings import (
    DatabaseConnection, DummyConsumerConnection, DummyControllerConnection, DummyPricerConnection,
    DummySolarForecasterConnection, ModbusControllerConnection,
)
from solala.utils.json_extras import json_dict


class DelegateConnectionsTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify connection errors and outcome logging for the primary delegates.
    """

    async def test_modbus_factory_reports_effective_configuration(self) -> None:
        defaults = ModbusControllerConnection(address='192.0.2.1')
        self.assertFalse(defaults.power_control_slaves)
        settings = ModbusControllerConnection(
            address='192.0.2.1, 192.0.2.2', power_control_slaves=True,
            default_MinRsvPct=9, default_WMaxLimPct_RvrtTms=15,
        )
        with (
            patch('pymodbus.client.ModbusTcpClient.connect', return_value=True),
            patch('solala.delegates.power_controller.modbus_power_controller.modbus._find_model_offsets',
                  return_value={}),
        ):
            controller = control_loop._connect_modbus(settings)
        async with controller:
            info = controller.get_connection_info()
            self.assertEqual(info['master'], 'master')
            self.assertEqual(info['meter'], 'meter')
            self.assertEqual(info['slaves'], ['slave'])
            self.assertIs(info['power_control_slaves'], True)
            self.assertEqual(info['default_MinRsvPct'], 9)
            self.assertEqual(info['default_WMaxLimPct_RvrtTms'], 15)
            devices = json_dict(info['devices'])
            self.assertNotIn('mac_address', json_dict(devices['slave']))

    async def test_database_factory_reports_configured_pool_sizes_without_password(self) -> None:
        defaults = DatabaseConnection(role='test', password='test-password')
        self.assertEqual((defaults.min_pool_size, defaults.max_pool_size), (2, 8))
        settings = DatabaseConnection(role='test', password='test-password', min_pool_size=0, max_pool_size=3)
        with (
            patch.object(control_loop, '_CONTROL_STATE', control_loop._ControlState()),
            patch.object(control_loop, 'log_info') as log_info,
        ):
            await control_loop.connect_database(settings)
            try:
                info = json_dict((await control_loop.get_connection_info())['database'])
                self.assertEqual(info['min_pool_size'], 0)
                self.assertEqual(info['max_pool_size'], 3)
                self.assertNotIn('password', info)
                self.assertNotIn('test-password', log_info.call_args.args[0])
            finally:
                await control_loop.disconnect_database()

    async def test_dummy_delegates_report_failure_configuration_without_exception_message(self) -> None:
        for factory, model, location in (
            (control_loop._connect_dummy_controller, DummyControllerConnection, 'get_status'),
            (control_loop._connect_dummy_consumer, DummyConsumerConnection, 'get_status'),
            (control_loop._connect_dummy_pricer, DummyPricerConnection, 'get_price'),
            (control_loop._connect_dummy_solar_forecaster, DummySolarForecasterConnection, 'get_forecast'),
        ):
            with self.subTest(factory=factory.__name__):
                settings = model.model_validate({'failure': {
                    'location': location,
                    'exception': {'type': 'RuntimeError', 'message': 'test-password'},
                    'probability': 0.5,
                    'sleep': 0.1,
                    'max_injections': 2,
                }})
                async with factory(settings) as delegate:
                    self.assertEqual(delegate.get_connection_info()['failure'], {
                        'location': location,
                        'exception': {'type': 'RuntimeError'},
                        'probability': 0.5,
                        'sleep': 0.1,
                        'max_injections': 2,
                    })

    async def test_connect_wraps_and_logs_factory_failure(self) -> None:
        for connect, factory, settings in (
            (control_loop.connect_controller, '_connect_dummy_controller', DummyControllerConnection()),
            (control_loop.connect_pricer, '_connect_dummy_pricer', DummyPricerConnection()),
            (control_loop.connect_forecaster, '_connect_dummy_solar_forecaster', DummySolarForecasterConnection()),
        ):
            with (
                self.subTest(factory=factory),
                patch.object(control_loop, factory, side_effect=RuntimeError('factory failed')),
                patch.object(control_loop, 'log_error') as error_log,
            ):
                with self.assertRaises(ControlLoopError):
                    await connect(settings)
                error_log.assert_called_once()
                self.assertIn('factory failed', error_log.call_args.args[0])

    async def test_disconnect_wraps_and_logs_close_failure(self) -> None:
        for name, disconnect in (
            ('controller', control_loop.disconnect_controller),
            ('pricer', control_loop.disconnect_pricer),
            ('forecaster', control_loop.disconnect_forecaster),
        ):
            state = control_loop._ControlState()
            delegate = AsyncMock()
            delegate.close.side_effect = RuntimeError('close failed')
            setattr(state.connections, name, delegate)
            with (
                self.subTest(delegate=name),
                patch.object(control_loop, '_CONTROL_STATE', state),
                patch.object(control_loop, 'log_error') as error_log,
            ):
                with self.assertRaises(ControlLoopError):
                    await disconnect()
                error_log.assert_called_once()
                self.assertIn('close failed', error_log.call_args.args[0])

    async def test_disconnect_logs_when_already_disconnected(self) -> None:
        for disconnect in (
            control_loop.disconnect_controller,
            control_loop.disconnect_pricer,
            control_loop.disconnect_forecaster,
        ):
            with (
                self.subTest(disconnect=disconnect.__name__),
                patch.object(control_loop, '_CONTROL_STATE', control_loop._ControlState()),
                patch.object(control_loop, '_REGISTERS'),
                patch.object(control_loop._REGISTERS, 'update_controller', new=AsyncMock()),
                patch.object(control_loop, 'log_info') as info_log,
            ):
                await disconnect()
                info_log.assert_called_once()
                self.assertIn('already disconnected', info_log.call_args.args[0])

    async def test_connect_and_disconnect_log_success(self) -> None:
        for name, connect, disconnect, settings in (
            ('controller', control_loop.connect_controller, control_loop.disconnect_controller,
             DummyControllerConnection()),
            ('pricer', control_loop.connect_pricer, control_loop.disconnect_pricer, DummyPricerConnection()),
            ('forecaster', control_loop.connect_forecaster, control_loop.disconnect_forecaster,
             DummySolarForecasterConnection()),
        ):
            state = control_loop._ControlState()
            with (
                self.subTest(delegate=name),
                patch.object(control_loop, '_CONTROL_STATE', state),
                patch.object(control_loop, '_REGISTERS'),
                patch.object(control_loop._REGISTERS, 'update_controller', new=AsyncMock()),
                patch.object(control_loop, 'log_info') as info_log,
            ):
                await connect(settings)
                self.assertIsNotNone(getattr(state.connections, name))
                info_log.assert_called_once()
                self.assertIn('connection:', info_log.call_args.args[0])

                info_log.reset_mock()
                await disconnect()
                self.assertIsNone(getattr(state.connections, name))
                info_log.assert_called_once()
                self.assertTrue(info_log.call_args.args[0].endswith('disconnected'))
