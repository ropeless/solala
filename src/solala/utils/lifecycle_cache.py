import asyncio
from asyncio import Task
from dataclasses import dataclass
from enum import Enum, auto
from time import monotonic
from traceback import format_exception
from typing import Callable, Coroutine, Any, ClassVar

from solala.utils.sentinel import Sentinel

_NONE = Sentinel('_NONE')
_INITIAL = Sentinel('_INITIAL')
_ERROR = Sentinel('_ERROR')


class LifecycleState(Enum):
    VALID = auto()
    INTERIM = auto()


@dataclass
class ObjectReturn[T]:
    value: T
    state: LifecycleState


@dataclass
class ErrorReturn:
    message: str
    state: ClassVar[Sentinel] = _ERROR


def valid[T](value: T) -> ObjectReturn[T]:
    """
    Support a wrapped function to return a VALID object.
    """
    return ObjectReturn(value, LifecycleState.VALID)


def interim[T](value: T) -> ObjectReturn[T]:
    """
    Support a wrapped function to return an INTERIM object.
    """
    return ObjectReturn(value, LifecycleState.INTERIM)


def error(message: str) -> ErrorReturn:
    """
    Support a wrapped function to return an error condition.
    """
    return ErrorReturn(message)


type LifecycleReturn[T] = ObjectReturn[T] | ErrorReturn

type WrappedFunction[T] = Callable[[], Coroutine[Any, Any, LifecycleReturn[T]]]


class NoResult(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            'no usable result from the wrapped function, no cached result, and no default result available')


class LifecycleCache[T]:
    """
    Cache results of an asynchronous function using lifecycle states and age thresholds.

    The wrapped function takes no arguments and returns a LifecycleReturn[T].
    VALID provides a usable result. INTERIM provides a usable but provisional
    result that should be retried sooner. Both replace any previously cached
    value, even when an INTERIM result follows a VALID result.

    An ErrorReturn means the wrapped function could not obtain a value,
    for example because of a network, resource, or configuration problem. It is a refresh
    outcome, not an exception raised by LifecycleCache.__call__(). An error
    result does not replace the last usable cached value. The cache retains
    that value for fallback only while it remains younger than old. Once
    the cached value reaches old, it expires and is replaced by the
    configured default (or _NONE if no default was configured).

    If neither an unexpired cached value nor a configured default is
    available, __call__() raises NoResult. This means the cache cannot
    provide a result, even though the wrapped function returned ErrorReturn.
    Such a failure does not prevent future refresh attempts.

    If a default is configured, normal lifecycle operation never raises
    NoResult: a usable cached value or the default is always available,
    including after an ERROR result or cache expiration. This guarantee
    does not cover unexpected exceptions raised by the wrapped function,
    logging callbacks, or other programming errors.

    The internal _INITIAL sentinel means that no wrapped-function result has
    yet been received. Successful results have LifecycleState.VALID or
    LifecycleState.INTERIM; ErrorReturn uses the internal _ERROR sentinel.
    After a result is received, the cache state reflects that result, even
    if `__call__()` subsequently raises NoResult. It does not return to _INITIAL.
    None maybe a legitimate value of `T` or default; only _NONE denotes absence.
    Sentinel instances are not valid successful results.

    Both VALID and INTERIM cached values expire at age 'old'. Expiration
    replaces the cached value with the configured default; it does not
    change the lifecycle state or its timestamp. A default value never
    expires. An expired value must not be returned even if a refresh
    subsequently returns ErrorReturn.

    The cache tracks the latest result state and its monotonic timestamp.
    Age is the elapsed time since that result was received. This timestamp
    advances for VALID, INTERIM, and ErrorReturn alike. The timestamp of the last
    usable value is tracked separately so error refreshes cannot extend its
    lifetime.

    Three age thresholds control refreshes: retry, young, and old.
    They must satisfy 0 < retry <= young <= old. If omitted, young defaults
    to old and retry defaults to young.

    The intended behaviour of __call__() is:

    _INITIAL, any age:
        Await the wrapped function.

    _ERROR, age < retry:
        Return an unexpired cached value or the default; if neither
        exists, raise NoResult.

    _ERROR, retry <= age:
        Await the wrapped function; if it reports ERROR, use an unexpired
        cached value or the default, or raise NoResult if neither exists.

    INTERIM, result age < retry and cached-value age < old:
        Return the cached provisional value.

    INTERIM, retry <= result age and cached-value age < old:
        Await the wrapped function; the provisional value remains usable
        if the refresh reports ERROR.

    INTERIM, old <= cached-value age:
        Expire the cached value, then await the wrapped function. If it
        reports ERROR, return the default or raise NoResult.

    VALID, age < young:
        Return the cached value.

    VALID, young <= age < old:
        Start a background refresh and return the cached value.

    VALID, old <= age:
        Expire the cached value, then await the wrapped function. If it
        reports ERROR, return the default or raise NoResult.

    This cache assumes all callers use the same asyncio event loop and
    normal (non-eager) asyncio task scheduling. It is not thread-safe.
    Refresh task creation relies on these assumptions and does not use
    an explicit lock.

    At most one background refresh is intended to run at a time. If a
    foreground refresh is needed while a background refresh is running,
    the foreground caller awaits that existing task instead of cancelling
    it or starting another refresh. If the cached value has reached old,
    it must expire before awaiting the task.

    The wrapped function is responsible for catching exceptions it
    considers non-fatal and returning ErrorReturn instead.
    Other exceptions raised by the wrapped function propagate to
    foreground callers. Unexpected refresh exceptions are also logged
    with their traceback, regardless of whether a foreground caller awaits
    them or not.

    An unexpected exception does not change the lifecycle state,
    timestamps, or cached value. Any cache expiration performed before
    the refresh remains effective, so an expired value is not restored.
    The cache remains internally consistent, and subsequent calls can
    attempt another refresh.

    asyncio.CancelledError represents cancellation, not a lifecycle
    ERROR, and is not converted into one. Cancelling an individual
    foreground caller must not cancel a refresh shared with other callers.
    """

    def __init__(
            self,
            f: WrappedFunction[T],
            *,
            error_log: Callable[[str], None],
            info_log: Callable[[str], None],
            old: float,
            young: float | None = None,
            retry: float | None = None,
            default: T | Sentinel = _NONE,
            interim_message: str = 'interim value received: {value!r}',
            error_message: str = 'error calling cached function: {message!r}',
    ) -> None:
        """
        Initialize the lifecycle cache and its refresh policy.

        Args:
            f: Asynchronous function providing ObjectReturn or ErrorReturn.
            error_log: Callback for refresh errors and unexpected failures.
            info_log: Callback for provisional results.
            old: Maximum age of a cached result in seconds.
            young: Age at which a valid result triggers background refresh.
                Defaults to old.
            retry: Minimum interval between interim or error refresh attempts.
                Defaults to young.
            default: Fallback value when no unexpired cached value is available.
                None is valid; _NONE means no default.
            interim_message: Format string for logging provisional values.
            error_message: Format string for logging expected refresh errors.

        Raises:
            ValueError: If age thresholds are invalid or the default is
                an unsupported sentinel.
        """
        # Default values
        if young is None:
            young: float = old
        if retry is None:
            retry: float = young

        # Consistency checks
        if not 0 < retry <= young <= old:
            raise ValueError(f'ensure: `0 < retry <= young <= old`')
        if isinstance(default, Sentinel) and default is not _NONE:
            raise ValueError(f'cannot use a Sentinel as a default object: {default!r}')

        self._f: WrappedFunction[T] = f
        self._retry: float = retry
        self._young: float = young
        self._old: float = old
        self._default: T | Sentinel = default
        self._cache: T | Sentinel = default
        self._state: LifecycleState | Sentinel = _INITIAL
        self._timestamp: float = float('-inf')
        self._cache_timestamp: float = float('-inf')
        self._error_log: Callable[[str], None] = error_log
        self._info_log: Callable[[str], None] = info_log
        self._interim_message: str = interim_message
        self._error_message: str = error_message
        self._task: Task[None] | None = None

    async def __call__(self) -> T:
        """
        Return the cached value, managing refreshing of the cache
        according to the cache state and age.

        Returns:
            The cached or newly computed value.
        """
        # Expire usable values independently of the latest refresh result.
        # ERROR refreshes update _timestamp but do not extend cache lifetime.
        now: float = monotonic()
        old_cache: bool = now - self._cache_timestamp >= self._old
        if old_cache:
            self._cache = self._default

        if self._state is _INITIAL:
            return await self._refresh_and_get()
        elif self._state is LifecycleState.VALID:
            if old_cache:
                return await self._refresh_and_get()
            elif now - self._timestamp < self._young:
                return self._get_cached_value()
            else:
                self._get_or_create_refresh_task()
                return self._get_cached_value()
        elif self._state is LifecycleState.INTERIM and old_cache:
            return await self._refresh_and_get()
        elif now < self._timestamp + self._retry:
            # _ERROR | INTERIM with usable cache
            return self._get_cached_value()
        else:
            return await self._refresh_and_get()

    def _get_cached_value(self) -> T:
        """
        Return the cached value or configured default.

        Returns:
            The available value, which may be None.

        Raises:
            NoResult: If no cached value or default is available.
        """
        if self._cache is _NONE:
            raise NoResult()
        else:
            return self._cache

    async def _refresh_and_get(self) -> T:
        """
        Await the shared refresh task and return the resulting cached value.

        Shielding prevents cancellation of this caller from cancelling the
        shared refresh task.

        Returns:
            The refreshed value or an available fallback.
        """
        await asyncio.shield(self._get_or_create_refresh_task())
        return self._get_cached_value()

    def _get_or_create_refresh_task(self) -> Task[None]:
        """
        Return the active refresh task, creating one if necessary.

        Returns:
            The shared refresh task.
        """
        if self._task is None:
            task = asyncio.create_task(self._refresh())
            task.add_done_callback(self._refresh_done)
            self._task = task
            return task
        else:
            return self._task

    def _refresh_done(self, task: Task[None]) -> None:
        """
        Clear the completed refresh task and log unexpected failures.
        """
        if self._task is task:
            self._task = None
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            self._error_log(
                'unexpected exception refreshing cache:\n'
                + ''.join(format_exception(exception))
            )

    async def _refresh(self) -> None:
        """
        Refresh the cache using the wrapped function.

        Successful results replace the cached value. Error results update
        the lifecycle state without replacing an existing usable value.
        Called only by `_get_or_create_refresh_task()`.
        """
        lifecycle_return: LifecycleReturn[T] = await self._f()

        if isinstance(lifecycle_return, ObjectReturn):
            value: T = lifecycle_return.value
            if isinstance(value, Sentinel):
                raise ValueError(f'{value!r} is not a valid function return value')

        self._timestamp = monotonic()
        self._state = lifecycle_return.state
