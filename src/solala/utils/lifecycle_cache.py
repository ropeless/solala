import asyncio
from asyncio import Task
from dataclasses import dataclass
from enum import Enum, auto
from time import monotonic
from typing import Callable, Coroutine, Any

from solala.utils.sentinel import Sentinel

_NONE = Sentinel('_NONE')
_INVALID = Sentinel('_INVALID')


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
    Support a wrapped function to return a VALID object.
    """
    return LifecycleReturn(value, state=LifecycleState.INTERIM)


def error[T](message: str) -> LifecycleReturn[T]:
    """
    Support a wrapped function to return an error condition.
    """
    return LifecycleReturn(None, state=LifecycleState.ERROR, message=message)


type WrappedFunction[T] = Callable[[], Coroutine[Any, Any, LifecycleReturn[T]]]


class NoDefaultResult(RuntimeError):
    def __init__(self) -> None:
        super().__init__('no usable result from the wrapped function and no default result available')


class LifecycleCache[T]:
    """
    Cache results of an asynchronous function using lifecycle states and age thresholds.

    The wrapped function takes no arguments and returns a LifecycleReturn[T]:
    VALID indicates a usable result; INTERIM indicates a usable but provisional
    result; ERROR indicates that a result could not be obtained (for example,
    because of a network, resource, or configuration problem). An ERROR result
    is not an exception raised by LifecycleCache.__call__(). It signals that
    refreshing should be retried later while an available cached or default
    value is used in the meantime.

    A separate failure occurs when LifecycleCache.__call__() cannot supply a
    value: the wrapped function has not provided a usable result and neither
    a cached value nor a configured default is available. In that case,
    __call__() raises NoDefaultResult.

    The cache initially has an INVALID internal state, meaning no refresh
    has completed. Successful VALID and INTERIM results supply values that
    are cached and returned. A refresh reporting ERROR does not supply a
    replacement value. The most recently cached usable value is preferred
    over the configured default when a fallback is required.

    The cache tracks a state and a monotonic timestamp. Its age is the
    elapsed time since that timestamp. The timestamp is updated when a
    wrapped-function result is received, including ERROR, so retry timing
    is measured from the most recent refresh result rather than necessarily
    from the creation of the stored value.

    Three age thresholds control refreshes: retry, young, and old.
    They must satisfy retry <= young <= old. If omitted, young defaults
    to old and retry defaults to young.

    The intended behaviour of __call__() is:

    INVALID, any age:
        Await the wrapped function.

    ERROR, age < retry:
        Return the cached value or default; if neither exists, raise
        NoDefaultResult.

    ERROR, retry <= age:
        Await the wrapped function; use a fallback if it reports ERROR.

    INTERIM, age < retry:
        Return the cached interim value.

    INTERIM, retry <= age:
        Await the wrapped function.

    VALID, age < young:
        Return the cached value.

    VALID, young <= age < old:
        Start a background refresh and return the cached value.

    VALID, old <= age:
        Await the wrapped function.

    A background refresh is intended to run at most once at a time.
    If a synchronous refresh is required while a background refresh is
    running, the documented policy is to cancel the background task.
    Coordination of overlapping refreshes remains part of the implementation.

    The ERROR result described here is an expected inability to obtain a
    value, not a request to hide arbitrary programming exceptions. Behaviour
    for unexpected exceptions and task cancellation is not specified here.
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
        self._cache: T | Sentinel = _NONE
        self._state: LifecycleState | Sentinel = _INVALID
        self._timestamp: float = float('-inf')
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
        if self._state is _INVALID:
            return await self._call_f()
        elif self._state is LifecycleState.VALID:
            assert self._cache is not _NONE
            age: float = monotonic() - self._timestamp
            if age < self._young:
                return self._cache
            elif age < self._old:
                self._create_background_update()
                return self._cache
            else:
                return await self._call_f()
        else:
            # LifecycleState.ERROR | LifecycleState.INTERIM:
            if monotonic() < self._timestamp + self._retry:
                return self._cached_or_error()
            else:
                return await self._call_f()

    def _cached_or_error(self) -> T:
        """
        Return the cached value or raise an exception if there is no cached value.
        """
        if self._cache is _NONE:
            raise NoDefaultResult()
        else:
            return self._cache

    def _create_background_update(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._update())

    async def _call_f(self) -> T:
        """
        Call the wrapped function asynchronously, updating the
        cache according to the returned result.
        """
        lifecycle_return: LifecycleReturn[T] = await self._f()
        now = monotonic()
        state = lifecycle_return.state

        if state == LifecycleState.ERROR:
            self._error_log(self._error_message.format(message=lifecycle_return.message))
            return self._cached_or_error()

        value = lifecycle_return.value
        if value is _NONE:
            raise ValueError(f'{_NONE!r} is not a valid function return value')
        if state == LifecycleState.INTERIM:
            self._info_log(self._interim_message.format(value=value))
        self._timestamp = now
        self._state = state
        self._cache = value
        return value

    async def _update(self) -> None:
        """
        Called as a background tasks to update the cached value.
        """
        lifecycle_return: LifecycleReturn[T] = await self._f()
        now = monotonic()
        state = lifecycle_return.state

        if state == LifecycleState.ERROR:
            self._error_log(self._error_message.format(message=lifecycle_return.message))
            return

        value = lifecycle_return.value
        if value is _NONE:
            raise ValueError(f'{_NONE!r} is not a valid function return value')
        if state == LifecycleState.INTERIM:
            self._info_log(self._interim_message.format(value=value))
        self._timestamp = now
        self._state = state
        self._cache = value
