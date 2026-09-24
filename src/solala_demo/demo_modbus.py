from pymodbus.client import ModbusTcpClient

from local_config import MASTER_INVERTER_MAC_ADDR, SLAVE_INVERTER_MAC_ADDR
from solala.power_controller.impl_modbus.modbus import Modbus, ModbusDevice
from solala.utils.network import find_ip_by_mac


def main() -> None:
    ip_address = find_ip_by_mac([MASTER_INVERTER_MAC_ADDR, SLAVE_INVERTER_MAC_ADDR])
    master = ModbusTcpClient(ip_address[MASTER_INVERTER_MAC_ADDR])
    slave = ModbusTcpClient(ip_address[SLAVE_INVERTER_MAC_ADDR])

    devices = {
        'master': ModbusDevice(master, 1),
        'slave': ModbusDevice(slave, 1),
        'meter': ModbusDevice(master, 200),
    }

    with Modbus(devices) as modbus:
        sum_power(modbus)
        # show_one(modbus, 'master/W')


def show_one(modbus, param):
    print(param, modbus[param])


def sum_power(modbus):
    x = 0
    y = 0
    z = 0
    a = 0
    for register, value in modbus.items():
        if register.endswith('1/DCW') or register.endswith('2/DCW'):
            print(f'{register} = {value!r}')
            x += value
        elif register.endswith('/DCW'):
            print(f'{register} = {value!r}')
            y += value
        elif register.endswith('/W'):
            print(f'{register} = {value!r}')
            z += value
        elif register.endswith('/WMax'):
            print(f'{register} = {value!r}')
            a += value
    print()
    print('sum 1/DCW 2/DCW', x)
    print('sum /DCW', y)
    print('sum /W', z)
    print('sum /WMax', a)


if __name__ == '__main__':
    main()
