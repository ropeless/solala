import asyncio
from asyncio import Task
from dataclasses import dataclass
from datetime import datetime, UTC
from enum import Enum, auto
from time import monotonic
from traceback import format_exception
from typing import Callable, Coroutine, Any, ClassVar, Literal

from solala.utils.sentinel import Sentinel

NO_VALUE = Sentinel('NO_VALUE')


class LifecycleState(Enum):
    INITIAL = auto()
    VALID = auto()
    INTERIM = auto()
    ERROR = auto()


type ReturnState = Literal[LifecycleState.VALID, LifecycleState.INTERIM]


@dataclass
class ObjectReturn[T]:
    value: T
    state: ReturnState
    until_time: datetime | None


@dataclass
class ErrorReturn:
    message: str
    state: ClassVar[LifecycleState] = LifecycleState.ERROR


def valid[T](value: T, until_time: datetime | None = None) -> ObjectReturn[T]:
    """
    Support a wrapped function to return a VALID object.
    """
    return ObjectReturn(value, LifecycleState.VALID, until_time)


def interim[T](value: T, until_time: datetime | None = None) -> ObjectReturn[T]:
    """
    Support a wrapped function to return an INTERIM object.
    """
    return ObjectReturn(value, LifecycleState.INTERIM, until_time)


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
            'no usable result from the wrapped function, no cached result, and no default result available'
        )


class LifecycleCache[T]:
    """
    Cache results of an asynchronous function using lifecycle states and age thresholds.

    The wrapped function takes no arguments and returns a `LifecycleReturn[T]`.
    VALID provides a usable result. INTERIM provides a usable but provisional
    result that should be retried sooner. Both replace any previously cached
    value, even when an INTERIM result follows a VALID result.

    An ErrorReturn means the wrapped function could not obtain a value,
    for example because of a network, resource, or configuration problem. It is a refresh
    outcome, not an exception raised by `LifecycleCache.__call__()`. An error
    result does not replace the last usable cached value. The cache retains
    that value for fallback only while it remains younger than old. Once
    the cached value reaches old, it expires and is replaced by the
    configured default (or NO_VALUE if no default was configured).

    If neither an unexpired cached value nor a configured default is
    available, `__call__()` raises NoResult. This means the cache cannot
    provide a result, even though the wrapped function returned ErrorReturn.
    Such a failure does not prevent future refresh attempts.

    If a default is configured, normal lifecycle operation never raises
    NoResult: a usable cached value or the default is always available,
    including after an ERROR result or cache expiration. This guarantee
    does not cover unexpected exceptions raised by the wrapped function,
    logging callbacks, or other programming errors.

    The INITIAL lifecycle state means that no wrapped-function result has
    yet been received. Successful results have VALID or INTERIM state;
    ErrorReturn has ERROR state. After a result is received, the cache state
    reflects that result, even if `__call__()` subsequently raises NoResult.
    It does not return to INITIAL. None may be a legitimate value of `T` or default;
    only NO_VALUE denotes absence. Sentinel instances are valid values except
    for the reserved NO_VALUE sentinel.

    Both VALID and INTERIM cached values expire at age 'old'. Expiration
    replaces the cached value with the configured default; it does not
    change the lifecycle state or its timestamp. A default value never
    expires. An expired value must not be returned even if a refresh
    subsequently returns ErrorReturn.

    The wrapped function can override the definition of old age, by
    explicitly returning 'until_time' in its result.

    An external caller can invalidate a cached (make it old) at any time.

    The cache tracks the latest result state and its monotonic timestamp.
    The age of the cache is the elapsed time since that result was received.
    This timestamp advances for VALID, INTERIM, and ErrorReturn alike. The
    timestamp of the last usable value is tracked separately so error refreshes
    cannot extend its lifetime.

    Three age thresholds control refreshes: retry, young, and old.
    They must satisfy 0 < 'retry' <= 'young' <= 'old'. If omitted, 'young'
    defaults to 'old' and 'retry' defaults to 'young'.

    The intended behaviour of `__call__()` is:

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
    it or starting another refresh. If the cached value has reached 'old',
    it must expire before awaiting the task.

    The wrapped function is responsible for catching exceptions it
    considers non-fatal and returning ErrorReturn instead.
    Other exceptions raised by the wrapped function propagate to
    foreground callers. Unexpected refresh exceptions are also logged
    with their traceback, regardless of whether a foreground caller awaits
    them or not.

    An unexpected exception from the wrapped function or result validation
    does not change the lifecycle state, timestamps, or cached value. Any cache expiration performed before
    the refresh remains effective, so an expired value is not restored.
    The cache remains internally consistent, and subsequent calls can
    attempt another refresh.

    `asyncio.CancelledError` represents cancellation, not a lifecycle
    ERROR, and is not converted into one. Cancelling an individual
    foreground caller must not cancel a refresh shared with other callers.
    """

    def __init__(
            self,
            f: WrappedFunction[T],
            *,
            log_error: Callable[[str], None],
            log_info: Callable[[str], None],
            old: float,
            young: float | None = None,
            retry: float | None = None,
            default: T | Sentinel = NO_VALUE,
            valid_message: str = '',
            interim_message: str = 'interim value received: {value!r}',
            error_message: str = '{message}',
    ) -> None:
        """
        Initialise the lifecycle cache and its refresh policy.

        Args:
            f: Asynchronous function providing ObjectReturn or ErrorReturn.
            log_error: Callback for refresh errors and unexpected failures.
            log_info: Callback for provisional results.
            old: Maximum age of a cached result in seconds.
            young: Age at which a valid result triggers background refresh.
                Defaults to old.
            retry: Minimum interval between interim or error refresh attempts.
                Defaults to young.
            default: Fallback value when no unexpired cached value is available.
                None is valid; NO_VALUE means no default.
            valid_message: Format string for logging valid values, including {value}.
            interim_message: Format string for logging provisional values, including {value}.
            error_message: Format string for logging expected refresh errors, including {message}.

        Raises:
            ValueError: If age thresholds are invalid.
        """
        # Default values
        if young is None:
            young: float = old
        if retry is None:
            retry: float = young

        # Consistency checks
        if not 0 < retry <= young <= old:
            raise ValueError(f'ensure: `0 < retry <= young <= old`')

        self._f: WrappedFunction[T] = f
        self._retry: float = retry
        self._young: float = young
        self._old: float = old
        self._default: T | Sentinel = default
        self._cache: T | Sentinel = default
        self._state: LifecycleState = LifecycleState.INITIAL
        self._timestamp: float = monotonic()
        self._invalid_timestamp: float = self._timestamp
        self._error_log: Callable[[str], None] = log_error
        self._info_log: Callable[[str], None] = log_info
        self._valid_message: str = valid_message
        self._interim_message: str = interim_message
        self._error_message: str = error_message
        self._task: Task[None] | None = None

    @property
    def state(self) -> LifecycleState:
        return self._state

    @property
    def timestamp(self) -> float:
        """
        Return the monotonic time of the latest lifecycle result.

        This includes error results and may differ from the time the
        current cached value was obtained.
        """
        return self._timestamp

    @property
    def default(self) -> T | Sentinel:
        """
        Get the default cache value.

        Returns:
            The default value, if provided, or the Sentinel `NO_VALUE`.
        """
        return self._default

    async def invalidate(self) -> None:
        """
        Invalidate the cache.
        Cancel any active refresh and reset the cache to its initial state.
        """
        task = self._task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._cache = self._default
        self._state = LifecycleState.INITIAL
        self._timestamp = monotonic()
        self._invalid_timestamp = self._timestamp

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
        old_cache: bool = now >= self._invalid_timestamp
        if old_cache:
            self._cache = self._default

        if self._state is LifecycleState.INITIAL:
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
            # ERROR | INTERIM with usable cache
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
        if self._cache is NO_VALUE:
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
        NO_VALUE is reserved and cannot be returned as a successful value.
        Called only by `_get_or_create_refresh_task()`.
        """
        lifecycle_return: LifecycleReturn[T] = await self._f()

        if isinstance(lifecycle_return, ObjectReturn):
            value: T = lifecycle_return.value
            if value is NO_VALUE:
                raise ValueError(f'{value!r} is not a valid function return value')

        timestamp = monotonic()
        if isinstance(lifecycle_return, ErrorReturn):
            if self._error_message != '':
                self._error_log(self._error_message.format(message=lifecycle_return.message))
            self._timestamp = timestamp
            self._state = LifecycleState.ERROR
            return

        lifecycle_return: ObjectReturn
        value: T = lifecycle_return.value

        if lifecycle_return.state is LifecycleState.INTERIM:
            if self._interim_message != '':
                self._info_log(self._interim_message.format(value=value))
                if lifecycle_return.until_time is None:
                    self._invalid_timestamp = timestamp + self._retry
                else:
                    self._invalid_timestamp = _datetime_to_monotonic(lifecycle_return.until_time)
        elif lifecycle_return.state is LifecycleState.VALID:
            if self._valid_message != '':
                self._info_log(self._valid_message.format(value=value))
                if lifecycle_return.until_time is None:
                    self._invalid_timestamp = timestamp + self._old
                else:
                    self._invalid_timestamp = _datetime_to_monotonic(lifecycle_return.until_time)

        self._cache = value
        self._timestamp = timestamp
        self._state = lifecycle_return.state


def _datetime_to_monotonic(target_dt: datetime) -> float:
    """
    Make best efforts to convert the given timezone-aware datetime to a monotonic time stamp.
    """
    now_dt = datetime.now(UTC)
    now_mono = monotonic()
    delta_seconds = (target_dt - now_dt).total_seconds()
    return now_mono + delta_seconds
