import logging
from typing import List

from nicegui import ui

from solala.log import SOLALA_LOG_FORMAT, LOGGER

_APP_NAME: str = 'Solala'


class NiceGuiLogHandler(logging.Handler):
    """
    A custom logging Handler that writes the Solala logger
    to NiceGUI ui.log components.
    """

    def __init__(self):
        super().__init__()
        self._log_elements: List[ui.log] = []
        self.setFormatter(logging.Formatter(SOLALA_LOG_FORMAT))
        LOGGER.addHandler(self)

    def emit(self, record):
        try:
            # Format the log message using the handler's formatter
            msg = self.format(record)
            # Push the message to the NiceGUI UI element
            for ui_log in self._log_elements:
                ui_log.push(msg)
        except Exception:
            self.handleError(record)

    def add(self, element: ui.log) -> None:
        self.remove(element)
        self._log_elements.append(element)

    def remove(self, element: ui.log) -> None:
        try:
            self._log_elements.remove(element)
        except ValueError:
            pass


HANDLER = NiceGuiLogHandler()


@ui.page('/log')
def log_page():
    """
    Listens to the Solala logger.
    """
    with ui.column().style('width: 100vw; height: 100vh; position: fixed; top: 0; left: 0;').classes('no-wrap p-2'):
        ui.label(f'{_APP_NAME} log console').classes('text-h6 mb-1')
        log_ui = ui.log(max_lines=None).classes(
            'w-full grow min-h-0 text-mono text-body2 p-2 overflow-auto'
        )
        ui.context.client.on_disconnect(lambda: HANDLER.remove(log_ui))
        HANDLER.add(log_ui)
