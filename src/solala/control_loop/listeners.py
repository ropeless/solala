from abc import ABC, abstractmethod
from typing import final, Dict, List

from solala.control_loop import control_loop
from solala.power_pricer.power_pricer import Price
from solala.solar_forecaster.solar_forecaster import SolarForecast
from solala.utils.json import JSONDict


class StatusListener(ABC):
    """
    Abstract base class for status listeners.
    System status is provided to the listeners once per iteration through the control loop.
    """

    @abstractmethod
    def update(self, status_json: JSONDict) -> None:
        ...

    @final
    def update_now(self) -> None:
        """
        Manual update.
        """
        self.update(control_loop.get_status())


class RegistersListener(ABC):
    """
    Abstract base class for register listeners.
    Registers are provided to the listeners once per iteration through the control loop.
    """

    @abstractmethod
    def update(self, register_values: Dict[str, int | float | str | bool]) -> None:
        ...

    @final
    def update_now(self) -> None:
        """
        Manual update.
        """
        self.update(control_loop.get_registers())


class PriceForecastListener(ABC):
    """
    Abstract base class for price-forecast listeners.
    Prices are provided to the listeners once per iteration through the control loop.
    """

    @abstractmethod
    def update(self, price_forecast: List[Price]) -> None:
        ...

    @final
    def update_now(self) -> None:
        """
        Manual update.
        """
        self.update(control_loop.get_forecast_prices())


class SolarForecastListener(ABC):
    """
    Abstract base class for solar-forecast listeners.
    Prices are provided to the listeners once per iteration through the control loop.
    """

    @abstractmethod
    def update(self, solar_forecast: List[SolarForecast]) -> None:
        ...

    @final
    def update_now(self) -> None:
        """
        Manual update.
        """
        self.update(control_loop.get_solar_forecast())
