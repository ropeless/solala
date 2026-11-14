from abc import abstractmethod, ABC
from collections.abc import Sequence
from dataclasses import dataclass

from pymodbus.client import ModbusTcpClient
from pymodbus.pdu import ModbusPDU

from solala.logger import LOGGER
from solala.registers import ReadOnlyError, RegisterType, RegisterValue

NEXT_SF = -1  # The special scale factor address to use to nominate the next register.

type MODBUS_MODEL = int

_DEBUG_LOG = False  # Enable debug logger messages or not.
_LOG_SRC = '[modbus] '  # prefix for log messages


class ModbusError(IOError):
    """
    Raised when a Modbus read or write operation returns an error.

    Attributes:
        device: Modbus device ID.
        modbus_model: SunSpec model containing the register.
        addr: Register's relative address within the model.
        physical_addr: Absolute Modbus address used for the operation.
        count: Number of registers involved in the operation.
        read_write: Whether the failed operation was a read or write.
        result: Modbus response containing the error.
        modbus_message: Description of the Modbus exception code.
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
    ) -> None:
        super().__init__(
            f'Modbus {read_write} error device {device} at Model_{modbus_model}({addr})/{physical_addr}, '
            f'count {count}: {result}'
        )
        self.device = device
        self.modbus_model = modbus_model
        self.addr = addr
        self.physical_addr = physical_addr
        self.count = count
        self.read_write = read_write
        self.result = result
        self.modbus_message = _modbus_exception_code_message(result.exception_code)


@dataclass
class RegisterContext:
    """
    Identify the Modbus TCP connection, Modbus device ID, and
    address offset to used for a defined register operation.

    Attributes:
        client: Modbus TCP client used to communicate with the device.
        device_id: Modbus device ID.
        modbus_model: SunSpec model containing the register.
        address_offset: Offset added to a relative register address to obtain
            its physical, zero-based Modbus address.
    """

    client: ModbusTcpClient
    device_id: int
    modbus_model: MODBUS_MODEL
    address_offset: int


class RegisterAccess(ABC):
    """
    Abstract base class for defining reading and writing operations to a Modbus register.
    An implementation of this class takes into account the datatype of the register,
    including the number of atomic 16-bit registers to read/write and any scaling factor.
    """

    def __init__(self, register_type: RegisterType, writable: bool) -> None:
        self.register_type = register_type
        self.writable = writable

    @abstractmethod
    def get(self, context: RegisterContext) -> RegisterValue:
        ...

    @abstractmethod
    def set(self, context: RegisterContext, value: RegisterValue) -> None:
        ...


def uint16(addr: int, writable: bool = False) -> RegisterAccess:
    """
    Define an unsigned 16-bit unsigned integer register, at the given relative address.
    """
    return RegisterAccessInt(addr, count=1, signed=False, writable=writable)


def int16(addr: int, writable: bool = False) -> RegisterAccess:
    """
    Define a signed 16-bit unsigned integer register at the given relative address.
    """
    return RegisterAccessInt(addr, count=1, signed=True, writable=writable)


def uint32(addr: int, writable: bool = False) -> RegisterAccess:
    """
    Define an unsigned 32-bit unsigned integer register, at the given relative address.
    """
    return RegisterAccessInt(addr, count=2, signed=False, writable=writable)


def uint64(addr: int, writable: bool = False) -> RegisterAccess:
    """
    Define an unsigned 64-bit unsigned integer register, at the given relative address.
    """
    return RegisterAccessInt(addr, count=4, signed=False, writable=writable)


def int32(addr: int, writable: bool = False) -> RegisterAccess:
    """
    Define a signed 32-bit unsigned integer register at the given relative address.
    """
    return RegisterAccessInt(addr, count=2, signed=True, writable=writable)


def int64(addr: int, writable: bool = False) -> RegisterAccess:
    """
    Define a signed 64-bit unsigned integer register at the given relative address.
    """
    return RegisterAccessInt(addr, count=4, signed=True, writable=writable)


def str2(addr: int) -> RegisterAccess:
    """
    Define a string covering 2 registers, at the given relative address.
    """
    return RegisterAccessStr(addr, count=2)


def str4(addr: int) -> RegisterAccess:
    """
    Define a string covering 4 registers, at the given relative address.
    """
    return RegisterAccessStr(addr, count=4)


def str8(addr: int) -> RegisterAccess:
    """
    Define a string covering 8 registers, at the given relative address.
    """
    return RegisterAccessStr(addr, count=8)


def str16(addr: int) -> RegisterAccess:
    """
    Define a string covering 16 registers, at the given relative address.
    """
    return RegisterAccessStr(addr, count=16)


def scaled_uint16(addr: int, scale_addr: int, writable: bool = False) -> RegisterAccess:
    """
    Define a scaled unsigned integer at the given relative address.
    Internal format: uint16 & scale-factor.
    """
    return RegisterAccessScaled(addr, scale_addr, 1, signed=False, writable=writable)


def scaled_int16(addr: int, scale_addr: int, writable: bool = False) -> RegisterAccess:
    """
    Define a scaled unsigned integer at the given relative address.
    Internal format: int16 & scale-factor.
    """
    return RegisterAccessScaled(addr, scale_addr, 1, signed=True, writable=writable)


def scaled_uint32(addr: int, scale_addr: int, writable: bool = False) -> RegisterAccess:
    """
    Define a scaled unsigned integer at the given relative address.
    Internal format: uint32 & scale-factor.
    """
    return RegisterAccessScaled(addr, scale_addr, 2, signed=False, writable=writable)


def scaled_int32(addr: int, scale_addr: int, writable: bool = False) -> RegisterAccess:
    """
    Define a scaled unsigned integer at the given relative address.
    Internal format: int32 & scale-factor.
    """
    return RegisterAccessScaled(addr, scale_addr, 2, signed=True, writable=writable)


def _read_byte_array(
        context: RegisterContext,
        addr: int,
        *,
        count: int,
) -> bytearray:
    """
    Read `count` registers as a byte array.

    Args:
        context: The RegisterContext defining where to read from.
        addr:
        count:

    Returns:
        the read byte array.
    """
    physical_addr = addr + context.address_offset
    result: ModbusPDU = context.client.read_holding_registers(
        physical_addr,
        count=count,
        device_id=context.device_id,
    )

    if result.isError():
        raise ModbusError(context.device_id, context.modbus_model, addr, physical_addr, count, 'read', result)
    the_bytes = _registers_to_bytearray(result.registers)

    _log(f'read byte array: physical_addr={physical_addr} count={count} result=0x{the_bytes.hex()}')
    return the_bytes


def _registers_to_bytearray(registers: Sequence[int]) -> bytearray:
    """
    Convert 16-bit register values to a big-endian byte array.

    Args:
        registers: Register values to convert.

    Returns:
        The register contents as a byte array.
    """
    byte_array = bytearray()
    for reg_result in registers:
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
    """
    Write an integer, signed or unsigned, covering `count` registers.

    Args:
        context: The RegisterContext defining where to write to.
        addr: The relative address of the first register to write to.
        count: The number of registers to write to.
        signed: Whether the integer is signed or unsigned.
        value: The integer value to write.
    """
    # We only permit writing a single 16bit register at the moment.
    check_valid_int(value=value, count=count, signed=signed)
    physical_addr = addr + context.address_offset
    match count:
        case 1:
            value &= 0xFFFF
            _log(f'write int: physical_addr={physical_addr} count={count} value={value}')
            result: ModbusPDU = context.client.write_registers(
                physical_addr,
                values=[value],
                device_id=context.device_id
            )

            if result.isError():
                raise ModbusError(context.device_id, context.modbus_model, addr, physical_addr, count, 'write', result)
        case _:
            raise IOError('cannot write int - not implemented')


def _modbus_exception_code_message(code: int) -> str:
    """
    Map a Modbus exception code to a human-readable message.
    """
    match code:
        case 1:
            return 'Illegal Function'
        case 2:
            return 'Illegal Data Address'
        case 3:
            return 'Illegal Data Value'
        case 4:
            return 'Server Device Failure'
        case 5:
            return 'Acknowledge'
        case 6:
            return 'Server Device Busy'
        case 8:
            return 'Memory Parity Error'
        case _:
            return f'Unknown Modbus error'


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
    """
    Read-only access to a string stored across consecutive Modbus registers.
    """

    def __init__(self, addr: int, count: int) -> None:
        """
        Initialise string register access.

        Args:
            addr: Relative address of the first register.
            count: Number of 16-bit registers occupied by the string.
        """
        super().__init__(register_type=str, writable=False)
        self.addr = addr
        self.count = count

    def get(self, context: RegisterContext) -> str:
        byte_array = _read_byte_array(context, self.addr, count=self.count)
        return byte_array.decode('utf-8', errors='ignore').strip('\x00')

    def set(self, context: RegisterContext, value: RegisterValue) -> None:
        raise ReadOnlyError()


class RegisterAccessInt(RegisterAccess):
    """
    Access an integer stored across one or more consecutive Modbus registers.
    """

    def __init__(self, addr: int, count: int, signed: bool, writable: bool) -> None:
        """
        Initialise integer register access.

        Args:
            addr: Relative address of the first register (relative to the SunSpec model start, counting from one).
            count: Number of 16-bit registers occupied by the integer.
            signed: Whether the integer is signed (versus unsigned).
            writable: Whether the register can be written or not.
        """
        super().__init__(register_type=int, writable=writable)
        self.addr = addr
        self.count = count
        self.signed = signed

    def get(self, context: RegisterContext) -> int:
        byte_array = _read_byte_array(context, self.addr, count=self.count)
        return int.from_bytes(byte_array, byteorder='big', signed=self.signed)

    def set(self, context: RegisterContext, value: RegisterValue) -> None:
        if not self.writable:
            raise ReadOnlyError()
        if not isinstance(value, int):
            raise TypeError(type(value))
        if value < 0 and not self.signed:
            raise ValueError('Value is negative but register is unsigned')
        _write_int(context, self.addr, value=value, count=self.count, signed=self.signed)


class RegisterAccessScaled(RegisterAccess):
    """
    Access an integer register whose value is adjusted by a scale factor.

    The scale factor is a signed 16-bit integer representing a power of ten.
    """

    def __init__(self, addr: int, scale_addr: int, count: int, signed: bool, writable: bool) -> None:
        """
        Initialise scaled integer register access.

        Args:
            addr: Relative address of the first register (relative to the SunSpec model start, counting from one).
            scale_addr: Relative address of the scale-factor register, or
                NEXT_SF to use the register immediately after the value.
            count: Number of 16-bit registers occupied by the value.
            signed: Whether the value is signed.
            writable: Whether the register can be written.
        """
        super().__init__(register_type=float, writable=writable)
        self.addr = addr
        self.scale_addr = (addr + 1) if scale_addr == NEXT_SF else scale_addr
        self.count = count
        self.signed = signed
        self.start = min(self.addr, self.scale_addr)
        self.end = max(self.addr + count - 1, self.scale_addr)
        self.run_length = self.end - self.start + 1

    def get(self, context: RegisterContext) -> float:
        physical_addr = self.start + context.address_offset
        result: ModbusPDU = context.client.read_holding_registers(
            physical_addr,
            count=self.run_length,
            device_id=context.device_id,
        )
        if result.isError():
            raise ModbusError(
                context.device_id, context.modbus_model, self.start, physical_addr, self.run_length, 'read', result
            )

        def reg_value(_addr: int, _count: int, _signed: bool) -> int:
            _addr -= self.start
            value_byte_array = _registers_to_bytearray(result.registers[_addr: _addr + _count])
            return int.from_bytes(value_byte_array, byteorder='big', signed=_signed)

        value: int = reg_value(self.addr, self.count, self.signed)
        scale: int = reg_value(self.scale_addr, 1, True)

        _log(f'read scaled int: physical_addr={self.addr + context.address_offset} value={value}')
        _log(f'read scaled int: physical_addr={self.scale_addr + context.address_offset} scale={scale}')

        return value * (10 ** scale)

    def set(self, context: RegisterContext, value: RegisterValue) -> None:
        if not self.writable:
            raise ReadOnlyError()
        if not isinstance(value, int | float):
            raise TypeError(type(value))
        if value < 0 and not self.signed:
            raise ValueError('Value is negative but register is unsigned')

        _log(f'write scale int: value={value}')

        # We keep the same scaling factor
        byte_array = _read_byte_array(context, self.scale_addr, count=1)
        scale: int = int.from_bytes(byte_array, byteorder='big', signed=True)

        _log(f'write scale int: read scale={scale}')

        if isinstance(value, float):
            scaled_value = int(value * (10 ** -scale) + 0.5)  # add 0.5 for rounding
            _write_int(
                context, self.addr, value=scaled_value, count=self.count, signed=self.signed
            )
        elif isinstance(value, int):
            if scale > 0:
                factor = 10 ** scale
                scaled_value = value // factor
                if scaled_value * factor != value:
                    raise ValueError('Value is not an integer multiple of the scaling factor')
            else:
                scaled_value = value * (10 ** -scale)
            _write_int(
                context, self.addr, value=scaled_value, count=self.count, signed=self.signed
            )
        else:
            assert False, 'unexpected type'


def _log(msg: str) -> None:
    """
    Write a debug message to the logger (only when _DEBUG_LOG is True).

    Args:
        msg: Message to log.
    """
    if _DEBUG_LOG:
        LOGGER.debug(f'{_LOG_SRC}{msg}')  # type: ignore[PyUnreachableCode]
