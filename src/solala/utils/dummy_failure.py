import asyncio
import random
from enum import Enum

from pydantic import BaseModel, Field

from typing import Annotated, Any

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


class DummyFailureDescription(BaseModel):
    """
    Describe a simulated delay or exception at a delegate operation.

    Attributes:
        location: Delegate-specific operation at which injection is possible.
        exception: Optional exception to raise after the delay.
        sleep: Delay in seconds before returning or raising.
    """

    location: str
    exception: SerializableException | None = None
    sleep: float = Field(default=0.0, ge=0.0)


class DummyFailureInjector:
    """
    Apply probabilistic faults to designated dummy delegate operations.
    """

    def __init__(self, probability: float, description: DummyFailureDescription | None) -> None:
        self._probability = probability
        self._description = description

    async def maybe_inject_failure(self, location: Enum) -> None:
        """
        Inject the configured delay and exception for a matching operation.

        Args:
            location: Operation-specific location enum member.
        """
        description = self._description
        if (
            description is None
            or description.location != location.name
            or random.random() >= self._probability
        ):
            return
        if description.sleep:
            await asyncio.sleep(description.sleep)
        if description.exception is not None:
            raise description.exception
