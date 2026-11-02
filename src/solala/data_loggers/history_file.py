import asyncio
from datetime import datetime
from pathlib import Path
from typing import Sequence, List, Dict

from solala.control_loop import control_loop
from solala.control_loop.loop_listener import LoopListener
from solala.control_loop.modes_and_policies import ControlMode
from solala.delegates.power_pricer.power_pricer import Price


class HistoryFile(LoopListener):
    """
    Record a history of:
    * control modes and policies
    * prices
    * registers
    """

    def __init__(self, file_path: Path | str, sep: str = ',', datetime_format: str = '%Y-%m-%d %H:%M:%S'):
        super().__init__()
        self._path = Path(file_path)
        self._file = open(file_path, 'a')
        self._sep = sep
        self._datetime_format = datetime_format
        self._first_update = True
        self._registers: Sequence[str] = ()

    def __str__(self) -> str:
        return f'{self.__class__.__name__}({self._path})'

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        control_loop.remove_control_loop_listener(self)
        if self._file is not None:
            self._file.close()
            self._file = None

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    async def update(self) -> None:
        now: str = datetime.now().strftime(self._datetime_format)

        register_values: Dict[str, int | float | str | bool]
        control_mode: ControlMode
        price: Price
        register_values, control_mode, price = await asyncio.gather(
            control_loop.get_registers(),
            control_loop.get_control_mode(),
            control_loop.get_price_now()
        )

        def _print(*msg):
            print(*msg, file=self._file, sep=self._sep)

        if self._first_update:
            self._first_update = False
            self._registers = tuple(register_values.keys())
            header: List[str] = [
                'timestamp',
                'battery/mode',
                'battery/policy',
                'inverter/mode',
                'inverter/policy',
            ]
            header.extend(self._registers)
            header.extend(
                f'price/{key}' for key in
                ('buy_price', 'feed_in_price', 'renewables', 'tariff_period', 'tariff_season', 'tariff_demand_window')
            )
            header.extend(
                f'charger/{key}' for key in
                ('voltage', 'current', 'power')
            )
            _print(*header)

        row: List[int | float | str | bool] = [
            now,
            control_mode.battery_mode.name,
            control_mode.battery_policy.name,
            control_mode.inverter_mode.name,
            control_mode.inverter_policy.name,
        ]
        row.extend(register_values[key] for key in self._registers)
        row.append(price.buy_price)
        row.append(price.feed_in_price)
        row.append(price.renewables)
        row.append(price.tariff_period)
        row.append(price.tariff_season)
        row.append(price.tariff_demand_window)
        _print(*row)
        self._file.flush()
