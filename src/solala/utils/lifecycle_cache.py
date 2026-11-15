import asyncio
from asyncio import Task
from dataclasses import dataclass
from enum import Enum, auto
from time import monotonic
from traceback import format_exception
from typing import Callable, Coroutine, Any

from solala.utils.sentinel import Sentinel

_NONE = Sentinel('_NONE')
_INITIAL = Sentinel('_INITIAL')


class LifecycleState(Enum):
    VALID = auto()
    INTERIM = auto()
    ERROR = auto()


@dataclass
class LifecycleReturn[T]:
    value: T | None
    state: LifecycleState
    message: str = ''


def valid[T](value: T) -> LifecycleReturn[T]:
    """
    Support a wrapped function to return a VALID object.
    """
    return LifecycleReturn(value, state=LifecycleState.VALID)


def interim[T](value: T) -> LifecycleReturn[T]:
    """
    Support a wrapped function to return an INTERIM object.
    """
    return LifecycleReturn(value, state=LifecycleState.INTERIM)


def error[T](message: str) -> LifecycleReturn[T]:
    """
    Support a wrapped function to return an error condition.
    """
    return LifecycleReturn(None, state=LifecycleState.ERROR, message=message)


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

    ERROR means that the wrapped function could not obtain a value, for example
    because of a network, resource, or configuration problem. It is a refresh
    outcome, not an exception raised by LifecycleCache.__call__(). An ERROR
    result does not replace the last usable cached value. The cache retains
    that value for fallback only while it remains younger than old. Once
    the cached value reaches old, it expires and is replaced by the
    configured default (or _NONE if no default was configured).

    If neither an unexpired cached value nor a configured default is
    available, __call__() raises NoResult. This is a distinct failure: the cache cannot
    provide a result, even though the wrapped function has reported ERROR.
    Such a failure does not prevent future refresh attempts.

    If a default is configured, normal lifecycle operation never raises
    NoResult: a usable cached value or the default is always available,
    including after an ERROR result or cache expiration. This guarantee
    does not cover unexpected exceptions raised by the wrapped function,
    logging callbacks, or other programming errors.

    The internal INITIAL state means that no wrapped-function result has yet
    been received. INITIAL is not a LifecycleState returned by the wrapped
    function. After a result is received, the cache state is always the state
    returned by the wrapped function, including ERROR even if __call__()
    subsequently raises NoResult. The cache does not return to INITIAL.

    Both VALID and INTERIM cached values expire at age 'old'. Expiration
    replaces the cached value with the configured default; it does not
    change the lifecycle state or its timestamp. A default value never
    expires. An expired value must not be returned even if a refresh
    subsequently reports ERROR.

    The cache tracks the latest result state and its monotonic timestamp.
    Age is the elapsed time since that result was received. This timestamp
    advances for VALID, INTERIM, and ERROR alike. The timestamp of the last
    usable value is tracked separately so ERROR refreshes cannot extend its
    lifetime.

    Three age thresholds control refreshes: retry, young, and old.
    They must satisfy retry <= young <= old. If omitted, young defaults
    to old and retry defaults to young.

    The intended behaviour of __call__() is:

    INITIAL, any age:
        Await the wrapped function.

    ERROR, age < retry:
        Return an unexpired cached value or the default; if neither
        exists, raise NoResult.

    ERROR, retry <= age:
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
    considers non-fatal and returning LifecycleReturn(ERROR) instead.
    Other exceptions raised by the wrapped function propagate to
    foreground callers. Unexpected refresh exceptions are also logged
    with their traceback, whether or not a foreground caller awaits them.

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
        # Default values
        if young is None:
            young: float = old
        if retry is None:
            retry: float = young

        # Consistency checks
        if not retry <= young <= old:
            raise ValueError(f'ensure: `retry <= young <= old`')
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
            return await self._call_f()
        elif self._state is LifecycleState.VALID:
            if old_cache:
                return await self._call_f()
            elif now - self._timestamp < self._young:
                return self._cached_or_error()
            else:
                self._create_background_update()
                return self._cached_or_error()
        elif self._state is LifecycleState.INTERIM and old_cache:
            return await self._call_f()
        elif now < self._timestamp + self._retry:
            # LifecycleState.ERROR | LifecycleState.INTERIM with usable cache
            return self._cached_or_error()
        else:
            return await self._call_f()

    def _cached_or_error(self) -> T:
        """
        Return the cached value or raise an exception if there is no cached value.
        """
        if self._cache is _NONE:
            raise NoResult()
        else:
            return self._cache

    async def _call_f(self) -> T:
        """
        Call the wrapped function asynchronously, updating the
        cache according to the returned result.
        """
        await self._create_background_update()
        return self._cached_or_error()

    def _create_background_update(self) -> Task[None]:
        """
        Get the existing background update task or create a new one as needed.
        """
        if self._task is None:
            task = asyncio.create_task(self.__update())
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

    async def __update(self) -> None:
        """
        Update the cached value.
        This should only ever be called by `_create_background_update()`.
        """
        lifecycle_return: LifecycleReturn[T] = await self._f()
        self._timestamp = monotonic()
        self._state = lifecycle_return.state

        if self._state == LifecycleState.ERROR:
            self._error_log(self._error_message.format(message=lifecycle_return.message))
            return

        value = lifecycle_return.value
        if value is _NONE:
            raise ValueError(f'{_NONE!r} is not a valid function return value')
        if self._state == LifecycleState.INTERIM:
            self._info_log(self._interim_message.format(value=value))
        self._cache = value
        self._cache_timestamp = self._timestamp
