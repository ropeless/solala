from collections.abc import Awaitable, Callable
from time import monotonic

from solala.utils.sentinel import Sentinel

_UNSET = Sentinel('_UNSET')


class _BaseMicroCache:
    """
    Share expiry tracking for synchronous and asynchronous micro-caches.

    Expiry is based on a monotonic clock and is updated after a successful
    refresh. A cache duration of zero causes every call to refresh.
    """

    def __init__(self, cache_time: float) -> None:
        """
        Initialise the cache expiry interval.

        Args:
            cache_time: Number of seconds for which a refreshed value remains valid.
        """
        self._cache_time: float = cache_time
        self._cache_timestamp: float = float('-inf')

    def _is_expired(self) -> bool:
        return monotonic() >= self._cache_timestamp

    def _update_timestamp(self) -> None:
        self._cache_timestamp = monotonic() + self._cache_time


class MicroCache[T](_BaseMicroCache):
    """
    Cache the result of a synchronous zero-argument function.

    The function is called on first access and again after the cache expires.
    Exceptions propagate to the caller without updating the expiry time.
    Calls are not synchronised across threads.
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
        """
        Return the cached value, refreshing it when expired.

        Returns:
            The cached or newly computed value.
        """
        if self._is_expired() or self._cache is _UNSET:
            self._cache = self._f()
            self._update_timestamp()

        return self._cache


class AsyncMicroCache[T](_BaseMicroCache):
    """
    Cache the result of an asynchronous zero-argument function.

    The function is awaited on first access and again after the cache expires.
    Exceptions propagate to the caller without updating the expiry time.
    Concurrent callers are not coalesced and may refresh the cache separately.
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
        """
        Return the cached value, awaiting a refresh when expired.

        Returns:
            The cached or newly computed value.
        """
        if self._is_expired() or self._cache is _UNSET:
            self._cache = await self._f()
            self._update_timestamp()

        return self._cache
