import asyncio
import threading
from functools import partial
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI

from solala.constants import APP_NAME
from solala.control_loop import control_loop
from solala.logger import LOGGER
from solala.resources import IMAGE_FILES
from solala.server.server_gui import ui
from solala.settings import Settings


def run_server(
        host: str,
        port: int,
        settings_path: Optional[Path | str] = None,
        settings: Optional[Settings] = None,
        force_settings: bool = False,
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
    """
    app = FastAPI()
    favicon: str = Path(str(IMAGE_FILES / 'solala-32x32.png')).absolute().as_posix()
    ui.run_with(app, title=APP_NAME, favicon=favicon)

    # Start the control loop in a separate thread.
    coroutine = control_loop.control_loop(settings_path, settings, force_settings)
    target = partial(asyncio.run, coroutine)
    control_loop_thread = threading.Thread(target=target, daemon=True)
    control_loop_thread.start()

    uvicorn.run(app, host=host, port=port, workers=1, log_level='info')

    # Cleanly stop the control loop thread
    control_loop.exit_control_loop()
    LOGGER.info('waiting for the control loop to terminate')
    control_loop_thread.join()
