"""
Mirror Solala log messages into active NiceGUI log consoles.

A shared logging handler retains a bounded message history so newly opened
consoles can display recent messages immediately.
"""

import logging
import threading
from nicegui import ui
from nicegui.element import Element

from solala.constants import Constants, GUI_LOG_FORMAT
from solala.logger import LOGGER


class _GuiLogHandler(logging.Handler):
    """
    Forward Solala log records to registered NiceGUI elements.

    The handler formats each record, appends it to a bounded history, and
    displays it in every registered log console. A lock protects updates to
    the history and active consoles during emission, registration and removal.
    """

    def __init__(self) -> None:
        super().__init__()
        self._log_elements: list[Element] = []
        self._history: list[str] = []
        self._lock = threading.Lock()
        self.setFormatter(logging.Formatter(GUI_LOG_FORMAT))
        LOGGER.addHandler(self)

    def emit(self, record: logging.LogRecord) -> None:
        """
        Append a formatted record to the history and active log consoles.

        Args:
            record: Log record to display and retain.
        """
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
        """
        Register a console and populate it with retained log messages.

        Args:
            element: NiceGUI container that receives log line labels.
        """
        with self._lock:
            if element in self._log_elements:
                self._log_elements.remove(element)
            for msg in self._history:
                with element:
                    ui.label(msg).classes('solala-log-line')
            self._log_elements.append(element)

    def remove(self, element: Element) -> None:
        """
        Unregister a console, ignoring elements that are not registered.

        Args:
            element: NiceGUI container to unregister.
        """
        with self._lock:
            try:
                self._log_elements.remove(element)
            except ValueError:
                pass


_LOG_HANDLER = _GuiLogHandler()


def add(element: Element) -> None:
    """
    Register a NiceGUI log console with the shared handler.

    Args:
        element: Container that receives log messages.
    """
    _LOG_HANDLER.add(element)


def remove(element: Element) -> None:
    """
    Unregister a NiceGUI log console from the shared handler.

    Args:
        element: Container to unregister.
    """
    _LOG_HANDLER.remove(element)
