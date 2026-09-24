from abc import abstractmethod, ABC
from dataclasses import dataclass
from typing import TypeAlias

from pymodbus.client import ModbusTcpClient
from pymodbus.pdu import ModbusPDU

NEXT_SF = -1  # The scale factor address to use to mean the next register.

MODBUS_MODEL: TypeAlias = int


class ReadOnlyError(AttributeError):
    """
    Raised when requesting to write to a read-only Modbus register or field.
    """

    def __init__(self):
        super().__init__('Not writable')


class ModbusError(IOError):
    """
    Raised when a Modbus IO error occurs.
    """

    def __init__(
            self,
            device: int,
            modbus_model: MODBUS_MODEL,
            addr: int,
            physical_addr: int,
            count: int,
            read_write: str,
            result: ModbusPDU,
    ):
        super().__init__(
            f'Modbus {read_write} error device {device} at Model_{modbus_model}({addr})/{physical_addr}, '
            f'count {count}: {result}'
        )


@dataclass
class RegisterContext:
    client: ModbusTcpClient
    device_id: int
    modbus_model: MODBUS_MODEL
    address_offset: int


class RegisterAccess(ABC):

    @abstractmethod
    def get(self, context: RegisterContext) -> int | float | str:
        ...

    @abstractmethod
    def set(self, context: RegisterContext, value: int | float | str) -> None:
        ...


def uint16(addr: int, writable: bool = False) -> RegisterAccess:
    return RegisterAccessInt(addr, count=1, signed=False, writable=writable)


def int16(addr: int, writable: bool = False) -> RegisterAccess:
    return RegisterAccessInt(addr, count=1, signed=True, writable=writable)


def uint32(addr: int, writable: bool = False) -> RegisterAccess:
    return RegisterAccessInt(addr, count=2, signed=False, writable=writable)


def int32(addr: int, writable: bool = False) -> RegisterAccess:
    return RegisterAccessInt(addr, count=2, signed=True, writable=writable)


def str2(addr: int) -> RegisterAccess:
    return RegisterAccessStr(addr, count=2)


def str4(addr: int) -> RegisterAccess:
    return RegisterAccessStr(addr, count=4)


def str8(addr: int) -> RegisterAccess:
    return RegisterAccessStr(addr, count=8)


def str16(addr: int) -> RegisterAccess:
    return RegisterAccessStr(addr, count=16)


def scaled_uint(addr: int, scale_addr: int, writable: bool = False) -> RegisterAccess:
    """
    uint16 + scale-factor.
    """
    return RegisterAccessScaled(addr, scale_addr, signed=False, writable=writable)


def scaled_int(addr: int, scale_addr: int, writable: bool = False) -> RegisterAccess:
    """
    int16 + scale-factor.
    """
    return RegisterAccessScaled(addr, scale_addr, signed=True, writable=writable)


def _read_byte_array(
        context: RegisterContext,
        addr: int,
        *,
        count: int,
) -> bytearray:
    physical_addr = addr + context.address_offset
    result: ModbusPDU = context.client.read_holding_registers(
        physical_addr,
        count=count,
        device_id=context.device_id,
    )
    if result.isError():
        raise ModbusError(context.device_id, context.modbus_model, addr, physical_addr, count, 'read', result)
    byte_array = bytearray()
    for reg_result in result.registers:
        byte_array.extend(reg_result.to_bytes(2, byteorder='big'))
    return byte_array


def _write_int(
        context: RegisterContext,
        addr: int,
        *,
        count: int,
        signed: bool,
        value: int,
) -> None:
    # We only permit writing a single 16bit register at the moment.
    check_valid_int(value=value, count=count, signed=signed)
    physical_addr = addr + context.address_offset
    match count:
        case 1:
            value &= 0xFFFF
            result: ModbusPDU = context.client.write_registers(
                physical_addr,
                values=[value],
                device_id=context.device_id
            )
            if result.isError():
                raise ModbusError(context.device_id, context.modbus_model, addr, physical_addr, count, 'write', result)
        case _:
            raise IOError('cannot write int')


def check_valid_int(value: int, count: int, signed: bool) -> None:
    """
    Raise a ValueError if the value is out of range for the given register count and sign.
    """
    bits = 16 * count
    if signed:
        max_signed = 2 ** (bits - 1) - 1
        min_signed = -max_signed - 1
        if value < min_signed or value > max_signed:
            raise ValueError(f'Value {value} is out of range for int{bits} registers')
    else:
        max_unsigned = 2 ** bits - 1
        if value < 0 or value > max_unsigned:
            raise ValueError(f'Value {value} is out of range for uint{bits} registers')


class RegisterAccessStr(RegisterAccess):

    def __init__(self, addr: int, count: int):
        self.addr = addr
        self.count = count

    def get(self, context: RegisterContext) -> str:
        byte_array = _read_byte_array(context, self.addr, count=self.count)
        return byte_array.decode('utf-8', errors='ignore').strip('\x00')

    def set(self, context: RegisterContext, value: int | float | str) -> None:
        raise ReadOnlyError()


class RegisterAccessInt(RegisterAccess):

    def __init__(self, addr: int, count: int, signed: bool, writable: bool):
        self.addr = addr
        self.count = count
        self.signed = signed
        self.writable = writable

    def get(self, context: RegisterContext) -> int:
        byte_array = _read_byte_array(context, self.addr, count=self.count)
        return int.from_bytes(byte_array, byteorder='big', signed=self.signed)

    def set(self, context: RegisterContext, value: int | float | str) -> None:
        if not isinstance(value, int):
            raise TypeError(type(value))
        if value < 0 and not self.signed:
            raise ValueError('Value is negative but register is unsigned')
        if not self.writable:
            raise ReadOnlyError()
        _write_int(context, self.addr, value=value, count=self.count, signed=self.signed)


class RegisterAccessScaled(RegisterAccess):

    def __init__(self, addr: int, scale_addr: int, signed: bool, writable: bool):
        self.addr = addr
        self.scale_addr = (addr + 1) if scale_addr == NEXT_SF else scale_addr
        self.signed = signed
        self.start = min(self.addr, self.scale_addr)
        self.count = max(self.addr, self.scale_addr) - self.start + 1
        self.writable = writable

    def get(self, context: RegisterContext) -> float:
        physical_addr = self.start + context.address_offset
        result: ModbusPDU = context.client.read_holding_registers(
            physical_addr,
            count=self.count,
            device_id=context.device_id,
        )
        if result.isError():
            raise ModbusError(
                context.device_id, context.modbus_model, self.start, physical_addr, self.count, 'read', result
            )

        def reg_value(_addr: int, _signed: bool) -> int:
            value_reg = result.registers[_addr - self.start]
            value_byte_array = bytearray(value_reg.to_bytes(2, byteorder='big'))
            return int.from_bytes(value_byte_array, byteorder='big', signed=_signed)

        value: int = reg_value(self.addr, self.signed)
        scale: int = reg_value(self.scale_addr, True)
        return value * (10 ** scale)

    def set(self, context: RegisterContext, value: int | float | str) -> None:
        if not isinstance(value, int | float):
            raise TypeError(type(value))
        if value < 0 and not self.signed:
            raise ValueError('Value is negative but register is unsigned')
        if not self.writable:
            raise ReadOnlyError()

        # We keep the same scaling factor
        byte_array = _read_byte_array(context, self.scale_addr, count=1)
        scale: int = int.from_bytes(byte_array, byteorder='big', signed=True)

        if isinstance(value, float):
            scaled_value = int(value * (10 ** -scale) + 0.5)  # add 0.5 for rounding
            _write_int(
                context, self.addr, value=scaled_value, count=1, signed=self.signed
            )
        elif isinstance(value, int):
            if scale > 0:
                scaled_value = value // (10 ** scale)
                check_value = value * (10 ** scale)
                if value != check_value:
                    raise ValueError('Value is not an integer multiple of the scaling factor')
            else:
                scaled_value = value * (10 ** -scale)
            _write_int(
                context, self.addr, value=scaled_value, count=1, signed=self.signed
            )
        else:
            assert False, 'unexpected type'
