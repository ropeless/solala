import asyncio
import importlib
import unittest
from unittest.mock import patch

control_loop = importlib.import_module('solala.control_loop.control_loop')


class ControlLoopShutdownTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Ensure the database task finishes before control_loop returns or raises.
    """

    async def test_normal_exit_cancels_and_awaits_database_task(self) -> None:
        await self._check_shutdown(None)

    async def test_control_loop_failure_cancels_and_awaits_database_task(self) -> None:
        with self.assertRaisesRegex(RuntimeError, 'control failed'):
            await self._check_shutdown(RuntimeError('control failed'))

    async def test_control_loop_cancellation_cancels_and_awaits_database_task(self) -> None:
        with self.assertRaises(asyncio.CancelledError):
            await self._check_shutdown(asyncio.CancelledError())

    async def _check_shutdown(self, failure: BaseException | None) -> None:
        database_started = asyncio.Event()
        database_finished = asyncio.Event()
        observed = []

        async def database_loop() -> None:
            try:
                database_started.set()
                await asyncio.Event().wait()
            finally:
                observed.append('database cleanup')
                database_finished.set()

        async def main_loop() -> None:
            await database_started.wait()
            if failure is not None:
                raise failure

        with (
            patch.object(control_loop, '_CONTROL_STATE', control_loop._ControlState()),
            patch.object(control_loop, '_database_loop', side_effect=database_loop),
            patch.object(control_loop, '_control_loop', side_effect=main_loop),
        ):
            try:
                await control_loop.control_loop(database_write=False)
            finally:
                self.assertTrue(database_finished.is_set())
                self.assertEqual(observed, ['database cleanup'])


if __name__ == '__main__':
    unittest.main()
