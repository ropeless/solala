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
