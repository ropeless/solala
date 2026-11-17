from typing import Iterable, Mapping, KeysView, AsyncIterator

from solala.register import Register, RegisterValue, ConstantRegister
from solala.utils.sentinel import Sentinel

_NONE = Sentinel('NO_VALUE')


class RegisterBank:
    """
    A collection of named registers.

    Register names are fixed after initialisation, but individual register
    values may change. The `registers` property exposes the underlying mapping.
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
        Asynchronously iterate over register names and their current values.

        Each register is read when its entry is yielded.

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


# An immutable, empty register bank
EMPTY_REGISTER_BANK: RegisterBank = RegisterBank({})
