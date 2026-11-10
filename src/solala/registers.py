import asyncio
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import TypeAlias, Type, Mapping, Iterator, Iterable, Tuple, KeysView, Optional, Hashable, \
    MutableMapping, Callable, final, Any, Awaitable

RegisterValue: TypeAlias = str | int | float | bool
RegisterType: TypeAlias = Type[str] | Type[int] | Type[float] | Type[bool]


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

    def get(self) -> RegisterValue:
        """
        Get the register value.
        """
        return self._get()

    def set(self, value: RegisterValue) -> None:
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
        self._set(value)

    @abstractmethod
    def _get(self) -> RegisterValue:
        ...

    @abstractmethod
    def _set(self, value: RegisterValue) -> None:
        ...


class ReadOnlyRegister(Register):
    def __init__(self, register_type: RegisterType):
        super().__init__(register_type, writable=False)

    @abstractmethod
    def _get(self) -> RegisterValue:
        ...

    @final
    def _set(self, value: RegisterValue) -> None:
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

    def _get(self) -> RegisterValue:
        return self._value


class CallRegister(ReadOnlyRegister):
    """
    A register that calls a function to get its value.
    """

    def __init__(self, f: Callable[[], RegisterValue], register_type: Optional[RegisterType] = None) -> None:
        if register_type is None:
            check_value = f()
            register_type = type(check_value)
        super().__init__(register_type)
        self._f: Callable[[], RegisterValue] = f

    def _get(self) -> RegisterValue:
        return self._f()


class AsyncCallRegister(ReadOnlyRegister):
    """
    A register that calls a function to get its value.
    """

    def __init__(self, f: Callable[[], Awaitable[RegisterValue]], register_type: RegisterType) -> None:
        super().__init__(register_type)
        self._f: Callable[[], Awaitable[RegisterValue]] = f

    def _get(self) -> RegisterValue:
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, self._f()).result()


class AsyncRegister(ReadOnlyRegister):
    """
    A register that calls an async method in a separate thread to get its value.
    """

    def __init__(self, register_type: RegisterType) -> None:
        super().__init__(register_type)

    def _get(self) -> RegisterValue:
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, self._async_get()).result()

    @abstractmethod
    async def _async_get(self) -> RegisterValue:
        ...


class DictRegister(Register):
    """
    A register that gets its value from a mapping.
    """

    def __init__(
            self,
            mapping: Mapping[Hashable, RegisterValue],
            key: Hashable,
            writable: bool = False,
    ):
        if writable and not isinstance(mapping, MutableMapping):
            raise TypeError('Mapping must be mutable for a writable register')

        check_value = mapping[key]
        super().__init__(type(check_value), writable=writable)
        self._mapping = mapping
        self._key = key

    def _get(self) -> RegisterValue:
        return self._mapping[self._key]

    def _set(self, value: RegisterValue) -> None:
        assert self.writable
        self._mapping[self._key] = value  # type: ignore


class RegisterBank(Mapping[str, RegisterValue]):
    """
    A collection of named registers.

    Note that it is not possible to change the registers
    of a register bank (i.e. the keys), but the register
    values may change.
    """

    def __init__(
            self,
            registers: Iterable[Tuple[str, Register | RegisterValue]] | Mapping[str, Register | RegisterValue]
    ):
        if isinstance(registers, Mapping):
            registers = registers.items()

        registers: Iterable[Tuple[str, Register | RegisterValue]]
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

    def get(self, key: str, default: Optional[RegisterValue] = None) -> Optional[RegisterValue]:
        got: Optional[Register] = self._registers.get(key, None)
        if got is None:
            return None
        else:
            return got.get()

    def __getitem__(self, key: str, /) -> RegisterValue:
        return self._registers[key].get()

    def __setitem__(self, key: str, value: RegisterValue) -> None:
        self._registers[key].set(value)

    def __iter__(self) -> Iterator[str]:
        return iter(self._registers)
