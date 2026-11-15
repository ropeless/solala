import asyncio
import unittest

from solala.server.page_session import PageSession, _SessionListener


class _BlockingListener:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False
        self.calls = 0

    async def update(self) -> None:
        self.calls += 1
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class SessionListenerTestCase(unittest.IsolatedAsyncioTestCase):

    async def test_close_cancels_and_awaits_running_update(self) -> None:
        listener = _BlockingListener()
        wrapped = _SessionListener(listener)
        task = asyncio.create_task(wrapped.update())
        await listener.started.wait()

        await wrapped.close()

        self.assertTrue(task.done())
        self.assertTrue(task.cancelled())
        self.assertTrue(listener.cancelled)

    async def test_snapshot_update_after_close_is_ignored(self) -> None:
        listener = _BlockingListener()
        wrapped = _SessionListener(listener)
        await wrapped.close()

        # Simulate a control-loop snapshot taken before unregistration.
        await wrapped.update()
        self.assertEqual(listener.calls, 0)

    async def test_multiple_running_updates_are_cancelled(self) -> None:
        listener = _BlockingListener()
        wrapped = _SessionListener(listener)
        tasks = [asyncio.create_task(wrapped.update()) for _ in range(3)]
        await asyncio.sleep(0)

        await wrapped.close()

        self.assertEqual(listener.calls, 3)
        self.assertTrue(all(task.cancelled() for task in tasks))

    async def test_registration_completing_after_session_close_is_cleaned_up(self) -> None:
        registration_started = asyncio.Event()
        allow_registration = asyncio.Event()
        registered: list[object] = []

        async def register(listener: object) -> None:
            registration_started.set()
            await allow_registration.wait()
            registered.append(listener)

        async def unregister(listener: object) -> None:
            registered.remove(listener)

        async def select_tab(_name: str) -> None:
            pass

        session = PageSession(None, select_tab)  # type: ignore[arg-type]
        listener = _BlockingListener()
        registration_task = asyncio.create_task(
            session._add_listener(listener, register, unregister)
        )
        await registration_started.wait()
        await session.close()
        allow_registration.set()

        with self.assertRaisesRegex(RuntimeError, 'closed page session'):
            await registration_task
        self.assertEqual(registered, [])
