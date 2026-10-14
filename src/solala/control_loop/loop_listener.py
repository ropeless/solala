from abc import ABC, abstractmethod


class LoopListener(ABC):
    """
    Abstract base class for listeners that want to be notified each loop iteration.
    """

    @abstractmethod
    def update(self) -> None:
        ...
