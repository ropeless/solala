import logging
import math
import unittest

from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock, patch

from solala.delegates.power_controller.modbus_power_controller.modbus_power_controller import ModbusPowerController

from solala.register import AsyncCallRegister, Register, RegisterValue
from solala.register_bank import RegisterBank
from solala.logger import LOGGER


class _WritableRegister(Register):
    def __init__(
            self,
            read: Callable[[], Awaitable[RegisterValue]],
            write: Callable[[RegisterValue], Awaitable[None]],
    ) -> None:
        super().__init__(float, writable=True)
        self._read = read
        self._write = write

    async def _get(self) -> RegisterValue:
        return await self._read()

    async def _set(self, value: RegisterValue) -> None:
        await self._write(value)


class ModbusPowerControllerTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Test Modbus control safety without connecting to physical hardware.
    """

    def setUp(self) -> None:
        """
        Suppress routine Solala logging without changing other test output.
        """
        handlers = patch.object(LOGGER, 'handlers', [logging.NullHandler()])
        propagation = patch.object(LOGGER, 'propagate', False)
        handlers.start()
        propagation.start()
        self.addCleanup(propagation.stop)
        self.addCleanup(handlers.stop)

    @staticmethod
    def make_controller(registers: dict[str, Register]) -> ModbusPowerController:
        # These tests exercise register operations without the hardware-dependent
        # constructor, which normally discovers devices and their Modbus models.
        controller = object.__new__(ModbusPowerController)
        controller._modbus = RegisterBank(registers)
        return controller

    async def test_set_rejects_nonfinite_requests_before_read_or_write(self) -> None:
        calls: list[str] = []

        async def read() -> float:
            calls.append('read')
            return 5.0

        async def write(value: float) -> None:
            calls.append('write')

        controller = self.make_controller({'r': _WritableRegister(read, write)})
        for invalid in (math.nan, math.inf, -math.inf):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    await controller._set('r', invalid)
        self.assertEqual(calls, [])

    async def test_set_skips_unchanged_value_unless_forced(self) -> None:
        calls: list[float] = []

        async def read() -> float:
            return 12.0

        async def write(value: float) -> None:
            calls.append(value)

        controller = self.make_controller({'r': _WritableRegister(read, write)})
        await controller._set('r', 12.0)
        self.assertEqual(calls, [])
        await controller._set('r', 12.0, force=True)
        self.assertEqual(calls, [12.0])

    async def test_set_propagates_write_failure(self) -> None:
        failure = OSError('write failed')

        async def read() -> float:
            return 1.0

        async def write(value: float) -> None:
            raise failure

        controller = self.make_controller({'r': _WritableRegister(read, write)})
        with self.assertRaises(OSError) as caught:
            await controller._set('r', 2.0)
        self.assertIs(caught.exception, failure)

    async def test_set_rejects_bad_readback(self) -> None:
        for returned in (3.0, math.nan, math.inf, -math.inf):
            with self.subTest(returned=returned):
                reads = 0

                async def read() -> float:
                    nonlocal reads
                    reads += 1
                    return 1.0 if reads == 1 else returned

                async def write(value: float) -> None:
                    pass

                controller = self.make_controller({'r': _WritableRegister(read, write)})
                with self.assertRaises(ValueError):
                    await controller._set('r', 2.0)
                self.assertEqual(reads, 2)

    async def test_set_propagates_readback_exception(self) -> None:
        failure = OSError('readback failed')
        reads = 0

        async def read() -> float:
            nonlocal reads
            reads += 1
            if reads == 2:
                raise failure
            return 1.0

        async def write(value: float) -> None:
            pass

        controller = self.make_controller({'r': _WritableRegister(read, write)})
        with self.assertRaises(OSError) as caught:
            await controller._set('r', 2.0)
        self.assertIs(caught.exception, failure)

    async def test_status_read_failure_returns_nan(self) -> None:
        failure = OSError('read failed')

        async def read() -> float:
            raise failure

        controller = self.make_controller({'r': AsyncCallRegister(read, float)})
        self.assertTrue(math.isnan(await controller._get_for_status('r')))

    async def test_status_sum_preserves_other_reads_and_returns_nan(self) -> None:
        calls: list[str] = []

        async def failed() -> float:
            calls.append('bad')
            raise OSError('offline')

        async def good() -> float:
            calls.append('good')
            return 10.0

        controller = self.make_controller({
            'bad': AsyncCallRegister(failed, float),
            'good': AsyncCallRegister(good, float),
        })
        self.assertTrue(math.isnan(await controller._get_sum_for_status(['bad', 'good'])))
        self.assertEqual(calls, ['bad', 'good'])

    async def test_control_get_propagates_failure(self) -> None:
        failure = OSError('read failed')

        async def read() -> float:
            raise failure

        controller = self.make_controller({'r': AsyncCallRegister(read, float)})
        with self.assertRaises(OSError) as caught:
            await controller._get('r')
        self.assertIs(caught.exception, failure)

    async def test_power_limit_single_inverter(self) -> None:
        async def read_limit() -> float:
            return 40.0

        enabled = 1.0

        async def read_enabled() -> float:
            return enabled

        controller = self.make_controller({
            'limit': AsyncCallRegister(read_limit, float),
            'enabled': AsyncCallRegister(read_enabled, float),
        })
        controller._WMaxLimPct = ['limit']
        controller._WMaxLim_Ena = ['enabled']
        self.assertEqual(await controller._get_power_limit(), 40.0)
        enabled = 0.0
        self.assertEqual(await controller._get_power_limit(), 100.0)

    @staticmethod
    def make_zero_export_controller(
            *, grid_power: float, inverter_power: float = 4000.0,
            limit_pct: float = 50.0, capacity: float = 8000.0,
            discharge_power: float = 0.0,
    ) -> ModbusPowerController:
        controller = object.__new__(ModbusPowerController)
        controller._hunt_history = []
        controller._power_controllers = ['master']
        controller._W = ['master/W']
        controller._grid_power = 'meter/W'
        controller._discharge_power = 'master/module/4/DCW'
        controller._get_power_limit = AsyncMock(return_value=limit_pct)
        controller._get_inverter_limit_array = AsyncMock(return_value=[capacity])
        controller._get_sum = AsyncMock(return_value=inverter_power)
        controller._is_force_discharge_enabled = AsyncMock(return_value=False)
        controller._set_power_pct = AsyncMock()

        async def get_register(name: str) -> float:
            if name == controller._grid_power:
                return grid_power
            if name == controller._discharge_power:
                return discharge_power
            raise AssertionError(f'unexpected register: {name}')

        controller._get = AsyncMock(side_effect=get_register)
        return controller

    async def test_zero_export_exact_method_reduces_limit_on_export(self) -> None:
        controller = self.make_zero_export_controller(grid_power=-3000.0)
        await controller.zero_export(change_duration=11)
        controller._set_power_pct.assert_awaited_once_with(12.5, 11)
        self.assertEqual(controller._hunt_history, [])

    async def test_zero_export_exact_method_increases_limit_on_import(self) -> None:
        controller = self.make_zero_export_controller(grid_power=3000.0)
        await controller.zero_export(change_duration=11)
        controller._set_power_pct.assert_awaited_once_with(87.5, 11)

    async def test_zero_export_hunting_method(self) -> None:
        controller = self.make_zero_export_controller(grid_power=-800.0)
        await controller.zero_export(change_duration=11)
        controller._set_power_pct.assert_awaited_once_with(49.0, 11)
        self.assertEqual(controller._hunt_history, [-800.0])

    async def test_zero_export_deadband(self) -> None:
        controller = self.make_zero_export_controller(grid_power=-50.0)
        controller._hunt_history = [100.0]
        await controller.zero_export(change_duration=11)
        controller._set_power_pct.assert_awaited_once_with(50.0, 11)
        self.assertEqual(controller._hunt_history, [])

    async def test_zero_export_accounts_for_battery_discharge(self) -> None:
        controller = self.make_zero_export_controller(
            grid_power=-3000.0, inverter_power=3000.0, discharge_power=1000.0,
        )
        await controller.zero_export(change_duration=11)
        controller._set_power_pct.assert_awaited_once_with(12.5, 11)

    async def test_zero_export_rejects_unavailable_limit_without_writes(self) -> None:
        controller = self.make_zero_export_controller(grid_power=-3000.0, limit_pct=math.nan)
        with self.assertRaises(ValueError):
            await controller.zero_export(change_duration=11)
        controller._set_power_pct.assert_not_awaited()
        controller._get.assert_not_awaited()

    async def test_zero_export_propagates_meter_failure_without_writes(self) -> None:
        controller = self.make_zero_export_controller(grid_power=-3000.0)
        failure = OSError('meter unavailable')
        controller._get = AsyncMock(side_effect=failure)
        with self.assertRaises(OSError) as caught:
            await controller.zero_export(change_duration=11)
        self.assertIs(caught.exception, failure)
        controller._set_power_pct.assert_not_awaited()

    async def test_zero_export_propagates_command_failure(self) -> None:
        controller = self.make_zero_export_controller(grid_power=-3000.0)
        failure = OSError('write failed')
        controller._set_power_pct.side_effect = failure
        with self.assertRaises(OSError) as caught:
            await controller.zero_export(change_duration=11)
        self.assertIs(caught.exception, failure)
