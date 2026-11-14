from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, KeysView, Mapping
from typing import final

from solala.utils.sentinel import Sentinel

type RegisterValue = str | int | float | bool
type RegisterType = type[str] | type[int] | type[float] | type[bool]

_NONE = Sentinel('_NONE')


class ReadOnlyError(AttributeError):
    """
    Raised when requesting to write to a read-only register.
    """

    def __init__(self) -> None:
        super().__init__('Register not writable')


def check_type(t: object) -> RegisterType:
    """
    Check that the given type is a valid register type.

    Args:
        t: The type to check.

    Returns:
        The register type.

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
    Check that the given value is a valid register value.

    Args:
        v: The value to check.

    Returns:
        The value.

    Raises:
        TypeError: If the type of value is not a valid register type.
    """
    if isinstance(v, (str, int, float, bool)):
        return v
    else:
        raise TypeError(f'not a valid register type: {type(v)}')


def value_okay(value: RegisterValue, register_type: RegisterType) -> bool:
    """
    Check whether the value is acceptable for the given register type.

    Note that this explicitly allows:
    * `bool` values can be used for `int` and `float` register types
    * `int` values can be used for `float` register types.

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
                from the give value.
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
    A read-only register whose value is obtained by calling a synchronous function.

    If the register type is not specified, the function is called once during
    initialisation to determine the type of its return value.
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
    A read-only register whose value is obtained by awaiting an asynchronous function.
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


class RegisterBank:
    """
    A collection of named registers.

    The set of registers cannot be changed after initialisation, but the
    values held by those registers may change.
    """

    def __init__(
            self,
            registers: Iterable[tuple[str, Register | RegisterValue]] | Mapping[str, Register | RegisterValue]
    ) -> None:
        """
        Initialise the register bank.

        Args:
            registers: The registers to include in the bank. Each entry
                associates a name with either a Register or a constant value.
                Constant values are wrapped in ConstantRegister instances.
        """
        if isinstance(registers, Mapping):
            registers: Iterable[tuple[str, Register | RegisterValue]] = registers.items()

        registers: Iterable[tuple[str, Register | RegisterValue]]
        self._registers: Mapping[str, Register] = {
            key: value if isinstance(value, Register) else ConstantRegister(value)
            for key, value in registers
        }

    @property
    def registers(self) -> Mapping[str, Register]:
        """
        Return the registers in the bank.

        Returns:
            A mapping of register names to Register instances.
        """
        return self._registers

    def __len__(self) -> int:
        """
        Return the number of registers in the bank.
        """
        return len(self._registers)

    def keys(self) -> KeysView[str]:
        """
        Return a view of the register names.
        """
        return self._registers.keys()

    async def items(self) -> AsyncIterator[tuple[str, RegisterValue]]:
        """
        Iterate over the register names and their current values.

        Yields:
            A tuple containing a register name and its current value.
        """
        for key in self._registers.keys():
            yield key, await self._registers[key].get()

    async def get(self, key: str, default: RegisterValue | None = None) -> RegisterValue | None:
        """
        Get the current value of a register.

        Args:
            key: The name of the register.
            default: The value to return if the register does not exist.

        Returns:
            The register value, or the default if the register does not exist.
        """
        got: Register | Sentinel = self._registers.get(key, _NONE)
        if got is _NONE:
            return default
        else:
            assert isinstance(got, Register)
            return await got.get()

    async def set(self, key: str, value: RegisterValue) -> None:
        """
        Set the value of a register.

        Args:
            key: The name of the register.
            value: The value to write.

        Raises:
            KeyError: If the register does not exist.
            ReadOnlyError: If the register is read-only.
            TypeError: If the value is not of the expected type.
        """
        got: Register | Sentinel = self._registers.get(key, _NONE)
        if got is _NONE:
            raise KeyError(key)
        else:
            assert isinstance(got, Register)
            await got.set(value)
