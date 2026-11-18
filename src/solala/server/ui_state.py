from collections.abc import MutableMapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any


_STORAGE_KEY = 'solala_ui_state'


@dataclass
class UIState:
    """
    Describe the browser UI state needed to restore the active page on refresh.

    The displayed day is a concrete date, not a preference for future visits.
    Ordinary tab navigation must initialize date-sensitive pages to today.
    """

    tab: str = 'Power'
    displayed_day: date | None = None
    graph_series: dict[str, dict[str, bool]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize the UI state using JSON-compatible values.
        """
        return {
            'tab': self.tab,
            'displayed_day': self.displayed_day.isoformat() if self.displayed_day else None,
            'graph_series': {
                chart: selections.copy()
                for chart, selections in self.graph_series.items()
            },
        }

    @classmethod
    def from_dict(cls, value: object, valid_tabs: set[str]) -> 'UIState':
        """
        Restore valid fields, falling back safely for invalid stored values.

        Args:
            value: Untrusted serialized state.
            valid_tabs: Currently supported tab names.
        """
        if not isinstance(value, dict):
            return cls()

        tab = value.get('tab')
        if not isinstance(tab, str) or tab not in valid_tabs:
            tab = 'Power'

        raw_day = value.get('displayed_day')
        try:
            displayed_day = date.fromisoformat(raw_day) if isinstance(raw_day, str) else None
        except ValueError:
            displayed_day = None

        graph_series: dict[str, dict[str, bool]] = {}
        raw_series = value.get('graph_series')
        if isinstance(raw_series, dict):
            for chart, selections in raw_series.items():
                if not isinstance(chart, str) or not isinstance(selections, dict):
                    continue
                valid_selections = {
                    series: selected
                    for series, selected in selections.items()
                    if isinstance(series, str) and isinstance(selected, bool)
                }
                graph_series[chart] = valid_selections

        return cls(tab=tab, displayed_day=displayed_day, graph_series=graph_series)


class UIStateStorage:
    """
    Read and write a UI state snapshot in a NiceGUI-compatible storage mapping.

    The caller supplies the appropriate browser-scoped storage mapping.
    """

    def __init__(self, storage: MutableMapping[str, Any], valid_tabs: set[str]) -> None:
        self._storage = storage
        self._valid_tabs = valid_tabs

    def load(self) -> UIState:
        """
        Return a validated snapshot of the stored UI state.
        """
        return UIState.from_dict(self._storage.get(_STORAGE_KEY), self._valid_tabs)

    def save(self, state: UIState) -> None:
        """
        Persist a JSON-compatible snapshot of the UI state.

        Args:
            state: Current UI state to persist.
        """
        self._storage[_STORAGE_KEY] = state.to_dict()
