import asyncio
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from functools import partial

import httpx

from solala.delegates.power_consumer.power_consumer import PowerConsumer, ConsumerStatus
from solala.logger import LOGGER
from solala.register import check_type, RegisterType, AsyncCallRegister, RegisterValue, check_value
from solala.register_bank import RegisterBank
from solala.utils.json_extras import JSONDict, json_dict, json_num, json_bool
from solala.utils.micro_cache import AsyncMicroCache


class TeslaWallConnector(PowerConsumer):
    """
    Power consumer implementation for a Tesla Wall Connector.

    Reads the connector's local HTTP API to retrieve electrical measurements,
    expose the available data as registers, and estimate accumulated charging energy.

    Accumulated energy is measured in Wh and is estimated from successive
    `session_energy_wh` readings. A decrease in session energy or `session_s`
    indicates a new charging session; the new session's energy is then added to
    the running total. The first observation includes energy already delivered
    in the current session. The total is maintained in memory and resets when
    the connector instance is recreated. Charging sessions that start and finish
    entirely between observations cannot always be recovered.

    The first call to `get_status()` starts a background energy monitor. The
    monitor waits `energy_check_cadence` before each check and runs independently of status
    requests. Every `get_status()` call also checks the latest energy reading.
    Concurrent and cached reads do not count the same observation twice.
    Temporary device communication failures do not stop the monitor or discard
    accumulated energy. Missing or invalid session measurements leave the last
    valid energy state unchanged.

    Construction does not require a running event loop. `close()` cancels and
    awaits the monitor before closing the HTTP client, and prevents the monitor
    from restarting. Closing more than once is safe.

    Important: active power is estimated from phase voltage and current
    measurements, assuming a power factor of one.

    """

    def __init__(
            self,
            host: str,
            mac_address: str = '',
            cache_duration: float = 0.01,
            energy_check_cadence: float = 60,
    ):
        """
        Initialise the connection to a Tesla Wall Connector.

        Args:
            host: Hostname or IP address of the connector.
            mac_address: Optional MAC address included in connection information.
            cache_duration: How long to cache device vitals, in seconds. Fresh
                observations update the accumulated energy at most once.
                The default value is 0.01 seconds.
            energy_check_cadence: how often to attempt reading the device to maintain
                the accumulated energy record.
        """
        if not math.isfinite(energy_check_cadence) or energy_check_cadence <= 0:
            raise ValueError('energy_check_cadence must be positive and finite')
        super().__init__(can_switch=False)

        # noinspection HttpUrlsUsage
        self._api = f'http://{host}/api/1/'
        self._client = httpx.AsyncClient()
        self._connection_info = {
            'connection': 'Tesla Wall Connector',
            'host': host,
        }
        if mac_address != '':
            self._connection_info['mac_address'] = mac_address

        self._energy_check_cadence = energy_check_cadence
        self._energy_task: asyncio.Task[None] | None = None
        self._closed = False
        self._accumulated_energy = 0.0
        self._last_session_energy: float | None = None
        self._last_session_seconds: float | None = None

        # Cache fresh vitals; each fetch updates energy at most once.
        self._cache: Callable[[], Awaitable[JSONDict]] = AsyncMicroCache(self.__get_vitals, cache_duration)

        # Created on first call to `get_registers`
        self._register_bank: RegisterBank | None = None
        self._register_bank_lock = asyncio.Lock()

    async def get_registers(self) -> RegisterBank:
        reg_bank = self._register_bank
        if reg_bank is None:
            async with self._register_bank_lock:
                reg_bank = self._register_bank
                if reg_bank is None:
                    reg_bank = RegisterBank({
                        key: AsyncCallRegister(partial(self._get_register_value, key), reg_type)
                        async for key, reg_type in self._get_register_keys()
                    })
                    self._register_bank = reg_bank
        return reg_bank

    async def get_status(self) -> ConsumerStatus:
        """
        Return current electrical measurements and accumulated charging energy.

        Starts periodic energy monitoring on first use and checks energy on
        every call. The accumulated energy is the in-memory total in Wh.

        Returns:
            The latest consumer status, including accumulated energy.
        """
        if self._closed:
            raise RuntimeError('Tesla Wall Connector is closed')
        if self._energy_task is None:
            self._energy_task = asyncio.create_task(self._monitor_energy())
        data: JSONDict = await self.check_energy()
        voltage: float = json_num(data['grid_v'])
        apparent_power = (
                json_num(data['currentA_a']) * json_num(data['voltageA_v'])
                + json_num(data['currentB_a']) * json_num(data['voltageB_v'])
                + json_num(data['currentC_a']) * json_num(data['voltageC_v'])
        )
        # Equivalent single phase current, assuming  phase-to-neutral voltage measurement
        # We are assuming a power factor or 1 (purely resistive load).
        current: float = apparent_power / voltage
        on: bool = json_bool(data['contactor_closed'])

        return ConsumerStatus(
            voltage=voltage,
            current=current,
            power=voltage * current,  # assumes a pure resistive load
            on=on,
            accumulated_energy=self._accumulated_energy,
        )

    async def check_energy(self) -> JSONDict:
        """
        Check current vitals and update accumulated energy on fresh readings.

        Returns:
            The latest cached or freshly fetched device vitals.
        """
        if self._closed:
            raise RuntimeError('Tesla Wall Connector is closed')
        return await self._cache()

    def _update_energy(self, data: JSONDict) -> None:
        """
        Accumulate energy from a valid session observation.

        Args:
            data: The latest vitals response.
        """
        try:
            energy = json_num(data['session_energy_wh'])
            seconds = json_num(data['session_s'])
        except (KeyError, TypeError, ValueError):
            return
        if not (math.isfinite(energy) and math.isfinite(seconds)
                and energy >= 0 and seconds >= 0):
            return

        previous_energy = self._last_session_energy
        previous_seconds = self._last_session_seconds
        if previous_energy is None or previous_seconds is None:
            delta = energy
        elif energy < previous_energy or seconds < previous_seconds:
            delta = energy
        else:
            delta = energy - previous_energy

        self._accumulated_energy += delta
        self._last_session_energy = energy
        self._last_session_seconds = seconds

    async def _monitor_energy(self) -> None:
        """Check energy periodically until the monitor is cancelled."""
        while True:
            await asyncio.sleep(self._energy_check_cadence)
            try:
                await self.check_energy()
            except asyncio.CancelledError:
                raise
            except Exception as err:
                LOGGER.warning(f'{self.__class__.__name__} energy monitoring failed: {err!r}')

    def get_connection_info(self) -> JSONDict:
        return self._connection_info

    async def close(self) -> None:
        """
        Stop energy monitoring and close the HTTP connection.

        Cancels and awaits the background monitor before closing the client.
        Repeated calls are safe, and monitoring cannot restart after closing.
        """
        if self._closed:
            return
        self._closed = True
        task = self._energy_task
        try:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        finally:
            await self._client.aclose()

    async def _get_switch(self) -> bool:
        return (await self.get_status()).on

    async def _set_switch(self, on: bool) -> None:
        raise NotImplementedError('Tesla Wall Connector does not support switching')

    async def _get_register_keys(self) -> AsyncIterator[tuple[str, RegisterType]]:
        """
        Get the vitals keys supported by the register system.

        Returns:
            An asynchronous iterator of register keys and their corresponding
            register types. Values with unsupported types are skipped.
        """
        device_status: JSONDict = await self._cache()
        for key, value in device_status.items():
            try:
                reg_type: RegisterType = check_type(type(value))
            except TypeError:
                continue
            yield key, reg_type

    async def _get_register_value(self, key: str) -> RegisterValue:
        """
        Get the current value of a connector vitals register.

        Args:
            key: Name of the vitals field to retrieve.

        Returns:
            The register value converted to a supported register type.
        """
        json: JSONDict = await self._cache()
        value = json[key]
        return check_value(value)

    async def __get_vitals(self) -> JSONDict:
        """
        Retrieve the connector's vitals from its local HTTP API.

        Returns:
            The vitals response as a JSON dictionary.

        Raises:
            Exception: If the HTTP request or response processing fails.
        """
        url = self._api + 'vitals'
        response = await self._client.get(url)
        data = json_dict(response.json())
        self._update_energy(data)
        return data
