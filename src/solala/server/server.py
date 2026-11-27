"""
Start the Solala web server and control loop on a configured event loop.
"""

import asyncio
import selectors
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from solala.constants import Constants
from solala.control import control_loop
from solala.logger import LOGGER
from solala.resources import IMAGE_FILES
from solala.server.server_gui import ui
from solala.settings import Settings


class _Server(uvicorn.Server):
    """
    Share the HTTP shutdown deadline with the application lifespan.
    """

    shutdown_deadline: float | None = None

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        self.shutdown_deadline = asyncio.get_running_loop().time() + Constants.MAX_SHUTDOWN_TIMEOUT.total_seconds()
        await super().shutdown(sockets)


def run_server(
        host: str,
        port: int,
        *,
        solala_storage_secret: str,
        settings_path: Path | str | None = None,
        settings: Settings | None = None,
        force_settings: bool = False,
        database_write: bool = True,
) -> None:
    """
    Run the web server and control loop as async tasks in the current thread.

    Both coroutines run concurrently on the same asyncio event loop, created
    using a selector-based loop factory.

    Args:
        host: Host address to bind the server to.
        port: Port to bind the server to.
        settings_path: Optional settings file path used by the control loop.
        settings: Optional settings supplied to the control loop.
        force_settings: Whether to force the supplied settings rather than
            using values loaded from the settings file.
        database_write: Whether the control loop writes measurements to the
            database. The argument is useful for testing.
        solala_storage_secret: a long random string specific to the server.
    """
    try:
        with asyncio.Runner(loop_factory=_loop_factory) as runner:
            runner.run(_async_run_server(
                host=host,
                port=port,
                solala_storage_secret=solala_storage_secret,
                settings_path=settings_path,
                settings=settings,
                force_settings=force_settings,
                database_write=database_write,
            ))
    except KeyboardInterrupt:
        LOGGER.info(f'killed by keyboard interrupt')


async def _async_run_server(
        host: str,
        port: int,
        *,
        solala_storage_secret: str,
        settings_path: Path | str | None = None,
        settings: Settings | None = None,
        force_settings: bool = False,
        database_write: bool = True,
) -> None:
    """
    Initialise NiceGUI and run the HTTP server alongside the control loop.

    Args:
        host: Network interface or address to bind.
        port: HTTP listening port.
        settings_path: Optional settings file path for the control loop.
        settings: Optional control-loop settings.
        force_settings: Whether supplied settings override loaded settings.
        database_write: Whether to persist measurements to the database.
        solala_storage_secret: a long random string specific to the server.
    """
    cancelled_for_shutdown = False

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        nonlocal cancelled_for_shutdown
        try:
            yield
        finally:
            if not control_task.done():
                # Uvicorn waits for lifespan shutdown before replaying signals.
                loop = asyncio.get_running_loop()
                deadline = server.shutdown_deadline
                if deadline is None:
                    deadline = loop.time() + Constants.MAX_SHUTDOWN_TIMEOUT.total_seconds()
                control_loop.exit_control_loop(deadline=deadline)
                _, pending = await asyncio.wait((control_task,), timeout=max(0, deadline - loop.time()))
                if pending:
                    cancelled_for_shutdown = control_task.cancel()
                await asyncio.gather(control_task, return_exceptions=True)

    app = FastAPI(lifespan=lifespan)
    favicon: str = Path(str(IMAGE_FILES / 'solala-32x32.png')).absolute().as_posix()
    ui.run_with(
        app,
        title=Constants.APP_NAME,
        favicon=favicon,
        storage_secret=solala_storage_secret,
    )

    server_config = uvicorn.Config(
        app,
        host=host,
        port=port,
        workers=1,
        log_level='info',
        timeout_graceful_shutdown=int(Constants.MAX_SHUTDOWN_TIMEOUT.total_seconds()),
    )
    server = _Server(server_config)

    control_task = asyncio.create_task(
        control_loop.control_loop(settings_path, settings, force_settings, database_write)
    )

    def request_server_exit(_: asyncio.Task[None]) -> None:
        server.should_exit = True

    control_task.add_done_callback(request_server_exit)
    try:
        await server.serve()
    finally:
        # Startup failure and forced exit can bypass the lifespan shutdown.
        if not control_task.done() and server.shutdown_deadline is not None:
            control_loop.exit_control_loop(deadline=server.shutdown_deadline)
        cancelled_for_shutdown = control_task.cancel() or cancelled_for_shutdown
        await asyncio.gather(control_task, return_exceptions=True)
    if not cancelled_for_shutdown or not control_task.cancelled():
        control_task.result()


def _loop_factory() -> asyncio.AbstractEventLoop:
    """
    Create a selector-based asyncio event loop for the server.

    Returns:
        A new selector event loop.
    """
    return asyncio.SelectorEventLoop(selectors.SelectSelector())
