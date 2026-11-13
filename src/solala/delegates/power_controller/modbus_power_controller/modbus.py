from dataclasses import dataclass
from collections.abc import Iterable, Mapping, Sequence

from pymodbus.client import ModbusTcpClient

from solala.delegates.power_controller.modbus_power_controller.modbus_register_access import RegisterContext, \
    RegisterAccess, \
    MODBUS_MODEL
from solala.delegates.power_controller.modbus_power_controller.modbus_registers import MODELS, mppt_modules, MPPT_MODEL
from solala.logger import LOGGER
from solala.registers import Register, RegisterValue, RegisterBank

@dataclass
class ModbusDevice:
    client: ModbusTcpClient
    device_id: int

class ModbusRegister(Register):

    def __init__(self, access: RegisterAccess, context: RegisterContext):
        super().__init__(access.register_type, access.writable)
        self._access: RegisterAccess = access
        self._context: RegisterContext = context

    async def _get(self) -> RegisterValue:
        return self._access.get(self._context)

    async def _set(self, value: RegisterValue) -> None:
        return self._access.set(self._context, value)

type ModbusDevices = Mapping[str | None, ModbusDevice]

class Modbus(RegisterBank):
    """
    This class provides access to Modbus registers for devices (potentially via multiple clients).
    Register access takes into account the data type of each register (string, integer, or scaled integer, etc.).

    Register names are of the form `logical_device_id/register_name` if the logical device ID is provided, otherwise
    registers are named `register_name`.
    """

    def __init__(self, devices: ModbusDevices | ModbusDevice | ModbusTcpClient):
        """
        Wraps a ModbusTcpClient to provide access to Modbus registers.

        The available registers are determined automatically using potential registers defined in `registers.MODELS`.
        Given a ModbusTcpClient and device id, the register blocks of that device are searched to find all
        matching Modbus models matching `registers.MODELS`.

        If `devices` is a Mapping, then it maps logical device IDs to ModbusDevice objects. If the logical
        device ID is a string, then registers are named `{logical_device_id}/{register_name}`, where `{register_name}`
        is taken from matching models. If the logical device ID is None, then registers are named `{register_name}`.

        If `devices` is a single ModbusDevice object, `device`, then it is equivalent to the mapping `{None: device}`.
        I.e. a single device with no logical device name.

        If `devices` is a ModbusTcpClient, then it is assumed that all devices are on the same client,
        and a ModbusDevice is created for each device ID found (in the range 1 to 255), with
        `logical_device_id = str(device_id)`.

        Args:
            devices: A mapping of logical device IDs to ModbusDevice objects, or a ModbusTcpClient
                object, or a single ModbusDevice.
        """

        if isinstance(devices, ModbusTcpClient):
            client: ModbusTcpClient = devices
            devices: ModbusDevices = {
                str(device_id): ModbusDevice(client, device_id)
                for device_id in _find_devices(devices)
            }
        elif isinstance(devices, ModbusDevice):
            devices: ModbusDevices = {None: devices}

        self._devices: ModbusDevices = devices

        # Get unique clients
        # `clients_by_client_id` is client_id => ModbusTcpClient
        clients_by_client_id: Mapping[int, ModbusTcpClient] = {
            id(device.client): device.client
            for device in devices.values()
        }

        # Get unique devices mentioned for each client
        # `devices_by_client_id` is client_id => set(device_id)
        devices_by_client_id: Mapping[int, set[int]] = {
            client_id: {
                device.device_id
                for device in devices.values()
                if device.client is client
            }
            for client_id, client in clients_by_client_id.items()
        }

        # Find offset models for each client
        # `offset_models` is client_id => device_id => MODBUS_MODEL => address_offset
        offset_models: dict[int, dict[int, dict[MODBUS_MODEL, int]]] = {
            id_client: {
                device_id: _find_model_offsets(clients_by_client_id[id_client], device_id)
                for device_id in device_ids
            }
            for id_client, device_ids in devices_by_client_id.items()
        }

        # Construct logical devices
        # `device_registers` is logical_device_id => LogicalDevice
        device_registers: dict[str, ModbusRegister] = {}
        logical_device_id: str | None
        for logical_device_id, device in devices.items():
            client: ModbusTcpClient = device.client
            device_id: int = device.device_id
            client_models = offset_models[id(client)]
            if device_id not in client_models:
                LOGGER.warning(
                    f'no registers for logical device {logical_device_id!r}, device_id {device_id}, client {client.comm_params.host}')
                continue
            model_to_offset: dict[MODBUS_MODEL, int] = client_models[device_id]

            for modbus_model, address_offset in model_to_offset.items():
                if modbus_model == MPPT_MODEL:
                    model_registers: dict[str, RegisterAccess] = dict(MODELS[modbus_model])
                    # append special MPPT modules
                    context = RegisterContext(client, device_id, modbus_model, address_offset)
                    n_access: RegisterAccess = model_registers['N']
                    number_of_modules = n_access.get(context)
                    if not isinstance(number_of_modules, int):
                        raise RuntimeError(f'could not get number of MPPT modules: {number_of_modules!r}')
                    model_registers.update(mppt_modules(number_of_modules))
                else:
                    model_registers: Mapping[str, RegisterAccess] = MODELS[modbus_model]

                for register_name, register_access in model_registers.items():
                    context = RegisterContext(client, device_id, modbus_model, address_offset)
                    full_name: str = (
                        register_name if logical_device_id is None
                        else f'{logical_device_id}/{register_name}'
                    )
                    device_registers[full_name] = ModbusRegister(register_access, context)

        # Create fields
        self._clients: Sequence[ModbusTcpClient] = list(clients_by_client_id.values())
        super().__init__(device_registers)

    def connect(self) -> None:
        """
        Delegate `connect` to each unique Modbus client.
        """
        for client in self._clients:
            client.connect()

    def devices(self) -> ModbusDevices:
        """
        Return the Modbus devices.
        """
        return self._devices

    def close(self) -> None:
        """
        Delegate `close` to each unique Modbus client.
        """
        for client in self._clients:
            client.close()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

def _find_devices(client: ModbusTcpClient) -> Iterable[int]:
    address = 40000
    for device_id in range(1, 256):
        result = client.read_holding_registers(address=address, count=2, device_id=device_id)
        if result.isError():
            continue
        registers = (result.registers[0], result.registers[1])
        if not registers == (21365, 28243):
            # Not `SunS`
            continue
        yield device_id

def _find_model_offsets(client: ModbusTcpClient, device_id: int) -> dict[MODBUS_MODEL, int]:
    result: dict[MODBUS_MODEL, int] = {
        0: -1,  # initialise with the special zero model, where registers are in Modicon (40xxx) format.
    }
    current_address = 40002
    while current_address < 45000:
        # Read the Model ID and Length (2 registers)
        read_result = client.read_holding_registers(address=current_address, count=2, device_id=device_id)
        if read_result.isError():
            break
        model_id = read_result.registers[0]
        block_length = read_result.registers[1]

        if model_id == 65535:
            # End Block
            break

        if model_id in result:
            LOGGER.warning(f'Duplicate Modbus Model {model_id} for device {device_id}')
        else:
            result[model_id] = current_address - 1  # subtract 1 as relative address start from 1.

        # Move to the next block identifier
        current_address += 2 + block_length

    return result
