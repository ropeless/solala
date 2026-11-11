import asyncio
from pprint import pprint

from tuya_connector import TuyaOpenAPI

from solala.utils.local_config_help import config
from solala.delegates.power_consumer.tuya_power_consumer.tuya_power_consumer import TuyaPowerConsumer


API_ENDPOINT = "https://openapi.tuyaeu.com"


def check_cloud_api() -> None:
    device_id = config.POWER_POINT_DEVICE

    # Connect to Tuya Cloud
    api = TuyaOpenAPI(
        API_ENDPOINT,
        config.POWER_POINT_ACCESS_ID,
        config.POWER_POINT_ACCESS_SECRET,
    )

    response = api.connect()
    print("Connection response:")
    pprint(response)

    # Retrieve device status
    response = api.get(
        f"/v1.0/iot-03/devices/{device_id}/status"
    )

    print("\nDevice status:")
    pprint(response)

    # Retrieve supported device functions
    response = api.get(
        f"/v1.0/iot-03/devices/{device_id}/functions"
    )

    print("\nDevice functions:")
    pprint(response)


async def main() -> None:
    # check_cloud_api()

    async with TuyaPowerConsumer(
            access_id=config.POWER_POINT_ACCESS_ID,
            access_secret=config.POWER_POINT_ACCESS_SECRET,
            device_id=config.POWER_POINT_DEVICE,
    ) as device:
        for name, value in (await device.get_registers()).items():
            print(f'{name} =  {value!r}')


if __name__ == '__main__':
    asyncio.run(main())
