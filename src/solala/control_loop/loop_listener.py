import asyncio
from abc import ABC, abstractmethod
from asyncio import AbstractEventLoop


class LoopListener(ABC):
    """
    Abstract base class for listeners that want to be notified each loop iteration.
    """

    def __init__(self) -> None:
        self._event_loop: AbstractEventLoop = asyncio.get_running_loop()

    @property
    def event_loop(self) -> AbstractEventLoop:
        return self._event_loop

    @abstractmethod
    async def update(self) -> None:
        ...
