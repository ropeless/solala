from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, KeysView, Mapping
from typing import Any, final

type RegisterValue = str | int | float | bool
type RegisterType = type[str] | type[int] | type[float] | type[bool]


class ReadOnlyError(AttributeError):
    """
    Raised when requesting to write to a read-only register.
    """

    def __init__(self):
        super().__init__('Register not writable')


def check_type(t: Any) -> RegisterType:
    """
    Is the given type a valid register type.

    Args:
        t: The type to check.

    Returns:
        The register type.

    Raises:
        TypeError: If the type is not a valid register type.
    """
    if t in (str, int, float, bool):
        return t
    else:
        raise TypeError(f'not a valid register type: {t}')


def check_value(v: Any) -> RegisterValue:
    """
    Is the given value a valid register value.

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
    Is the given value acceptable for the given register type.

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

    def __init__(self, register_type: RegisterType, writable: bool):
        if register_type not in (str, int, float, bool):
            raise TypeError(f'Unexpected register type: {register_type}')
        self._register_type = register_type
        self._writable = writable

    @property
    def reg_type(self) -> RegisterType:
        return self._register_type

    @property
    def writable(self) -> bool:
        return self._writable

    async def get(self) -> RegisterValue:
        """
        Get the register value.
        """
        return await self._get()

    async def set(self, value: RegisterValue) -> None:
        """
        Set the register value.

        Args:
            value: the new value for the register.

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
        ...

    @abstractmethod
    async def _set(self, value: RegisterValue) -> None:
        ...


class ReadOnlyRegister(Register):
    def __init__(self, register_type: RegisterType):
        super().__init__(register_type, writable=False)

    @abstractmethod
    async def _get(self) -> RegisterValue:
        ...

    @final
    async def _set(self, value: RegisterValue) -> None:
        assert False


class ConstantRegister(ReadOnlyRegister):
    """
    A register with a constant value.
    """

    def __init__(self, value: RegisterValue):
        register_type: RegisterType = type(value)
        if not value_okay(value, register_type):
            raise TypeError(f'Expected {register_type}, got {type(value)}')

        super().__init__(register_type)
        self._value = value

    async def _get(self) -> RegisterValue:
        return self._value


class CallRegister(ReadOnlyRegister):
    """
    A register that calls a function to get its value.
    """

    def __init__(self, f: Callable[[], RegisterValue], register_type: RegisterType | None = None) -> None:
        if register_type is None:
            register_type = type(f())
        super().__init__(register_type)
        self._f: Callable[[], RegisterValue] = f

    async def _get(self) -> RegisterValue:
        return self._f()


class AsyncCallRegister(ReadOnlyRegister):
    """
    A register that calls a function to get its value.
    """

    def __init__(self, f: Callable[[], Awaitable[RegisterValue]], register_type: RegisterType) -> None:
        super().__init__(register_type)
        self._f: Callable[[], Awaitable[RegisterValue]] = f

    async def _get(self) -> RegisterValue:
        return await self._f()


class RegisterBank:
    """
    A collection of named registers.

    Note that it is not possible to change the registers
    of a register bank (i.e. the keys), but the register
    values may change.
    """

    def __init__(
            self,
            registers: Iterable[tuple[str, Register | RegisterValue]] | Mapping[str, Register | RegisterValue]
    ):
        if isinstance(registers, Mapping):
            registers = registers.items()

        registers: Iterable[tuple[str, Register | RegisterValue]]
        self._registers: Mapping[str, Register] = {
            key: value if isinstance(value, Register) else ConstantRegister(value)
            for key, value in registers
        }

    @property
    def registers(self) -> Mapping[str, Register]:
        return self._registers

    def __len__(self) -> int:
        return len(self._registers)

    def keys(self) -> KeysView[str]:
        return self._registers.keys()

    async def items(self) -> AsyncIterator[tuple[str, RegisterValue]]:
        for key in self._registers.keys():
            yield key, await self._registers[key].get()

    async def get(self, key: str, default: RegisterValue | None = None) -> RegisterValue | None:
        got: Register | None = self._registers.get(key, None)
        if got is None:
            return default
        else:
            return await got.get()

    async def set(self, key: str, value: RegisterValue) -> None:
        got: Register | None = self._registers.get(key, None)
        if got is None:
            raise KeyError(key)
        else:
            await got.set(value)
