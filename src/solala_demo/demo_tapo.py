import asyncio
from enum import auto, Enum

from kasa import Credentials, Discover

from solala.utils.local_config_help import config


class Action(Enum):
    on = auto()
    off = auto()
    status = auto()


async def main() -> None:
    """
    Explore a Tapo P110M smart plug using its local LAN interface.
    """
    host = config.TAPO_HOST
    username = config.TAPO_USERNAME
    password = config.TAPO_PASSWORD
    action = Action.status

    device = await Discover.discover_single(
        host,
        credentials=Credentials(username, password),
    )
    if device is None:
        raise RuntimeError(f'No supported device found: host = {host!r}')

    try:
        await device.update()
        print(f'Alias: {device.alias}')
        print(f'Model: {device.model}')
        print(f'On: {device.is_on}')

        match action:
            case Action.on:
                await device.turn_on()
                await device.update()
            case Action.off:
                await device.turn_off()
                await device.update()

        print('Available features:')
        for feature_id, feature in sorted(device.features.items()):
            try:
                print(f'  {feature_id}: {feature.value!r}')
            except Exception as err:
                print(f'  {feature_id}: unavailable ({err!r})')
    finally:
        await device.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
