"""Contract tests for Tesla Wall Connector energy monitoring (issue #35)."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from solala.delegates.power_consumer.tesla_wall_connector.tesla_wall_connector import TeslaWallConnector


def vitals(energy: float = 0, seconds: float = 0, **overrides: object) -> dict:
    """Build a representative three-phase Tesla vitals response."""
    data = {
        'grid_v': 240.0,
        'voltageA_v': 240.0,
        'voltageB_v': 240.0,
        'voltageC_v': 240.0,
        'currentA_a': 10.0,
        'currentB_a': 0.0,
        'currentC_a': 0.0,
        'contactor_closed': True,
        'vehicle_connected': True,
        'session_energy_wh': energy,
        'session_s': seconds,
    }
    data.update(overrides)
    return data


class TeslaEnergyTestCase(unittest.IsolatedAsyncioTestCase):
    """Specify cumulative energy and the monitoring task lifecycle."""

    async def asyncSetUp(self) -> None:
        self.consumer = TeslaWallConnector('tesla.example', cache_duration=0)
        self.consumer._client.get = AsyncMock()
        self.addAsyncCleanup(self.consumer.close)

    def readings(self, *values: dict | Exception) -> None:
        """Supply successive uncached vitals observations."""
        results = []
        for value in values:
            if isinstance(value, Exception):
                results.append(value)
            else:
                results.append(Mock(json=Mock(return_value=value)))
        self.consumer._client.get.side_effect = results

    async def test_constructor_does_not_start_task(self) -> None:
        """Construction is safe outside a running event loop."""
        with patch('asyncio.create_task', side_effect=AssertionError('task created')):
            consumer = TeslaWallConnector('tesla.example')
        await consumer.close()

    async def test_first_status_starts_monitor_and_reports_existing_session(self) -> None:
        self.readings(vitals(120, 30))
        status = await self.consumer.get_status()
        self.assertEqual(status.accumulated_energy, 120)
        self.assertIsNotNone(self.consumer._energy_task)
        self.assertFalse(self.consumer._energy_task.done())

    async def test_session_progress_and_duplicate_observation(self) -> None:
        self.readings(vitals(100, 10), vitals(150, 20), vitals(150, 20))
        totals = [(await self.consumer.get_status()).accumulated_energy for _ in range(3)]
        self.assertEqual(totals, [100, 150, 150])

    async def test_energy_reset_starts_new_session(self) -> None:
        self.readings(vitals(100, 10), vitals(160, 20), vitals(15, 1), vitals(35, 5))
        totals = [(await self.consumer.get_status()).accumulated_energy for _ in range(4)]
        self.assertEqual(totals, [100, 160, 175, 195])

    async def test_session_timer_reset_even_if_energy_increases(self) -> None:
        self.readings(vitals(100, 50), vitals(120, 60), vitals(140, 2))
        totals = [(await self.consumer.get_status()).accumulated_energy for _ in range(3)]
        self.assertEqual(totals, [100, 120, 260])

    async def test_disconnected_observation_does_not_erase_energy(self) -> None:
        self.readings(vitals(50, 10), vitals(50, 10, vehicle_connected=False,
                                            contactor_closed=False), vitals(10, 2))
        totals = [(await self.consumer.get_status()).accumulated_energy for _ in range(3)]
        self.assertEqual(totals, [50, 50, 60])

    async def test_invalid_session_values_preserve_accumulator(self) -> None:
        self.readings(vitals(50, 10), vitals(-1, 20), vitals(float('nan'), 25),
                      vitals(70, 30))
        self.assertEqual((await self.consumer.get_status()).accumulated_energy, 50)
        for _ in range(2):
            try:
                await self.consumer.get_status()
            except (ValueError, TypeError):
                pass
        self.assertEqual((await self.consumer.get_status()).accumulated_energy, 70)

    async def test_missing_session_values_preserve_accumulator(self) -> None:
        missing = vitals(0, 0)
        del missing['session_energy_wh']
        self.readings(vitals(50, 10), missing, vitals(70, 30))
        self.assertEqual((await self.consumer.get_status()).accumulated_energy, 50)
        try:
            await self.consumer.get_status()
        except (KeyError, ValueError, TypeError):
            pass
        self.assertEqual((await self.consumer.get_status()).accumulated_energy, 70)

    async def test_failed_fetch_preserves_energy_and_recovers(self) -> None:
        self.readings(vitals(50, 10), TimeoutError('offline'), vitals(80, 20))
        self.assertEqual((await self.consumer.get_status()).accumulated_energy, 50)
        with self.assertRaises(TimeoutError):
            await self.consumer.get_status()
        self.assertEqual((await self.consumer.get_status()).accumulated_energy, 80)

    async def test_check_energy_and_status_do_not_double_count(self) -> None:
        self.readings(vitals(90, 10), vitals(90, 10), vitals(110, 20))
        await self.consumer.check_energy()
        self.assertEqual((await self.consumer.get_status()).accumulated_energy, 90)
        self.assertEqual((await self.consumer.get_status()).accumulated_energy, 110)

    async def test_concurrent_status_checks_count_fresh_reading_once(self) -> None:
        self.readings(vitals(100, 10))
        # A long cache duration forces concurrent requests to share one observation.
        await self.consumer.close()
        self.consumer = TeslaWallConnector('tesla.example', cache_duration=60)
        self.consumer._client.get = AsyncMock(
            return_value=Mock(json=Mock(return_value=vitals(100, 10)))
        )
        statuses = await asyncio.gather(*(self.consumer.get_status() for _ in range(5)))
        self.assertEqual([s.accumulated_energy for s in statuses], [100] * 5)
        self.consumer._client.get.assert_awaited_once()

    async def test_monitor_waits_before_first_periodic_check(self) -> None:
        self.readings(vitals(50, 10))
        await self.consumer.get_status()
        # The monitor must not immediately issue a second device request.
        await asyncio.sleep(0)
        self.consumer._client.get.assert_awaited_once()

    async def test_monitor_survives_transient_failure(self) -> None:
        self.readings(vitals(10, 1), TimeoutError('offline'), vitals(20, 2))
        await self.consumer.get_status()
        # Triggering subsequent checks must not leave the monitor permanently stopped.
        with self.assertRaises(TimeoutError):
            await self.consumer.check_energy()
        self.assertEqual((await self.consumer.get_status()).accumulated_energy, 20)
        self.assertFalse(self.consumer._energy_task.done())

    async def test_background_monitor_updates_energy_without_status_calls(self) -> None:
        """The monitor continues sampling when no caller requests status."""
        await self.consumer.close()
        self.consumer = TeslaWallConnector(
            'tesla.example', cache_duration=0, energy_check_cadence=0.005,
        )
        observed = asyncio.Event()
        calls = 0

        async def fetch(_url: str) -> Mock:
            nonlocal calls
            calls += 1
            if calls >= 2:
                observed.set()
            return Mock(json=Mock(return_value=vitals(calls * 10, calls)))

        self.consumer._client.get = AsyncMock(side_effect=fetch)
        self.assertEqual((await self.consumer.get_status()).accumulated_energy, 10)
        await asyncio.wait_for(observed.wait(), timeout=1)
        self.assertGreaterEqual(self.consumer._accumulated_energy, 20)

    async def test_background_monitor_recovers_from_http_failure(self) -> None:
        """A failed scheduled check does not prevent later scheduled checks."""
        await self.consumer.close()
        self.consumer = TeslaWallConnector(
            'tesla.example', cache_duration=0, energy_check_cadence=0.005,
        )
        recovered = asyncio.Event()
        calls = 0

        async def fetch(_url: str) -> Mock:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise TimeoutError('offline')
            if calls >= 3:
                recovered.set()
            return Mock(json=Mock(return_value=vitals(calls * 10, calls)))

        self.consumer._client.get = AsyncMock(side_effect=fetch)
        await self.consumer.get_status()
        await asyncio.wait_for(recovered.wait(), timeout=1)
        self.assertGreaterEqual(self.consumer._accumulated_energy, 30)
        self.assertFalse(self.consumer._energy_task.done())

    async def test_invalid_monitor_interval_rejected(self) -> None:
        """The cadence must not allow a busy loop."""
        for cadence in (0, -1, float('nan'), float('inf')):
            with self.subTest(cadence=cadence):
                with self.assertRaises(ValueError):
                    TeslaWallConnector('tesla.example', energy_check_cadence=cadence)

    async def test_close_cancels_monitor_and_is_idempotent(self) -> None:
        self.readings(vitals(10, 1))
        await self.consumer.get_status()
        task = self.consumer._energy_task
        await self.consumer.close()
        self.assertTrue(task.done())
        self.assertTrue(task.cancelled())
        self.assertTrue(self.consumer._client.is_closed)
        await self.consumer.close()

    async def test_close_prevents_monitor_restart(self) -> None:
        self.readings(vitals(10, 1))
        await self.consumer.get_status()
        await self.consumer.close()
        task = self.consumer._energy_task
        try:
            await self.consumer.get_status()
        except (RuntimeError, httpx.HTTPError):
            pass
        self.assertIs(self.consumer._energy_task, task)
        self.assertTrue(task.done())


if __name__ == '__main__':
    unittest.main()
