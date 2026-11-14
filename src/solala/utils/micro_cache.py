from collections.abc import Awaitable, Callable
from time import monotonic

from solala.utils.sentinel import Sentinel

_UNSET = Sentinel('_UNSET')


class _BaseMicroCache:
    """
    Common implementation for synchronous and asynchronous micro-caches.
    """

    def __init__(self, cache_time: float) -> None:
        self._cache_time: float = cache_time
        self._cache_timestamp: float = float('-inf')

    def _is_expired(self) -> bool:
        return monotonic() >= self._cache_timestamp

    def _update_timestamp(self) -> None:
        self._cache_timestamp = monotonic() + self._cache_time


class MicroCache[T](_BaseMicroCache):
    """
    Cache the result of a synchronous function for a short duration.
    """

    def __init__(
            self,
            f: Callable[[], T],
            cache_time: float,
    ) -> None:
        super().__init__(cache_time)
        self._f = f
        self._cache: T | Sentinel = _UNSET

    def __call__(self) -> T:
        if self._is_expired() or self._cache is _UNSET:
            self._cache = self._f()
            self._update_timestamp()

        return self._cache


class AsyncMicroCache[T](_BaseMicroCache):
    """
    Cache the result of an asynchronous function for a short duration.
    """

    def __init__(
            self,
            f: Callable[[], Awaitable[T]],
            cache_time: float,
    ) -> None:
        super().__init__(cache_time)
        self._f = f
        self._cache: T | Sentinel = _UNSET

    async def __call__(self) -> T:
        if self._is_expired() or self._cache is _UNSET:
            self._cache = await self._f()
            self._update_timestamp()

        return self._cache
