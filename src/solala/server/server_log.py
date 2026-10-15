import logging
import threading
from typing import List

from nicegui import ui

from solala.constants import Constants
from solala.logger import LOGGER, SOLALA_LOG_FORMAT


class _GuiLogHandler(logging.Handler):
    """
    A custom logging Handler that writes the Solala logger
    to NiceGUI ui.log components.
    """

    def __init__(self):
        super().__init__()
        self._log_elements: List[ui.log] = []
        self._history: List[str] = []
        self._lock = threading.Lock()
        self.setFormatter(logging.Formatter(SOLALA_LOG_FORMAT))
        LOGGER.addHandler(self)

    def emit(self, record):
        try:
            # Format the log message using the handler's formatter
            msg = self.format(record)
            with self._lock:
                # Push the message to the NiceGUI UI element
                for ui_log in self._log_elements:
                    ui_log.push(msg)
                # Add to history
                self._history.append(msg)
                while len(self._history) > Constants.MAX_LOG_HISTORY:
                    self._history.pop(0)
        except (IOError, ValueError, RuntimeError):
            self.handleError(record)

    def add(self, element: ui.log) -> None:
        self.remove(element)
        with self._lock:
            for msg in self._history:
                element.push(msg)
            self._log_elements.append(element)

    def remove(self, element: ui.log) -> None:
        try:
            self._log_elements.remove(element)
        except ValueError:
            pass


_LOG_HANDLER = _GuiLogHandler()


def add(element: ui.log) -> None:
    _LOG_HANDLER.add(element)


def remove(element: ui.log) -> None:
    _LOG_HANDLER.remove(element)
