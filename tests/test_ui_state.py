import unittest
from datetime import date

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

    def test_storage_round_trip(self) -> None:
        storage: dict[str, object] = {}
        adapter = UIStateStorage(storage, TABS, DEFAULT_TAB)
        state = UIState(tab='Solar', displayed_day=date(2026, 11, 19))
        adapter.save(state)
        self.assertEqual(adapter.load(), state)

    def test_storage_snapshot_is_independent(self) -> None:
        storage: dict[str, object] = {}
        adapter = UIStateStorage(storage, TABS, DEFAULT_TAB)
        state = UIState(tab=DEFAULT_TAB, graph_series={'Energy': {'Solar': False}})
        adapter.save(state)
        state.graph_series['Energy']['Solar'] = True
        self.assertFalse(adapter.load().graph_series['Energy']['Solar'])

        loaded = adapter.load()
        loaded.graph_series['Energy']['Solar'] = True
        self.assertFalse(adapter.load().graph_series['Energy']['Solar'])


if __name__ == '__main__':
    unittest.main()
