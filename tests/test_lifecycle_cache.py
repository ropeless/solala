import asyncio
import unittest
from unittest.mock import Mock, patch

from solala.utils.lifecycle_cache import (
    LifecycleCache,
    LifecycleState,
    ErrorReturn,
    NoResult,
    error,
    interim,
    valid,
    NO_VALUE,
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
            log_error=self.error_log,
            log_info=self.info_log,
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
        self.assertEqual(cache._state, ErrorReturn.state)
        self.assertEqual(self.calls, 1)

    async def test_initial_error_without_default_raises_no_result(self) -> None:
        self.results = [error('unavailable')]
        cache = self.make_cache(has_default=False)
        with self.assertRaises(NoResult):
            await cache()
        self.assertEqual(cache._state, ErrorReturn.state)

    async def test_expiry_is_set_when_success_logging_is_disabled(self) -> None:
        for result_factory, expected_lifetime in ((valid, 30), (interim, 30)):
            with self.subTest(result_factory=result_factory):
                async def wrapped():
                    return result_factory(12)

                cache = LifecycleCache(
                    wrapped, old=30, young=10, retry=5,
                    log_error=self.error_log, log_info=self.info_log,
                    valid_message='', interim_message='',
                )
                self.assertEqual(await cache(), 12)
                self.assertEqual(cache._invalid_timestamp, self.now + expected_lifetime)
                self.info_log.assert_not_called()

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
            default=7, log_error=self.error_log, log_info=self.info_log,
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
        self.assertEqual(cache._state, ErrorReturn.state)
        self.assertEqual(self.calls, 2)

    async def test_valid_old_without_default_cannot_return_expired_value(self) -> None:
        self.results = [valid(12), error('unavailable')]
        cache = self.make_cache(has_default=False)
        self.assertEqual(await cache(), 12)
        self.now += 30
        with self.assertRaises(NoResult):
            await cache()
        self.assertEqual(cache._state, ErrorReturn.state)

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

    async def test_interim_until_time_controls_refresh_not_expiry(self) -> None:
        from datetime import UTC, datetime

        self.results = [interim(12, until_time=datetime.now(UTC)), error('unavailable')]
        cache = self.make_cache(default=7)
        with patch('solala.utils.lifecycle_cache._datetime_to_monotonic', return_value=112.0) as convert:
            self.assertEqual(await cache(), 12)
            convert.assert_called_once()
            self.assertEqual(cache._refresh_timestamp, 112.0)
        self.assertEqual(cache._invalid_timestamp, 130.0)
        self.now = 111.0
        self.assertEqual(await cache(), 12)
        self.assertEqual(self.calls, 1)
        self.now = 112.0
        self.assertEqual(await cache(), 12)
        self.assertEqual(self.calls, 2)
        self.now = 130.0
        self.results = [error('still unavailable')]
        self.assertEqual(await cache(), 7)

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
        self.assertEqual(await cache._refresh_and_get(), 12)
        self.now += 5
        self.assertEqual(await cache(), 12)
        self.now += 20
        self.assertEqual(await cache(), 7)
        self.assertEqual(cache._state, ErrorReturn.state)
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
            log_error=self.error_log, log_info=self.info_log,
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
            default=7, log_error=self.error_log, log_info=self.info_log,
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
            default=7, log_error=self.error_log, log_info=self.info_log,
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

    async def test_foreground_exception_propagates_and_allows_retry(self) -> None:
        async def wrapped():
            self.calls += 1
            if self.calls == 1:
                raise ValueError('unexpected failure')
            return valid(42)

        cache = LifecycleCache(
            wrapped, old=30, young=10, retry=5,
            default=7, log_error=self.error_log, log_info=self.info_log,
        )
        with self.assertRaisesRegex(ValueError, 'unexpected failure'):
            await cache()
        await asyncio.sleep(0)  # Allow the task completion callback to run.
        self.assertIsNone(cache._task)
        self.assertIs(cache._state, LifecycleState.INITIAL)
        self.assertEqual(cache._timestamp, 100.0)
        self.assertEqual(cache._invalid_timestamp, 100.0)
        self.assertEqual(cache._cache, 7)
        self.error_log.assert_called_once()
        self.assertIn('ValueError: unexpected failure', self.error_log.call_args.args[0])
        self.assertEqual(await cache(), 42)
        self.assertEqual(self.calls, 2)

    async def test_background_exception_is_logged_and_cache_preserved(self) -> None:
        started = asyncio.Event()

        async def wrapped():
            self.calls += 1
            if self.calls == 1:
                return valid(12)
            started.set()
            raise RuntimeError('background failure')

        cache = LifecycleCache(
            wrapped, old=30, young=10, retry=5,
            default=7, log_error=self.error_log, log_info=self.info_log,
        )
        self.assertEqual(await cache(), 12)
        timestamp = cache._timestamp
        invalid_timestamp = cache._invalid_timestamp
        self.now += 10
        self.assertEqual(await cache(), 12)
        await asyncio.wait_for(started.wait(), timeout=1)
        await asyncio.sleep(0)  # Allow the completion callback to run.
        self.assertIsNone(cache._task)
        self.assertEqual(cache._state, LifecycleState.VALID)
        self.assertEqual(cache._timestamp, timestamp)
        self.assertEqual(cache._invalid_timestamp, invalid_timestamp)
        self.assertEqual(cache._cache, 12)
        self.error_log.assert_called_once()
        self.assertIn('RuntimeError: background failure', self.error_log.call_args.args[0])

    async def test_expired_value_not_restored_after_exception(self) -> None:
        async def wrapped():
            self.calls += 1
            if self.calls == 1:
                return valid(12)
            if self.calls == 2:
                raise ValueError('refresh failed')
            return valid(42)

        cache = LifecycleCache(
            wrapped, old=30, young=10, retry=5,
            default=7, log_error=self.error_log, log_info=self.info_log,
        )
        self.assertEqual(await cache(), 12)
        timestamp = cache._timestamp
        self.now += 30
        with self.assertRaisesRegex(ValueError, 'refresh failed'):
            await cache()
        await asyncio.sleep(0)
        self.assertIsNone(cache._task)
        self.assertEqual(cache._cache, 7)
        self.assertEqual(cache._state, LifecycleState.VALID)
        self.assertEqual(cache._timestamp, timestamp)
        self.assertEqual(await cache(), 42)
        self.assertEqual(self.calls, 3)

    async def test_concurrent_foreground_callers_receive_same_exception(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def wrapped():
            self.calls += 1
            started.set()
            await release.wait()
            raise ValueError('shared failure')

        cache = LifecycleCache(
            wrapped, old=30, young=10, retry=5,
            log_error=self.error_log, log_info=self.info_log,
        )
        callers = [asyncio.create_task(cache()) for _ in range(3)]
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            await asyncio.sleep(0)
            self.assertEqual(self.calls, 1)
        finally:
            release.set()
        results = await asyncio.wait_for(
            asyncio.gather(*callers, return_exceptions=True), timeout=1,
        )
        self.assertTrue(all(isinstance(result, ValueError) for result in results))
        self.assertTrue(all(str(result) == 'shared failure' for result in results))
        await asyncio.sleep(0)
        self.assertIsNone(cache._task)
        self.assertEqual(self.calls, 1)
        self.error_log.assert_called_once()

    async def test_cancelling_one_caller_preserves_shared_refresh(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def wrapped():
            self.calls += 1
            started.set()
            await release.wait()
            return valid(42)

        cache = LifecycleCache(
            wrapped, old=30, young=10, retry=5,
            log_error=self.error_log, log_info=self.info_log,
        )
        callers = [asyncio.create_task(cache()) for _ in range(3)]
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            await asyncio.sleep(0)  # Let the remaining callers join the refresh.
            callers[0].cancel()
            with self.assertRaises(asyncio.CancelledError):
                await callers[0]
            self.assertEqual(self.calls, 1)
            self.assertIsNotNone(cache._task)
            self.assertFalse(cache._task.done())
        finally:
            release.set()
        results = await asyncio.wait_for(asyncio.gather(*callers[1:]), timeout=1)
        self.assertEqual(results, [42, 42])
        await asyncio.sleep(0)
        self.assertIsNone(cache._task)
        self.assertEqual(self.calls, 1)

    async def test_cancelling_only_caller_does_not_cancel_refresh(self) -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def wrapped():
            self.calls += 1
            started.set()
            await release.wait()
            return valid(42)

        cache = LifecycleCache(
            wrapped, old=30, young=10, retry=5,
            log_error=self.error_log, log_info=self.info_log,
        )
        caller = asyncio.create_task(cache())
        try:
            await asyncio.wait_for(started.wait(), timeout=1)
            caller.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await caller
            self.assertIsNotNone(cache._task)
            self.assertFalse(cache._task.done())
        finally:
            release.set()
        await asyncio.wait_for(cache._task, timeout=1)
        await asyncio.sleep(0)
        self.assertIsNone(cache._task)
        self.assertEqual(cache._state, LifecycleState.VALID)
        self.assertEqual(await cache(), 42)
        self.assertEqual(self.calls, 1)

    async def test_valid_none_is_cached(self) -> None:
        async def wrapped():
            self.calls += 1
            return valid(None)

        cache = LifecycleCache(
            wrapped, old=30, young=10, retry=5,
            log_error=self.error_log, log_info=self.info_log,
        )
        self.assertIsNone(await cache())
        self.assertIsNone(await cache())
        self.assertEqual(self.calls, 1)
        self.assertEqual(cache._state, LifecycleState.VALID)

    async def test_interim_none_is_cached(self) -> None:
        async def wrapped():
            self.calls += 1
            return interim(None)

        cache = LifecycleCache(
            wrapped, old=30, young=10, retry=5,
            log_error=self.error_log, log_info=self.info_log,
        )
        self.assertIsNone(await cache())
        self.assertIsNone(await cache())
        self.assertEqual(self.calls, 1)
        self.assertEqual(cache._state, LifecycleState.INTERIM)

    async def test_default_none_is_returned_on_error(self) -> None:
        async def wrapped():
            self.calls += 1
            return error('unavailable')

        cache = LifecycleCache(
            wrapped, old=30, young=10, retry=5, default=None,
            log_error=self.error_log, log_info=self.info_log,
        )
        self.assertIsNone(await cache())
        self.assertEqual(cache._state, ErrorReturn.state)
        self.assertEqual(self.calls, 1)

    async def test_non_reserved_sentinel_can_be_cached(self) -> None:
        from solala.utils.sentinel import Sentinel

        for result_factory in (valid, interim):
            with self.subTest(result_factory=result_factory):
                marker = Sentinel('allowed')

                async def wrapped():
                    return result_factory(marker)

                cache = LifecycleCache(
                    wrapped, old=30, young=10, retry=5,
                    log_error=self.error_log, log_info=self.info_log,
                )
                self.assertIs(await cache(), marker)
                self.assertIs(await cache(), marker)

    async def test_reserved_no_value_is_rejected_without_state_change(self) -> None:
        for result_factory in (valid, interim):
            with self.subTest(result_factory=result_factory):
                async def wrapped():
                    return result_factory(NO_VALUE)

                cache = LifecycleCache(
                    wrapped, old=30, young=10, retry=5,
                    log_error=self.error_log, log_info=self.info_log,
                )
                with self.assertRaisesRegex(ValueError, 'not a valid function return value'):
                    await cache()
                await asyncio.sleep(0)
                self.assertIsNone(cache._task)
                self.assertIs(cache.state, LifecycleState.INITIAL)
                self.assertEqual(cache.timestamp, 100.0)
                self.assertEqual(cache._invalid_timestamp, 100.0)
                self.assertIs(cache._cache, NO_VALUE)


if __name__ == '__main__':
    unittest.main()
