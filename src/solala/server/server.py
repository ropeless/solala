import asyncio
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
    Run the server in the current thread.
    Spawns a thread for the control loop.

    Args:
        host: Host address to bind the server to.
        port: Port to bind the server to.

        settings_path: Path to the settings file, if settings are to be persisted. If provided, the control
            loop will attempt to load settings from the file.

        settings: Settings object to use if the settings file cannot be loaded.

        force_settings: If True, the given settings object will always override any settings loaded from the file.
            Note that if settings are provided, they will override any settings loaded from the file. This includes
            modes and policies if the power controller is reloaded.

        database_write: If False, the control loop will not write to the database. This is useful for testing.
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
    app = FastAPI()
    favicon: str = Path(str(IMAGE_FILES / 'solala-32x32.png')).absolute().as_posix()
    ui.run_with(app, title=Constants.APP_NAME, favicon=favicon)

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
    return asyncio.SelectorEventLoop(selectors.SelectSelector())
