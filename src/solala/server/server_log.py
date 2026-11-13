import logging
import threading
from nicegui import ui
from nicegui.element import Element

from solala.constants import Constants, GUI_LOG_FORMAT
from solala.logger import LOGGER


class _GuiLogHandler(logging.Handler):
    """
    A custom logging Handler that writes the Solala logger
    to NiceGUI ui.log components.
    """

    def __init__(self):
        super().__init__()
        self._log_elements: list[Element] = []
        self._history: list[str] = []
        self._lock = threading.Lock()
        self.setFormatter(logging.Formatter(GUI_LOG_FORMAT))
        LOGGER.addHandler(self)

    def emit(self, record):
        try:
            # Format the log message using the handler's formatter
            msg = self.format(record)
            with self._lock:
                # Push the message to the NiceGUI UI element
                for ui_log in self._log_elements:
                    with ui_log:
                        ui.label(msg).classes('solala-log-line')
                # Add to history
                self._history.append(msg)
                while len(self._history) > Constants.MAX_LOG_HISTORY:
                    self._history.pop(0)
        except (IOError, ValueError, RuntimeError):
            self.handleError(record)

    def add(self, element: Element) -> None:
        self.remove(element)
        with self._lock:
            for msg in self._history:
                with element:
                    ui.label(msg).classes('solala-log-line')
            self._log_elements.append(element)

    def remove(self, element: Element) -> None:
        try:
            self._log_elements.remove(element)
        except ValueError:
            pass


_LOG_HANDLER = _GuiLogHandler()


def add(element: Element) -> None:
    _LOG_HANDLER.add(element)


def remove(element: Element) -> None:
    _LOG_HANDLER.remove(element)
