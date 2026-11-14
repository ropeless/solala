from typing import Protocol


class LoopListener(Protocol):
    """
    Protocol for listeners that are notified on each control loop iteration.
    """

    async def update(self) -> None:
        ...
