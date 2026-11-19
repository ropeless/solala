import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from solala.server.ui_state import UIState, UIStateStorage


TABS = {'Power', 'Solar', 'Graphs', 'Price'}
DEFAULT_TAB = 'Power'


class UIStateTestCase(unittest.TestCase):
    """
    Verify UI refresh state serialization and storage isolation.
    """

    def test_defaults(self) -> None:
        state = UIState.from_dict(None, TABS, DEFAULT_TAB)
        self.assertEqual(state, UIState(tab=DEFAULT_TAB))

    def test_explicit_default_tab(self) -> None:
        state = UIState.from_dict(None, TABS, 'Solar')
        self.assertEqual(state.tab, 'Solar')

    def test_round_trip(self) -> None:
        original = UIState(
            tab='Graphs',
            displayed_day=date(2026, 11, 18),
            graph_series={'Power': {'Solar': False, 'Battery': True}},
        )
        restored = UIState.from_dict(original.to_dict(), TABS, DEFAULT_TAB)
        self.assertEqual(restored, original)

    def test_invalid_values_fall_back_safely(self) -> None:
        state = UIState.from_dict({
            'tab': 'Removed Tab',
            'displayed_day': 'not a date',
            'graph_series': {
                'Power': {'Solar': False, 'Battery': 1, 'Grid': 'yes'},
                'Bad': ['not', 'a', 'mapping'],
            },
        }, TABS, DEFAULT_TAB)
        self.assertEqual(state.tab, DEFAULT_TAB)
        self.assertIsNone(state.displayed_day)
        self.assertEqual(state.graph_series, {'Power': {'Solar': False}})

    def test_missing_fields(self) -> None:
        self.assertEqual(UIState.from_dict({}, TABS, DEFAULT_TAB), UIState(tab=DEFAULT_TAB))

class UIStateStorageTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify browser sessionStorage access.
    """

    async def test_load_missing_state(self) -> None:
        storage = UIStateStorage(TABS, DEFAULT_TAB)
        with patch('solala.server.ui_state.ui.run_javascript', new_callable=AsyncMock) as run:
            run.return_value = None
            self.assertEqual(await storage.load(), UIState(tab=DEFAULT_TAB))
            self.assertIn('sessionStorage.getItem', run.await_args.args[0])

    async def test_load_saved_state(self) -> None:
        storage = UIStateStorage(TABS, DEFAULT_TAB)
        state = UIState(tab='Graphs', displayed_day=date(2026, 11, 18))
        with patch('solala.server.ui_state.ui.run_javascript', new_callable=AsyncMock) as run:
            run.return_value = state.to_dict()
            self.assertEqual(await storage.load(), state)

    async def test_save_serializes_state(self) -> None:
        storage = UIStateStorage(TABS, DEFAULT_TAB)
        state = UIState(tab='Solar', graph_series={'Power': {'Solar': False}})
        with patch('solala.server.ui_state.ui.run_javascript', new_callable=AsyncMock) as run:
            await storage.save(state)
            run.assert_awaited_once()
            script = run.await_args.args[0]
            self.assertIn('sessionStorage.setItem', script)
            self.assertIn('solala_ui_state', script)
            self.assertIn('Solar', script)


if __name__ == '__main__':
    unittest.main()
