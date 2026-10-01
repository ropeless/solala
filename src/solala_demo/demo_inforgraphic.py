from pathlib import Path

from local_config import OUT
from solala.server_infographic import Infographic


def main() -> None:
    infographic = Infographic()
    infographic.make(
        state_of_charge=100,
        battery_power=321,
        grid_power=456,
        house_power=768,
        solar_power=981,
        power_scale=100,
        buy_price=12.3,
        feed_in_price=4.5,
    )

    file_path: Path = OUT / 'infographic.svg'
    infographic.canvas.save_svg(file_path)


if __name__ == '__main__':
    main()
