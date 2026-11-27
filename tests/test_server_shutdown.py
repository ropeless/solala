import asyncio
import unittest
from datetime import timedelta
from unittest.mock import patch

from fastapi import FastAPI
from uvicorn import Server

from solala.control import control_loop
from solala.delegates.power_consumer.consumer_status import ConsumerStatus
from solala.delegates.power_consumer.dummy_power_consumer.dummy_power_consumer import DummyPowerConsumer
from solala.server import server
from solala.settings import ConsumerConnection, DummyConsumerConnection, Settings


class ServerShutdownTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify server shutdown joins control-loop resources before leaving the event loop.
    """

    async def test_lifespan_shutdown_awaits_a_pending_consumer_read_and_close(self) -> None:
        for close_error in (None, OSError('close failed')):
            with self.subTest(close_error=close_error):
                await self._check_lifespan_shutdown(close_error)

    async def _check_lifespan_shutdown(self, close_error: Exception | None) -> None:
        state = control_loop._ControlState()
        started = asyncio.Event()
        release = asyncio.Event()
        read_finished = asyncio.Event()
        closed_before_serve_returned: list[bool] = []
        consumers: dict[str, ConsumerConnection] = {'plug': DummyConsumerConnection()}

        async def get_status(_: DummyPowerConsumer) -> ConsumerStatus:
            started.set()
            await release.wait()
            read_finished.set()
            return ConsumerStatus(on=False, power=0, voltage=240, current=0, accumulated_energy=None)

        async def close(_: DummyPowerConsumer) -> None:
            self.assertTrue(read_finished.is_set())
            if close_error is not None:
                raise close_error

        async def control_step() -> None:
            state.connections.consumers['plug'].try_get_status()
            await state.control_changed.wait()

        async def serve(instance: Server) -> None:
            app = instance.config.app
            assert isinstance(app, FastAPI)
            async with app.router.lifespan_context(app):
                await started.wait()
                asyncio.get_running_loop().call_soon(release.set)
            closed_before_serve_returned.append(bool(close_delegate.await_count))
            control_loop.exit_control_loop()

        with (
            patch('nicegui.ui.run_with'),
            patch.object(Server, 'serve', autospec=True, side_effect=serve),
            patch.object(control_loop, '_CONTROL_STATE', state),
            patch.object(control_loop, '_REGISTERS'),
            patch.object(control_loop, '_control_loop', side_effect=control_step),
            patch.object(control_loop, 'log_info') as info,
            patch.object(control_loop, 'log_error') as error,
            patch.object(DummyPowerConsumer, 'get_status', autospec=True, side_effect=get_status),
            patch.object(DummyPowerConsumer, 'close', autospec=True, side_effect=close) as close_delegate,
        ):
            await asyncio.wait_for(server._async_run_server(
                'localhost', 0, settings=Settings(consumers=consumers),
                solala_storage_secret='test', database_write=False,
            ), 2)
            self.assertEqual(closed_before_serve_returned, [True])
            close_delegate.assert_awaited_once()
            if close_error is None:
                info.assert_any_call("Closed power consumer 'plug' during control-loop shutdown")
                error.assert_not_called()
            else:
                error.assert_called_once_with(
                    "Failed to close power consumer 'plug' during control-loop shutdown: OSError('close failed')"
                )

    async def test_server_return_without_lifespan_joins_control_loop(self) -> None:
        await self._check_server_without_lifespan(None)

    async def test_server_failure_without_lifespan_joins_control_loop(self) -> None:
        with self.assertRaisesRegex(RuntimeError, 'server failed'):
            await self._check_server_without_lifespan(RuntimeError('server failed'))

    async def test_server_cancellation_without_lifespan_joins_control_loop(self) -> None:
        with self.assertRaises(asyncio.CancelledError):
            await self._check_server_without_lifespan(asyncio.CancelledError())

    async def _check_server_without_lifespan(self, failure: BaseException | None) -> None:
        started = asyncio.Event()
        finished = asyncio.Event()

        async def run_control(*_: object) -> None:
            started.set()
            try:
                await asyncio.Future()
            finally:
                finished.set()

        async def serve(_: Server) -> None:
            await started.wait()
            if failure is not None:
                raise failure

        with (
            patch('nicegui.ui.run_with'),
            patch.object(Server, 'serve', autospec=True, side_effect=serve),
            patch.object(control_loop, 'control_loop', side_effect=run_control),
        ):
            try:
                await asyncio.wait_for(server._async_run_server(
                    'localhost', 0, solala_storage_secret='test', database_write=False,
                ), 2)
            finally:
                self.assertTrue(finished.is_set())

    async def test_control_loop_failure_requests_server_exit(self) -> None:
        serving = asyncio.Event()

        async def run_control(*_: object) -> None:
            await serving.wait()
            raise RuntimeError('control failed')

        async def serve(instance: Server) -> None:
            app = instance.config.app
            assert isinstance(app, FastAPI)
            async with app.router.lifespan_context(app):
                serving.set()
                while not instance.should_exit:
                    await asyncio.sleep(0)

        with (
            patch('nicegui.ui.run_with'),
            patch.object(Server, 'serve', autospec=True, side_effect=serve),
            patch.object(control_loop, 'control_loop', side_effect=run_control),
            self.assertRaisesRegex(RuntimeError, 'control failed'),
        ):
            await asyncio.wait_for(server._async_run_server(
                'localhost', 0, solala_storage_secret='test', database_write=False,
            ), 2)

    async def test_lifespan_uses_the_remaining_http_shutdown_budget(self) -> None:
        started = asyncio.Event()
        finished = asyncio.Event()

        async def run_control(*_: object) -> None:
            started.set()
            try:
                await asyncio.Future()
            finally:
                finished.set()

        async def serve(instance: Server) -> None:
            app = instance.config.app
            assert isinstance(app, FastAPI)
            async with app.router.lifespan_context(app):
                await started.wait()
                with patch.object(server.Constants, 'MAX_SHUTDOWN_TIMEOUT', timedelta()):
                    await instance.shutdown()
            self.assertTrue(finished.is_set())

        with (
            patch('nicegui.ui.run_with'),
            patch.object(Server, 'serve', autospec=True, side_effect=serve),
            patch.object(Server, 'shutdown', autospec=True),
            patch.object(control_loop, '_CONTROL_STATE', control_loop._ControlState()),
            patch.object(control_loop, 'control_loop', side_effect=run_control),
        ):
            await asyncio.wait_for(server._async_run_server(
                'localhost', 0, solala_storage_secret='test', database_write=False,
            ), 2)
