import asyncio
import unittest
from unittest.mock import Mock, patch

from solala.utils.lifecycle_cache import (
    LifecycleCache,
    LifecycleState,
    NoResult,
    error,
    interim,
    valid,
)


class LifecycleCacheCallTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Test __call__ against the documented lifecycle and expiration contract.
    """

    def setUp(self) -> None:
        self.now = 100.0
        self.clock = patch('solala.utils.lifecycle_cache.monotonic', side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.error_log = Mock()
        self.info_log = Mock()
        self.calls = 0
        self.results = []

    def make_cache(self, *, default=None, has_default=True) -> LifecycleCache[int]:
        async def wrapped():
            self.calls += 1
            return self.results.pop(0)

        options = {'default': default} if has_default else {}
        return LifecycleCache(
            wrapped,
            old=30,
            young=10,
            retry=5,
            error_log=self.error_log,
            info_log=self.info_log,
            **options,
        )

    async def test_initial_awaits_valid_result(self) -> None:
        self.results = [valid(12)]
        cache = self.make_cache(has_default=False)
        self.assertEqual(await cache(), 12)
        self.assertEqual(cache._state, LifecycleState.VALID)
        self.assertEqual(self.calls, 1)

    async def test_initial_error_uses_default(self) -> None:
        self.results = [error('unavailable')]
        cache = self.make_cache(default=7)
        self.assertEqual(await cache(), 7)
        self.assertEqual(cache._state, LifecycleState.ERROR)
        self.assertEqual(self.calls, 1)

    async def test_initial_error_without_default_raises_no_result(self) -> None:
        self.results = [error('unavailable')]
        cache = self.make_cache(has_default=False)
        with self.assertRaises(NoResult):
            await cache()
        self.assertEqual(cache._state, LifecycleState.ERROR)

    async def test_valid_young_returns_without_refresh(self) -> None:
        self.results = [valid(12)]
        cache = self.make_cache(default=7)
        self.assertEqual(await cache(), 12)
        self.now += 9
        self.assertEqual(await cache(), 12)
        self.assertEqual(self.calls, 1)

    async def test_valid_middle_age_starts_background_refresh(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def wrapped():
            self.calls += 1
            if self.calls == 1:
                return valid(12)
            started.set()
            await release.wait()
            return valid(15)

        cache = LifecycleCache(
            wrapped, old=30, young=10, retry=5,
            default=7, error_log=self.error_log, info_log=self.info_log,
        )
        self.assertEqual(await cache(), 12)
        self.now += 10
        self.assertEqual(await cache(), 12)
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            self.assertEqual(self.calls, 2)
        finally:
            release.set()
            if cache._task is not None:
                await cache._task
        self.assertEqual(await cache(), 15)

    async def test_valid_old_expires_and_awaits_refresh(self) -> None:
        self.results = [valid(12), error('unavailable')]
        cache = self.make_cache(default=7)
        self.assertEqual(await cache(), 12)
        self.now += 30
        self.assertEqual(await cache(), 7)
        self.assertEqual(cache._state, LifecycleState.ERROR)
        self.assertEqual(self.calls, 2)

    async def test_valid_old_without_default_cannot_return_expired_value(self) -> None:
        self.results = [valid(12), error('unavailable')]
        cache = self.make_cache(has_default=False)
        self.assertEqual(await cache(), 12)
        self.now += 30
        with self.assertRaises(NoResult):
            await cache()
        self.assertEqual(cache._state, LifecycleState.ERROR)

    async def test_interim_retries_at_retry_threshold(self) -> None:
        self.results = [interim(12), valid(15)]
        cache = self.make_cache(default=7)
        self.assertEqual(await cache(), 12)
        self.now += 4
        self.assertEqual(await cache(), 12)
        self.assertEqual(self.calls, 1)
        self.now += 1
        self.assertEqual(await cache(), 15)
        self.assertEqual(self.calls, 2)

    async def test_interim_old_expires_even_when_retry_not_due(self) -> None:
        self.results = [interim(12), error('unavailable'), error('still unavailable')]
        cache = self.make_cache(default=7)
        self.assertEqual(await cache(), 12)
        self.now += 29
        self.assertEqual(await cache(), 12)
        self.now += 1
        self.assertEqual(await cache(), 7)
        self.assertEqual(self.calls, 2)

    async def test_error_retries_only_after_retry_interval(self) -> None:
        self.results = [error('unavailable'), valid(15)]
        cache = self.make_cache(default=7)
        self.assertEqual(await cache(), 7)
        self.now += 4
        self.assertEqual(await cache(), 7)
        self.assertEqual(self.calls, 1)
        self.now += 1
        self.assertEqual(await cache(), 15)
        self.assertEqual(self.calls, 2)

    async def test_errors_do_not_extend_usable_cache_lifetime(self) -> None:
        self.results = [valid(12), error('first'), error('second'), error('third')]
        cache = self.make_cache(default=7)
        self.assertEqual(await cache(), 12)
        self.now += 5
        # Force a refresh without changing the age of the cached value.
        self.assertEqual(await cache._call_f(), 12)
        self.now += 5
        self.assertEqual(await cache(), 12)
        self.now += 20
        self.assertEqual(await cache(), 7)
        self.assertEqual(cache._state, LifecycleState.ERROR)
        self.assertEqual(self.calls, 4)

    async def test_concurrent_initial_callers_share_one_refresh(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def wrapped():
            self.calls += 1
            started.set()
            await release.wait()
            return valid(42)

        cache = LifecycleCache(
            wrapped, old=30, young=10, retry=5,
            error_log=self.error_log, info_log=self.info_log,
        )
        callers = [asyncio.create_task(cache()) for _ in range(3)]
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            # Allow all waiting callers to reach the shared task.
            await asyncio.sleep(0)
            self.assertEqual(self.calls, 1)
            self.assertTrue(all(not task.done() for task in callers))
        finally:
            release.set()
        self.assertEqual(await asyncio.wait_for(asyncio.gather(*callers), timeout=1), [42] * 3)
        self.assertEqual(self.calls, 1)

    async def test_concurrent_expired_callers_share_one_refresh(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def wrapped():
            self.calls += 1
            if self.calls == 1:
                return valid(12)
            started.set()
            await release.wait()
            return valid(42)

        cache = LifecycleCache(
            wrapped, old=30, young=10, retry=5,
            default=7, error_log=self.error_log, info_log=self.info_log,
        )
        self.assertEqual(await cache(), 12)
        self.now += 30
        callers = [asyncio.create_task(cache()) for _ in range(3)]
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            await asyncio.sleep(0)
            self.assertEqual(self.calls, 2)
            self.assertTrue(all(not task.done() for task in callers))
        finally:
            release.set()
        self.assertEqual(await asyncio.wait_for(asyncio.gather(*callers), timeout=1), [42] * 3)
        self.assertEqual(self.calls, 2)

    async def test_foreground_joins_existing_background_refresh(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def wrapped():
            self.calls += 1
            if self.calls == 1:
                return valid(12)
            started.set()
            await release.wait()
            return valid(42)

        cache = LifecycleCache(
            wrapped, old=30, young=10, retry=5,
            default=7, error_log=self.error_log, info_log=self.info_log,
        )
        self.assertEqual(await cache(), 12)
        self.now += 10
        self.assertEqual(await cache(), 12)  # Schedule background refresh.
        await asyncio.wait_for(started.wait(), timeout=1)
        self.now += 20  # Cached value is now expired.
        caller = asyncio.create_task(cache())
        try:
            await asyncio.sleep(0)
            self.assertEqual(self.calls, 2)
            self.assertFalse(caller.done())
        finally:
            release.set()
        self.assertEqual(await asyncio.wait_for(caller, timeout=1), 42)
        self.assertEqual(self.calls, 2)


if __name__ == '__main__':
    unittest.main()
