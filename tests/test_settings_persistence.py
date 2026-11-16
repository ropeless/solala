import asyncio
import importlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

control_loop = importlib.import_module('solala.control_loop.control_loop')


class SettingsPersistenceTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify settings saves are serialized without holding state locks for file I/O.
    """

    async def asyncSetUp(self) -> None:
        self.state = control_loop._ControlState()
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.state.settings_persistence.path = Path(self.tempdir.name) / 'settings.json'
        state_patch = patch.object(control_loop, '_CONTROL_STATE', self.state)
        state_patch.start()
        self.addCleanup(state_patch.stop)

    async def test_concurrent_saves_write_latest_snapshot(self) -> None:
        version = 1
        snapshots: list[int] = []

        def get_settings(state: object) -> SimpleNamespace:
            self.assertTrue(self.state.settings_persistence.lock._owner is asyncio.current_task())
            self.assertTrue(self.state.connections.lock._owner is not None)
            self.assertTrue(self.state.control.lock._owner is not None)
            snapshots.append(version)
            return SimpleNamespace(model_dump_json=lambda: str(version))

        with patch.object(control_loop, '_get_settings', side_effect=get_settings):
            async with self.state.settings_persistence.lock:
                first = asyncio.create_task(control_loop._save_settings())
                await asyncio.sleep(0)
                version = 2
                second = asyncio.create_task(control_loop._save_settings())
                await asyncio.sleep(0)
                self.assertFalse(self.state.settings_persistence.path.exists())
            await asyncio.gather(first, second)

        self.assertEqual(snapshots, [2, 2])
        self.assertEqual(self.state.settings_persistence.path.read_text().strip(), '2')

    async def test_persistence_lock_enforces_lock_order(self) -> None:
        with self.assertRaisesRegex(RuntimeError, 'Lock order violation'):
            async with self.state.connections.lock:
                async with self.state.settings_persistence.lock:
                    self.fail('Reverse lock acquisition should not succeed')

    async def test_save_does_not_hold_state_locks_during_write(self) -> None:
        original_open = open

        def checked_open(*args: object, **kwargs: object):
            self.assertTrue(self.state.settings_persistence.lock._owner is asyncio.current_task())
            self.assertFalse(self.state.connections.lock._owner is not None)
            self.assertFalse(self.state.control.lock._owner is not None)
            return original_open(*args, **kwargs)

        settings = SimpleNamespace(model_dump_json=lambda: '{"test":true}')
        with patch.object(control_loop, '_get_settings', return_value=settings):
            with patch('builtins.open', side_effect=checked_open):
                await control_loop._save_settings()

        self.assertEqual(self.state.settings_persistence.path.read_text().strip(), '{"test":true}')


if __name__ == '__main__':
    unittest.main()
