from collections.abc import Awaitable, Callable, Iterator
from dataclasses import fields
from inspect import getmembers
from itertools import chain
from typing import get_type_hints

from solala.control.modes_and_policies import ControlMode
from solala.control.power_consumer_manager import PowerConsumerManager
from solala.delegates.power_consumer.consumer_status import ConsumerStatus
from solala.delegates.power_controller.power_controller import PowerController
from solala.delegates.power_controller.power_status import PowerStatus
from solala.delegates.power_pricer.price import Price
from solala.register import (
    CallRegister, ReadOnlyRegister, Register, RegisterType, RegisterValue, RegisterValueUnavailable, check_type,
)
from solala.register_bank import RegisterBank


class RegisterManager:
    """
    Compose the register bank from system registers and published delegate banks.
    """

    def __init__(
            self,
            control_mode: ControlMode,
            get_power_status: Callable[[], Awaitable[PowerStatus]],
            get_price_now: Callable[[], Awaitable[Price]],
    ) -> None:
        """
        Create a register manager using the given sources for control state,
        power state and pricing.

        Call `update_controller()` to load controller register definitions and
        `update_consumers()` to track the active consumer managers. Consumer
        definitions appear after the managers publish them.

        Args:
            control_mode: source for control mode registers
            get_power_status: source for power status registers
            get_price_now: source for price registers
        """
        self._control_mode = control_mode
        self._get_power_status = get_power_status
        self._get_price_now = get_price_now
        self._power_controller_registers: dict[str, Register] = {}
        self._power_consumers: dict[str, PowerConsumerManager] = {}
        self._consumer_banks: tuple[tuple[str, RegisterBank | None], ...] = ()
        self._register_bank: RegisterBank | None = None

    def get_register_bank(self) -> RegisterBank:
        """
        Return the combined bank for the current published register definitions.
        """
        consumer_banks = tuple((name, consumer.discovered_registers) for name, consumer in self._power_consumers.items())
        bank = self._register_bank
        if bank is None or consumer_banks != self._consumer_banks:
            bank = RegisterBank(
                chain(
                    self._get_status_registers(),
                    self._power_controller_registers.items(),
                    self._get_power_consumer_registers(consumer_banks),
                )
            )
            self._register_bank = bank
            self._consumer_banks = consumer_banks
        return bank

    async def update_controller(self, controller: PowerController | None) -> None:
        """
        Replace the controller register definitions.
        """
        if controller is None:
            self._power_controller_registers = {}
        else:
            controller_registers: RegisterBank = await controller.get_registers()
            self._power_controller_registers = {
                f'controller/{name}': register
                for name, register in controller_registers.items()
            }
        self._register_bank = None

    def update_consumers(self, consumers: dict[str, PowerConsumerManager]) -> None:
        """
        Replace the set of active consumer managers.
        """
        self._power_consumers = consumers.copy()
        self._consumer_banks = ()
        self._register_bank = None

    def _get_status_registers(self) -> Iterator[tuple[str, Register]]:
        """
        Yield registers for control modes, parameters, and live status.

        Battery and inverter controls use `status/battery/{field}` and
        `status/inverter/{field}`. Control parameters use
        `status/parameter/{field}`. Power controller and current price fields
        share `status/power/{field}`. Consumer status fields and properties
        use `status/power/consumer/{consumer_name}/{field}`.
        """
        yield 'status/battery/mode', CallRegister(lambda: self._control_mode.battery_mode.name)
        yield 'status/battery/policy', CallRegister(lambda: self._control_mode.battery_policy.name)
        yield 'status/inverter/mode', CallRegister(lambda: self._control_mode.inverter_mode.name)
        yield 'status/inverter/policy', CallRegister(lambda: self._control_mode.inverter_policy.name)

        yield 'status/parameter/fixed_limit_pct', \
            CallRegister(lambda: self._control_mode.fixed_limit_pct)
        yield 'status/parameter/start_charge_price_threshold', \
            CallRegister(lambda: self._control_mode.start_charge_price_threshold)
        yield 'status/parameter/stop_charge_price_threshold', \
            CallRegister(lambda: self._control_mode.stop_charge_price_threshold)
        yield 'status/parameter/enable_export_price_threshold', \
            CallRegister(lambda: self._control_mode.enable_export_price_threshold)
        yield 'status/parameter/disable_export_price_threshold', \
            CallRegister(lambda: self._control_mode.disable_export_price_threshold)

        # Power controller fields use status/power/{field}.
        for field in fields(PowerStatus):
            reg_type = check_type(field.type)
            yield f'status/power/{field.name}', PowerRegister(self._get_power_status, field.name, reg_type)

        # Consumer status exposes fields and properties with supported register types.
        for consumer_name, consumer in self._power_consumers.items():
            for field in fields(ConsumerStatus):
                try:
                    reg_type = check_type(field.type)
                except TypeError:
                    continue
                yield f'status/power/consumer/{consumer_name}/{field.name}', \
                    ConsumerRegister(consumer, field.name, reg_type)
            for prop_name, prop_type in _get_dataclass_properties(ConsumerStatus):
                try:
                    reg_type: RegisterType = check_type(prop_type)
                except TypeError:
                    continue
                yield f'status/power/consumer/{consumer_name}/{prop_name}', \
                    ConsumerRegister(consumer, prop_name, reg_type)

        # Current price fields share status/power/{field}, with interval timestamps skipped.
        for field in fields(Price):
            if field.name in ('start_time', 'end_time'):
                continue
            reg_type = check_type(field.type)
            yield f'status/power/{field.name}', PriceRegister(self._get_price_now, field.name, reg_type)

    @staticmethod
    def _get_power_consumer_registers(
            consumer_banks: tuple[tuple[str, RegisterBank | None], ...],
    ) -> Iterator[tuple[str, Register]]:
        for consumer_name, registers in consumer_banks:
            if registers is not None:
                for register_name, register in registers.items():
                    yield f'consumer/{consumer_name}/{register_name}', register


class PowerRegister(ReadOnlyRegister):
    """
    Expose a power status field as a read-only register.
    """

    def __init__(
            self,
            get_power_status: Callable[[], Awaitable[PowerStatus]],
            field_name: str,
            register_type: RegisterType,
    ) -> None:
        self._field_name = field_name
        self._get_power_status = get_power_status
        super().__init__(register_type)

    async def _get(self) -> RegisterValue:
        return getattr(await self._get_power_status(), self._field_name)


class PriceRegister(ReadOnlyRegister):
    """
    Expose a current electricity price field as a read-only register.
    """

    def __init__(
            self,
            get_price_now: Callable[[], Awaitable[Price]],
            field_name: str,
            register_type: RegisterType,
    ) -> None:
        self._field_name = field_name
        self._get_price_now = get_price_now
        super().__init__(register_type)

    async def _get(self) -> RegisterValue:
        return getattr(await self._get_price_now(), self._field_name)


class ConsumerRegister(ReadOnlyRegister):
    """
    Expose a consumer status field as a read-only register.
    """

    def __init__(self, consumer: PowerConsumerManager, field_name: str, register_type: RegisterType) -> None:
        self._field_name = field_name
        self._consumer = consumer
        super().__init__(register_type)

    async def _get(self) -> RegisterValue:
        status: ConsumerStatus | None = self._consumer.try_get_status()
        if status is None:
            raise RegisterValueUnavailable('consumer status is unavailable')
        else:
            return getattr(status, self._field_name)


def _get_dataclass_properties(cls: type) -> Iterator[tuple[str, object]]:
    """
    Iterate over properties defined on a class and their return types.

    Args:
        cls: Class whose properties are to be inspected.

    Yields:
        Property name and annotated getter return type.
    """
    for name, member in getmembers(cls):
        if isinstance(member, property) and member.fget is not None:
            prop_type = get_type_hints(member.fget)['return']
            yield name, prop_type
