import asyncio
import random
from abc import abstractmethod
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import BaseModel, Field, model_validator
from pydantic import PlainSerializer, PlainValidator

_ALLOWED_EXCEPTIONS: dict[str, type[Exception]] = {
    'RuntimeError': RuntimeError,
    'TimeoutError': TimeoutError,
    'ConnectionError': ConnectionError,
    'OSError': OSError,
    'ValueError': ValueError,
}


def _validate_exception(value: Any) -> Exception:
    """
    Validate an allowed exception instance or its JSON representation.

    Args:
        value: Exception instance or a mapping with type and message.

    Returns:
        An exception from the supported set.

    Raises:
        ValueError: If the type or constructor arguments are unsupported.
    """
    if isinstance(value, Exception):
        exception = value
    elif isinstance(value, dict):
        if set(value) != {'type', 'message'}:
            raise ValueError('Exception representation requires type and message')
        name, message = value['type'], value['message']
        if not isinstance(name, str) or name not in _ALLOWED_EXCEPTIONS:
            raise ValueError('Unsupported exception type')
        if message is not None and not isinstance(message, str):
            raise ValueError('Exception message must be a string or null')
        exception = _ALLOWED_EXCEPTIONS[name]() if message is None else _ALLOWED_EXCEPTIONS[name](message)
    else:
        raise ValueError('Expected an exception or its serialized representation')

    if type(exception) not in _ALLOWED_EXCEPTIONS.values():
        raise ValueError('Unsupported exception type')
    if len(exception.args) > 1 or any(not isinstance(arg, str) for arg in exception.args):
        raise ValueError('Exception must have zero or one string argument')
    return exception


def _serialize_exception(exception: Exception) -> dict[str, str | None]:
    """
    Serialize a supported exception without dynamic imports.

    Args:
        exception: Validated exception instance.

    Returns:
        Exception class name and optional message.
    """
    return {
        'type': type(exception).__name__,
        'message': exception.args[0] if exception.args else None,
    }


SerializableException = Annotated[
    Exception,
    PlainValidator(_validate_exception),
    PlainSerializer(_serialize_exception, return_type=dict[str, str | None], when_used='json'),
]


class FailureLocation(StrEnum):
    """
    Base class for delegate failure locations.

    Subclasses define the supported operations and whether each is asynchronous.
    """

    @abstractmethod
    def is_async(self) -> bool:
        """
        Return whether this operation is asynchronous.
        """
        raise NotImplementedError()


class DummyFailure(BaseModel):
    """
    Describe a simulated delay or exception at a delegate operation.

    Attributes:
        location: Delegate-specific operation at which injection is possible.
        probability: Probability of injection.
        exception: Optional exception to raise after the delay.
        sleep: Delay in seconds before returning or raising.
    """

    location: FailureLocation
    probability: float = Field(default=1.0, gt=0.0, le=1.0)
    exception: SerializableException | None = None
    sleep: float = Field(default=0.0, ge=0.0)

    @model_validator(mode='after')
    def validate_failure(self) -> Self:
        if self.sleep == 0.0 and self.exception is None:
            raise ValueError('A failure must have at least an exception or a sleep')
        if self.sleep > 0 and not self.location.is_async():
            raise ValueError('Cannot inject a delay into a synchronous operation')
        return self


async def async_maybe_inject_failure(location: FailureLocation, failure: DummyFailure | None) -> None:
    """
    Inject the configured delay and exception for a matching failure description.

    Args:
        location: Operation being called; injection is possible if
            `location.name == failure.location`.
        failure: Optional description of the failure to inject.
    """
    if (
            failure is not None
            and failure.location == location.name
            and (failure.probability == 1 or random.random() < failure.probability)
    ):
        # inject the failure
        if failure.sleep > 0:
            await asyncio.sleep(failure.sleep)
        if failure.exception is not None:
            raise failure.exception


def maybe_inject_failure(location: FailureLocation, failure: DummyFailure | None) -> None:
    """
    Inject the configured delay and exception for a matching failure description.

    Args:
        location: Operation being called; injection is possible if
            `location.name == failure.location`.
        failure: Optional description of the failure to inject.

    Raises:
        ValueError: If the matching failure requests a delay in a synchronous operation.
    """
    if failure is None or failure.location != location.name:
        return
    if failure.sleep != 0:
        raise ValueError('cannot inject a failure sleep for a synchronous function')
    if failure.probability == 1 or random.random() < failure.probability:
        if failure.exception is not None:
            raise failure.exception
