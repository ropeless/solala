from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Sequence, List, Dict

from solala import control_loop
from solala.car_charger.wall_charger import ChargerStatus
from solala.power_pricer.power_pricer import Price
from solala.utils.json import JSONDict, json_dict


class HistoryFile:
    """
    Record a history of:
    * control modes and policies
    * registers
    * prices
    * charger
    """

    def __init__(self, file_path: Path | str, sep: str = ','):
        file_path = Path(file_path)
        self._file = open(file_path, 'a')
        self._recorder = _Recorder(self._file, sep)
        control_loop.add_listener(self._recorder)

    def close(self) -> None:
        control_loop.remove_listener(self._recorder)
        if self._file is not None:
            self._file.close()
            self._file = None

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return exc_type is None


class _Recorder(control_loop.RegistersListener):

    def __init__(self, file, sep: str):
        self._print = partial(print, file=file, sep=sep)
        self._flush = file.flush
        self._first_update = True
        self._registers: Sequence[str] = ()

    def update(self, register_values: Dict[str, int | float | str | bool]) -> None:
        now: str = datetime.now().strftime(control_loop.DATE_FORMAT)
        control_status: JSONDict = control_loop.get_control_status()
        price: Price = control_loop.get_cur_price()
        charger: ChargerStatus = control_loop.get_cur_car_charger()

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
            self._print(*header)

        row: List[int | float | str | bool] = [
            now,
            str(json_dict(control_status['battery'])['mode']),
            str(json_dict(control_status['battery'])['policy']),
            str(json_dict(control_status['inverter'])['mode']),
            str(json_dict(control_status['inverter'])['policy']),
        ]
        row.extend(register_values[key] for key in self._registers)
        row.append(price.buy_price)
        row.append(price.feed_in_price)
        row.append(price.renewables)
        row.append(price.tariff_period)
        row.append(price.tariff_season)
        row.append(price.tariff_demand_window)
        row.append(charger.voltage)
        row.append(charger.current)
        row.append(charger.power)
        self._print(*row)
        self._flush()
