import math
import unittest

from solala.delegates.power_controller.modbus_power_controller.modbus_power_controller import ModbusPowerController
from solala.register import AsyncCallRegister
from solala.register_bank import RegisterBank


class ModbusPowerControllerTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Test Modbus control safety without connecting to physical hardware.
    """

    @staticmethod
    def make_controller(registers: dict[str, AsyncCallRegister]) -> ModbusPowerController:
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

        controller = self.make_controller({'r': AsyncCallRegister(read, float, write)})
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

        controller = self.make_controller({'r': AsyncCallRegister(read, float, write)})
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

        controller = self.make_controller({'r': AsyncCallRegister(read, float, write)})
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

                controller = self.make_controller({'r': AsyncCallRegister(read, float, write)})
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

        controller = self.make_controller({'r': AsyncCallRegister(read, float, write)})
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
