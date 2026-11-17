import re
from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType

from solala.register import Register, RegisterValue, ConstantRegister


class RegisterBank(Mapping[str, Register]):
    """
    An immutable mapping of names to asynchronously accessed registers.

    Register values may change or become unavailable. Individual read
    failures are returned by `get_register_values` for clients to interpret.
    """

    def __init__(
            self,
            registers: Iterable[tuple[str, Register | RegisterValue]] | Mapping[str, Register | RegisterValue],
    ) -> None:
        """
        Initialise the bank.

        Args:
            registers: Named registers or constant values, which are wrapped
                in ConstantRegister instances.
        """
        if isinstance(registers, Mapping):
            registers = registers.items()
        self._registers: Mapping[str, Register] = MappingProxyType({
            name: value if isinstance(value, Register) else ConstantRegister(value)
            for name, value in registers
        })

    def __getitem__(self, key: str) -> Register:
        """
        Return the named register.
        """
        return self._registers[key]

    def __iter__(self) -> Iterator[str]:
        """
        Iterate over register names.
        """
        return iter(self._registers)

    def __len__(self) -> int:
        """
        Return the number of registers.
        """
        return len(self._registers)

    async def get_register_values(
            self,
            pattern: re.Pattern[str] | None = None,
    ) -> dict[str, RegisterValue | Exception]:
        """
        Read matching registers sequentially, retaining individual failures.

        Args:
            pattern: Compiled pattern matched against register names, or None
                to read all registers.

        Returns:
            Register names mapped to values or read exceptions. The caller
            determines how to handle unsuccessful reads.
        """
        results: dict[str, RegisterValue | Exception] = {}
        for name, register in self.items():
            if pattern is not None and not pattern.match(name):
                continue
            try:
                results[name] = await register.get()
            except Exception as error:
                results[name] = error
        return results


EMPTY_REGISTER_BANK: RegisterBank = RegisterBank({})
