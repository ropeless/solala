"""Tests for Tesla Wall Connector lifetime energy reporting."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx

from solala.delegates.power_consumer.tesla_wall_connector.tesla_wall_connector import TeslaWallConnector


def vitals() -> dict:
    """Build a representative three-phase vitals response."""
    return {
        'grid_v': 240.0,
        'voltageA_v': 240.0, 'currentA_a': 10.0,
        'voltageB_v': 240.0, 'currentB_a': 0.0,
        'voltageC_v': 240.0, 'currentC_a': 0.0,
        'contactor_closed': True,
    }


def response(data: dict, status_code: int = 200) -> Mock:
    """Build a mock HTTP response."""
    result = Mock()
    result.json.return_value = data
    if status_code >= 400:
        result.raise_for_status.side_effect = httpx.HTTPStatusError(
            'error', request=httpx.Request('GET', 'http://tesla.example/api/1/lifetime'),
            response=httpx.Response(status_code),
        )
    return result


class TeslaLifetimeEnergyTestCase(unittest.IsolatedAsyncioTestCase):
    """Verify device-owned accumulated energy and independent response caches."""

    async def asyncSetUp(self) -> None:
        self.consumer = TeslaWallConnector('tesla.example', cache_duration=0)
        self.addAsyncCleanup(self.consumer.close)

    async def test_lifetime_energy_is_reported_in_wh(self) -> None:
        self.consumer._client.get = AsyncMock(side_effect=[
            response(vitals()), response({'energy_wh': 123456.5}),
        ])
        status = await self.consumer.get_status()
        self.assertEqual(status.accumulated_energy, 123456.5)
        self.assertEqual(status.power, 2400)
        self.assertEqual(status.current, 10)
        self.assertTrue(status.on)
        self.assertEqual(
            [call.args[0].split('/')[-1] for call in self.consumer._client.get.await_args_list],
            ['vitals', 'lifetime'],
        )

    async def test_both_endpoints_share_cache_duration_but_not_cache(self) -> None:
        await self.consumer.close()
        self.consumer = TeslaWallConnector('tesla.example', cache_duration=60)
        self.addAsyncCleanup(self.consumer.close)
        self.consumer._client.get = AsyncMock(side_effect=[
            response(vitals()), response({'energy_wh': 100}),
        ])
        statuses = await asyncio.gather(*(self.consumer.get_status() for _ in range(4)))
        self.assertEqual([status.accumulated_energy for status in statuses], [100] * 4)
        self.assertEqual(self.consumer._client.get.await_count, 2)

    async def test_new_lifetime_reading_is_used_after_cache_expiry(self) -> None:
        self.consumer._client.get = AsyncMock(side_effect=[
            response(vitals()), response({'energy_wh': 100}),
            response(vitals()), response({'energy_wh': 125}),
        ])
        self.assertEqual((await self.consumer.get_status()).accumulated_energy, 100)
        self.assertEqual((await self.consumer.get_status()).accumulated_energy, 125)

    async def test_new_instance_reads_existing_lifetime_total(self) -> None:
        self.consumer._client.get = AsyncMock(side_effect=[
            response(vitals()), response({'energy_wh': 500000}),
        ])
        self.assertEqual((await self.consumer.get_status()).accumulated_energy, 500000)

    async def test_missing_or_invalid_energy_returns_none(self) -> None:
        for lifetime in ({}, {'energy_wh': -1}, {'energy_wh': float('nan')},
                         {'energy_wh': float('inf')}, {'energy_wh': True},
                         {'energy_wh': 'invalid'}):
            with self.subTest(lifetime=lifetime):
                self.consumer._client.get = AsyncMock(side_effect=[
                    response(vitals()), response(lifetime),
                ])
                if 'energy_wh' not in lifetime or isinstance(lifetime.get('energy_wh'), str):
                    with self.assertLogs('solala', level='WARNING') as captured:
                        self.assertIsNone((await self.consumer.get_status()).accumulated_energy)
                    self.assertIn('lifetime energy unavailable', captured.output[0])
                else:
                    self.assertIsNone((await self.consumer.get_status()).accumulated_energy)

    async def test_lifetime_http_failure_preserves_vitals(self) -> None:
        self.consumer._client.get = AsyncMock(side_effect=[
            response(vitals()), httpx.ConnectError('lifetime unavailable'),
        ])
        with self.assertLogs('solala', level='WARNING') as captured:
            status = await self.consumer.get_status()
        self.assertIn('ConnectError', captured.output[0])
        self.assertEqual(status.power, 2400)
        self.assertIsNone(status.accumulated_energy)

    async def test_lifetime_http_status_failure_preserves_vitals(self) -> None:
        self.consumer._client.get = AsyncMock(side_effect=[
            response(vitals()), response({}, status_code=503),
        ])
        with self.assertLogs('solala', level='WARNING') as captured:
            self.assertIsNone((await self.consumer.get_status()).accumulated_energy)
        self.assertIn('HTTPStatusError', captured.output[0])

    async def test_vitals_failure_propagates(self) -> None:
        self.consumer._client.get = AsyncMock(side_effect=httpx.ConnectError('offline'))
        with self.assertRaises(httpx.ConnectError):
            await self.consumer.get_status()
        self.consumer._client.get.assert_awaited_once()

    async def test_lifetime_failure_is_retried(self) -> None:
        self.consumer._client.get = AsyncMock(side_effect=[
            response(vitals()), httpx.ConnectError('offline'),
            response(vitals()), response({'energy_wh': 900}),
        ])
        with self.assertLogs('solala', level='WARNING') as captured:
            self.assertIsNone((await self.consumer.get_status()).accumulated_energy)
        self.assertIn('ConnectError', captured.output[0])
        self.assertEqual((await self.consumer.get_status()).accumulated_energy, 900)

    async def test_no_background_task_created(self) -> None:
        self.consumer._client.get = AsyncMock(side_effect=[
            response(vitals()), response({'energy_wh': 42}),
        ])
        with patch('asyncio.create_task', side_effect=AssertionError('background task created')):
            self.assertEqual((await self.consumer.get_status()).accumulated_energy, 42)

    async def test_default_cache_duration_is_tenth_second(self) -> None:
        with patch('solala.delegates.power_consumer.tesla_wall_connector.tesla_wall_connector.AsyncMicroCache') as cache:
            other = TeslaWallConnector('tesla.example')
            self.addAsyncCleanup(other.close)
            self.assertEqual(cache.call_count, 2)
            self.assertEqual([call.args[1] for call in cache.call_args_list], [0.1, 0.1])


if __name__ == '__main__':
    unittest.main()
