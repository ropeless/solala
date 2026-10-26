import asyncio
from abc import ABC, abstractmethod
from asyncio import AbstractEventLoop
from typing import Optional


class LoopListener(ABC):
    """
    Abstract base class for listeners that want to be notified each loop iteration.
    """

    def __init__(self, event_loop: Optional[AbstractEventLoop] = None):
        if event_loop is None:
            event_loop = asyncio.get_running_loop()
        # Store the event loop for use by the control loop
        self._event_loop: AbstractEventLoop = event_loop

    @abstractmethod
    async def update(self) -> None:
        ...
