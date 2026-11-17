from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import final

type RegisterValue = str | int | float | bool
type RegisterType = type[str] | type[int] | type[float] | type[bool]


class ReadOnlyError(AttributeError):
    """
    Raised when attempting to write to a read-only register.
    """

    def __init__(self) -> None:
        super().__init__('Register not writable')


def check_type(t: object) -> RegisterType:
    """
    Validate that a type is an allowed RegisterType.

    Args:
        t: The type to check.

    Returns:
        The register type, cast to RegisterType.

    Raises:
        TypeError: If the type is not a valid register type.
    """
    if t is str:
        return str
    if t is int:
        return int
    if t is float:
        return float
    if t is bool:
        return bool
    raise TypeError(f'not a valid register type: {t!r}')


def check_value(v: object) -> RegisterValue:
    """
    Validate that a value is an allowed RegisterValue.

    Args:
        v: The value to check.

    Returns:
        The value, cast to RegisterValue.

    Raises:
        TypeError: If the value has an unsupported type.
    """
    if isinstance(v, (str, int, float, bool)):
        return v
    else:
        raise TypeError(f'not a valid register type: {type(v)}')


def value_okay(value: RegisterValue, register_type: RegisterType) -> bool:
    """
    Check whether the value is acceptable for the given register type.

    Because `bool` is a subclass of `int`, boolean values are accepted by
    integer and floating-point registers. Integer values are also accepted by
    floating-point registers.

    Args:
        value: The value to check.
        register_type: The register type to check against.

    Returns:
        True if the value is acceptable for the given register type, False otherwise.
    """
    if isinstance(value, register_type):
        return True
    if type(value) is int and register_type is float:
        return True
    return False


class Register(ABC):
    """
    Base class for typed registers that support asynchronous access.

    A register has a fixed value type and may be either writable or read-only.
    Its value may change between reads, and reading may require I/O and fail.
    The caller determines how to handle read exceptions.
    """

    def __init__(self, register_type: RegisterType, writable: bool) -> None:
        """
        Initialise the register.

        Args:
            register_type: The type of values held by the register.
            writable: Whether the register can be written to.
        """
        if register_type not in (str, int, float, bool):
            raise TypeError(f'Unexpected register type: {register_type!r}')
        self._register_type = register_type
        self._writable = writable

    @property
    def reg_type(self) -> RegisterType:
        """
        Return the type of values held by the register.
        """
        return self._register_type

    @property
    def writable(self) -> bool:
        """
        Return whether the register can be written to.
        """
        return self._writable

    async def get(self) -> RegisterValue:
        """
        Get the current register value.

        Returns:
            The current register value.
        """
        return await self._get()

    async def set(self, value: RegisterValue) -> None:
        """
        Set the register value.

        Args:
            value: The new value for the register.

        Raises:
            ReadOnlyError: If the register is read-only.
            TypeError: If the value is not of the expected type.
        """
        if not self._writable:
            raise ReadOnlyError()
        if not value_okay(value, self._register_type):
            raise TypeError(f'Expected {self._register_type}, got {type(value)}')
        await self._set(value)

    @abstractmethod
    async def _get(self) -> RegisterValue:
        """
        Return the register value.
        """
        ...

    @abstractmethod
    async def _set(self, value: RegisterValue) -> None:
        """
        Write a value to the register.

        Args:
            value: The value to write.
        """
        ...


class ReadOnlyRegister(Register):
    """
    Base class for registers that cannot be written to.
    """

    def __init__(self, register_type: RegisterType) -> None:
        """
        Initialise the read-only register.

        Args:
            register_type: The type of values held by the register.
        """
        super().__init__(register_type, writable=False)

    @abstractmethod
    async def _get(self) -> RegisterValue:
        """
        Return the register value.
        """
        ...

    @final
    async def _set(self, value: RegisterValue) -> None:
        assert False


class ConstantRegister(ReadOnlyRegister):
    """
    A register with a constant value.

    The value is set when the register is created and cannot be changed.
    """

    def __init__(self, value: RegisterValue, register_type: RegisterType | None = None) -> None:
        """
        Initialise the register with its constant value.

        Args:
            value: The value returned whenever the register is read.
            register_type: The register value type. If omitted, it is inferred
                from the given value.
        """
        if register_type is None:
            register_type: RegisterType = check_type(type(value))
        elif not value_okay(value, register_type):
            raise TypeError(f'Expected {register_type}, got {type(value)}')

        super().__init__(register_type)
        self._value = value

    async def _get(self) -> RegisterValue:
        return self._value


class CallRegister(ReadOnlyRegister):
    """
    A read-only register backed by a synchronous function.

    The function is called on each read. If no register type is supplied,
    the function is also called during initialisation to infer its return type.
    """

    def __init__(self, f: Callable[[], RegisterValue], register_type: RegisterType | None = None) -> None:
        """
        Initialise the register.

        Args:
            f: The function called whenever the register is read.
            register_type: The register value type. If omitted, it is inferred
                from the function's return value.
        """
        if register_type is None:
            register_type: RegisterType = check_type(type(f()))

        register_type: RegisterType
        super().__init__(register_type)
        self._f: Callable[[], RegisterValue] = f

    async def _get(self) -> RegisterValue:
        return self._f()


class AsyncCallRegister(ReadOnlyRegister):
    """
    A read-only register backed by an asynchronous function.

    The function is awaited on each read.
    """

    def __init__(self, f: Callable[[], Awaitable[RegisterValue]], register_type: RegisterType) -> None:
        """
        Initialise the register.

        Args:
            f: The asynchronous function awaited whenever the register is read.
            register_type: The type of values returned by the function.
        """
        super().__init__(register_type)
        self._f: Callable[[], Awaitable[RegisterValue]] = f

    async def _get(self) -> RegisterValue:
        return await self._f()
