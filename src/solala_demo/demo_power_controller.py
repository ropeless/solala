import json

from pymodbus.client import ModbusTcpClient

from local_config import MASTER_INVERTER_ADDR, SLAVE_INVERTER_ADDR
from solala.log import configure_logger
from solala.power_controller.impl_modbus.modbus import Modbus, ModbusDevice
from solala.power_controller.impl_modbus.modbus_power_controller import ModbusPowerController

MASTER_INVERTER_DEVICE_ID = 1
SLAVE_INVERTER_DEVICE_ID = 1
METER_INVERTER_DEVICE_ID = 200


def main():
    configure_logger()
    master = ModbusTcpClient(MASTER_INVERTER_ADDR)
    slave = ModbusTcpClient(SLAVE_INVERTER_ADDR)

    devices = {
        'master': ModbusDevice(master, MASTER_INVERTER_DEVICE_ID),
        'slave': ModbusDevice(slave, SLAVE_INVERTER_DEVICE_ID),
        'meter': ModbusDevice(master, METER_INVERTER_DEVICE_ID),
    }

    with Modbus(devices) as modbus:
        controller = ModbusPowerController(
            modbus,
            master='master',
            slaves=['slave'],
            meter='meter',
        )

        print()
        status = controller.get_status().as_dict()
        print(json.dumps(status, indent=4))

        # print()
        # power_controller.enable_battery()
        # power_controller.disable_battery()
        # power_controller.force_charge()
        # power_controller.force_discharge()

        # print()
        # while True:
        #     print()
        #     power_controller.disable_export(change_duration=10)
        #     time.sleep(5)
        # power_controller.enable_export()

        print()


if __name__ == '__main__':
    main()
