"""
Start the Solala web server and control loop on a configured event loop.
"""

import asyncio
import os
import selectors
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from solala.constants import Constants
from solala.control_loop import control_loop
from solala.logger import LOGGER
from solala.resources import IMAGE_FILES
from solala.server.server_gui import ui
from solala.settings import Settings


def run_server(
        host: str,
        port: int,
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
    """
    try:
        with asyncio.Runner(loop_factory=_loop_factory) as runner:
            runner.run(_async_run_server(host, port, settings_path, settings, force_settings, database_write))
    except KeyboardInterrupt:
        LOGGER.info(f'killed by keyboard interrupt')


async def _async_run_server(
        host: str,
        port: int,
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
    """
    app = FastAPI()
    favicon: str = Path(str(IMAGE_FILES / 'solala-32x32.png')).absolute().as_posix()
    ui.run_with(
        app,
        title=Constants.APP_NAME,
        favicon=favicon,
        storage_secret=os.environ.get('SOLALA_STORAGE_SECRET'),
    )

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        workers=1,
        log_level='info',
    )
    server = uvicorn.Server(config)

    await asyncio.gather(
        control_loop.control_loop(settings_path, settings, force_settings, database_write),
        server.serve(),
    )


def _loop_factory() -> asyncio.AbstractEventLoop:
    """
    Create a selector-based asyncio event loop for the server.

    Returns:
        A new selector event loop.
    """
    return asyncio.SelectorEventLoop(selectors.SelectSelector())
