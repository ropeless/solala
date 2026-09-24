from pymodbus.client import ModbusTcpClient

from local_config import MASTER_INVERTER_MAC_ADDR
from solala.utils.network import find_ip_by_mac


def main() -> None:
    mac_address = MASTER_INVERTER_MAC_ADDR
    print(f'MAC address: {mac_address}')
    ip_address = find_ip_by_mac([mac_address])[mac_address]
    print(f'IP address: {ip_address}')
    client = ModbusTcpClient(ip_address, port=502)
    client.connect()
    print()

    # Find all modbus model blocks
    address_offset = 1
    for device_id in range(1, 256):
        current_address = 40002
        while current_address < 45000:
            # Read the Model ID and Length (2 registers)
            result = client.read_holding_registers(address=current_address, count=2, device_id=device_id)

            if result.isError():
                break

            model_id = result.registers[0]
            block_length = result.registers[1]

            if model_id == 65535:
                break

            print(f'device_id={device_id}, address={current_address+address_offset}, model_id={model_id}')

            # Move to the next block identifier
            current_address += 2 + block_length


if __name__ == '__main__':
    main()
