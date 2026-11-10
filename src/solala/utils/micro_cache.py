from datetime import datetime
from typing import Callable, Awaitable


class MicroCache[T]:
    """
    An object that caches a value for a short duration of time.
    """

    def __init__(
            self,
            f: Callable[[], T],
            cache_time: float,
    ):
        """
        Initialise a MicroCache object.

        Args:
            f (Callable[[], T]): function that gives the object to be cached.
            cache_time (float): time in seconds to cache the object.
        """
        self._f = f
        self._cache_time: float = cache_time
        self._cache: T
        self._cache_timestamp: float = 0

    def __call__(self) -> T:
        timestamp: float = datetime.now().timestamp()
        if timestamp >= self._cache_timestamp:
            self._cache = self._f()
            self._cache_timestamp = timestamp + self._cache_time

        return self._cache


class AsyncMicroCache[T]:
    """
    An object that caches a value for a short duration of time.
    """

    def __init__(
            self,
            f: Callable[[], Awaitable[T]],
            cache_time: float,
    ):
        """
        Initialise a MicroCache object.

        Args:
            f (Callable[[], T]): awaitable function that gives the object to be cached.
            cache_time (float): time in seconds to cache the object.
        """
        self._f = f
        self._cache_time: float = cache_time
        self._cache: T
        self._cache_timestamp: float = 0

    async def __call__(self) -> T:
        timestamp: float = datetime.now().timestamp()
        if timestamp >= self._cache_timestamp:
            self._cache = await self._f()
            self._cache_timestamp = timestamp + self._cache_time

        return self._cache
