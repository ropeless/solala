import asyncio
from abc import ABC, abstractmethod
from asyncio import AbstractEventLoop


class LoopListener(ABC):
    """
    Abstract base class for listeners that want to be notified each loop iteration.
    """

    @abstractmethod
    async def update(self) -> None:
        ...
