import asyncio
import unittest
from unittest.mock import MagicMock, patch

from solala.control.power_consumer_manager import PowerConsumerManager
from solala.control.register_manager import ConsumerRegister
from solala.delegates.power_consumer.dummy_power_consumer.dummy_power_consumer import DummyPowerConsumer
from solala.register_bank import RegisterBank
from solala.server.page_updaters import RegistersUpdater
from solala.server.register_filter import compile_register_filter


class _Register:
    def __init__(self, value: int) -> None:
        self.value = value
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()

    async def get(self) -> int:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return self.value


class RegistersUpdaterTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Exercise register reads without creating NiceGUI elements.
    """

    def setUp(self) -> None:
        self.session = MagicMock()
        self.session.closed = False
        self.tasks: list[asyncio.Task[None]] = []
        self.session.add_task.side_effect = self.tasks.append
        self.bank = {'first': _Register(1), 'second': _Register(2)}
        self.updater = object.__new__(RegistersUpdater)
        self.updater._session = self.session
        self.updater._bank = self.bank
        self.updater._values = {}
        self.updater._iteration = 0
        self.updater._read_generation = 0
        self.updater._read_task = None
        self.updater._filter = compile_register_filter('')
        self.updater._on_filter_change = None
        self.updater._error = MagicMock()
        self.updater._input = MagicMock()
        self.updater._render = MagicMock()

    async def asyncTearDown(self) -> None:
        for task in self.tasks:
            if not task.done():
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

    async def test_filter_limits_reads_and_reuses_values_in_iteration(self) -> None:
        self.updater.set_filter('first')
        await self.updater._read_task
        self.assertEqual(self.updater._values, {'first': 1})
        self.assertEqual(self.bank['second'].calls, 0)

        self.updater.set_filter('')
        await self.updater._read_task
        self.assertEqual(self.updater._values, {'first': 1, 'second': 2})
        self.assertEqual(self.bank['first'].calls, 1)

    async def test_new_iteration_invalidates_cached_values(self) -> None:
        self.updater.set_filter('')
        await self.updater._read_task
        self.bank['first'].value = 3

        with patch('solala.server.page_updaters.control_loop.get_register_bank', return_value=self.bank):
            await self.updater.update()
        await self.updater._read_task

        self.assertEqual(self.updater._values['first'], 3)
        self.assertEqual(self.bank['first'].calls, 2)

    async def test_cancelled_read_cannot_publish_stale_result(self) -> None:
        self.bank['first'].release.clear()
        self.updater.set_filter('')
        await self.bank['first'].started.wait()

        self.updater.set_filter('second')
        await self.updater._read_task
        self.assertEqual(self.updater._values, {'second': 2})

        self.bank['first'].release.set()
        await asyncio.sleep(0)
        self.assertEqual(self.updater._values, {'second': 2})

    async def test_superseded_read_cannot_publish_after_cancellation(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def cancellation_resistant_get() -> int:
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return 99

        self.bank['first'].get = cancellation_resistant_get
        self.updater.set_filter('first')
        old_task = self.updater._read_task
        await started.wait()

        self.updater.set_filter('second')
        await self.updater._read_task
        release.set()
        await old_task

        self.assertEqual(self.updater._values, {'second': 2})

    async def test_new_iteration_cancels_in_flight_read(self) -> None:
        self.bank['first'].release.clear()
        self.updater.set_filter('first')
        await self.bank['first'].started.wait()

        with patch('solala.server.page_updaters.control_loop.get_register_bank', return_value=self.bank):
            await self.updater.update()

        self.assertEqual(self.updater._values, {})
        self.bank['first'].value = 7
        self.bank['first'].release.set()
        await self.updater._read_task
        self.assertEqual(self.updater._values, {'first': 7})

    async def test_bank_replacement_discards_old_results(self) -> None:
        self.bank['first'].release.clear()
        self.updater.set_filter('first')
        await self.bank['first'].started.wait()

        replacement = {'first': _Register(5)}
        with patch('solala.server.page_updaters.control_loop.get_register_bank', return_value=replacement):
            await self.updater.update()
        await self.updater._read_task
        self.assertEqual(self.updater._values, {'first': 5})

        self.bank['first'].release.set()
        await asyncio.sleep(0)
        self.assertEqual(self.updater._values, {'first': 5})

    async def test_close_cancels_pending_read(self) -> None:
        self.bank['first'].release.clear()
        self.updater.set_filter('first')
        await self.bank['first'].started.wait()
        self.session.closed = True
        self.updater._read_task.cancel()
        await asyncio.gather(self.updater._read_task, return_exceptions=True)
        self.assertEqual(self.updater._values, {})

    async def test_failed_read_remains_unknown(self) -> None:
        self.bank['first'].get = MagicMock(side_effect=RuntimeError('unavailable'))
        with self.assertLogs('solala', level='DEBUG') as logs:
            self.updater.set_filter('first')
            task = self.updater._read_task
            assert task is not None
            await task
        self.assertEqual(self.updater._values, {})
        self.assertEqual(logs.records[0].getMessage(), 'Failed to read register first')
        self.assertIsNotNone(logs.records[0].exc_info)

    async def test_pending_consumer_register_is_quiet_and_reads_after_refresh(self) -> None:
        published = asyncio.Event()
        consumer = PowerConsumerManager(
            DummyPowerConsumer(power=120, current=1),
            on_read_complete=lambda *_: published.set(),
        )
        self.addAsyncCleanup(consumer.close)
        name = 'status/power/consumer/plug/power'
        bank = RegisterBank({name: ConsumerRegister(consumer, 'power', float)})
        self.updater._bank = bank

        with self.assertNoLogs('solala', level='DEBUG'):
            await self.updater._read_values(0, 0)
            self.assertEqual(self.updater._values, {})
            await asyncio.wait_for(published.wait(), 1)
            await self.updater._read_values(0, 0)

        self.assertEqual(self.updater._values, {name: 120})


if __name__ == '__main__':
    unittest.main()
