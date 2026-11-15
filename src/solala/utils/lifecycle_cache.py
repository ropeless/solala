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
    A LifecycleCache caches the result of a function, where the cache
    has an associated 'state' and 'timestamp'. The 'age' of the cache
    is `now() - timestamp`.

    Depending on the state and age of the cache, the wrapped function will
    be called to refresh the cache. The wrapped function returns a `LifecycleReturn[T]`
    object which encode the state of the freshly computed object. In reality
    the wrapped function should create its LifecycleReturn object by calling
    either: `valid(...)`, `interim(...)`, or `error(...)`. A timestamp is
    associated with a cached object for calculating its age.

    A LifecycleCache keeps track of three age thresholds, the 'young' age, the
    'old' age, and the 'retry' age. A LifecycleCache optionally keeps a 'default'
    object to be used as a stand-in for error conditions.

    The following must be true of the ages: retry <= young <= old.

    Calling a LifecycleCache cache, `__call__()`, will do the following according
    to the state and age of the cache. The initial state is INVALID.

    Whenever `__call__()` gets a LifecycleReturn from the wrapped function, it will
    Set the current state as per the returned LifecycleReturn and update the timestamp.

    If the new state is VALID or INTERIM then the supplied object will be cached, and the
    object is returned to the caller.

    If the new state is INVALID or ERROR then either: a default object is available
     which is then cached and returned, or no default object is available and an error
    is raised.

    The following describes when and how the wrapped function is called and the
    cached object is used.


    INVALID, any age:
    Call and await on the wrapped function.

    ERROR, age < retry:
    If have cached object then return the cached object,
    otherwise raise an exception.

    ERROR, retry <= age:
    Call and await on the wrapped function.

    INTERIM, age < retry:
    If have cached object then return the cached object,
    otherwise raise an exception.

    INTERIM, retry <= age:
    Call and await on the wrapped function.

    VALID, age < young:
    In this case there should be a cached object
    Return the cached object

    VALID, young <= age < old:
    In this case there should be a cached object
    Create a background task to call the wrapped function asynchronously.
    Return the cached object.

    VALID, old <= age:
    Call and await on the wrapped function.

    If the wrapped function is called asynchronously while a background task is working
    then the background task is cancelled. Only one background task can be running at a time.
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
