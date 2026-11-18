import unittest
from datetime import date

from solala.server.ui_state import UIState, UIStateStorage


TABS = {'Power', 'Solar', 'Graphs', 'Price'}


class UIStateTestCase(unittest.TestCase):
    """
    Verify UI refresh state serialization and storage isolation.
    """

    def test_defaults(self) -> None:
        state = UIState.from_dict(None, TABS)
        self.assertEqual(state.tab, 'Power')
        self.assertIsNone(state.displayed_day)
        self.assertEqual(state.graph_series, {})

    def test_round_trip(self) -> None:
        original = UIState(
            tab='Graphs',
            displayed_day=date(2026, 11, 18),
            graph_series={'Power': {'Solar': False, 'Battery': True}},
        )
        restored = UIState.from_dict(original.to_dict(), TABS)
        self.assertEqual(restored, original)

    def test_invalid_values_fall_back_safely(self) -> None:
        state = UIState.from_dict({
            'tab': 'Removed Tab',
            'displayed_day': 'not a date',
            'graph_series': {
                'Power': {'Solar': False, 'Battery': 1, 'Grid': 'yes'},
                'Bad': ['not', 'a', 'mapping'],
            },
        }, TABS)
        self.assertEqual(state.tab, 'Power')
        self.assertIsNone(state.displayed_day)
        self.assertEqual(state.graph_series, {'Power': {'Solar': False}})

    def test_invalid_container(self) -> None:
        self.assertEqual(UIState.from_dict(['invalid'], TABS), UIState())

    def test_storage_round_trip(self) -> None:
        storage: dict[str, object] = {}
        adapter = UIStateStorage(storage, TABS)
        state = UIState(tab='Solar', displayed_day=date(2026, 11, 19))
        adapter.save(state)
        self.assertEqual(adapter.load(), state)

    def test_storage_snapshot_is_independent(self) -> None:
        storage: dict[str, object] = {}
        adapter = UIStateStorage(storage, TABS)
        state = UIState(graph_series={'Energy': {'Solar': False}})
        adapter.save(state)
        state.graph_series['Energy']['Solar'] = True
        self.assertFalse(adapter.load().graph_series['Energy']['Solar'])

        loaded = adapter.load()
        loaded.graph_series['Energy']['Solar'] = True
        self.assertFalse(adapter.load().graph_series['Energy']['Solar'])


if __name__ == '__main__':
    unittest.main()
