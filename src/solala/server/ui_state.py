import asyncio
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Self

from nicegui import ui

from solala.utils.json_extras import JSONDict

_STORAGE_KEY = 'solala_ui_state'


@dataclass
class UIState:
    """
    Describe the browser UI state needed to restore the active page on refresh.

    The displayed day is a concrete date, not a preference for future visits.
    Ordinary tab navigation must initialise date-sensitive pages to `today`.
    """

    tab: str
    displayed_day: date | None = None
    graph_series: dict[str, dict[str, bool]] = field(default_factory=dict)

    def to_dict(self) -> JSONDict:
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
    def from_dict(cls, value: JSONDict | None, valid_tabs: set[str], default_tab: str) -> Self:
        """
        Create a UI state from a JSON compatible dictionary.

        This method reads data from persistent browser storage, which might
        contain a `value` written by an earlier version of Solala or has been
        corrupted, so we interpret `value` defensively.

        Restore valid fields, falling back safely for invalid stored values.

        Args:
            value: Untrusted serialized state.
            valid_tabs: Currently supported tab names.
            default_tab: the tab to record as current tab if not available in `value`.
        """
        if not isinstance(value, dict):
            return cls(default_tab)

        # Read the needed parameters directly from the `value` dict.
        tab = value.get('tab')
        raw_day = value.get('displayed_day')
        raw_series = value.get('graph_series')

        if not isinstance(tab, str) or tab not in valid_tabs:
            tab = default_tab

        try:
            displayed_day = date.fromisoformat(raw_day) if isinstance(raw_day, str) else None
        except ValueError:
            displayed_day = None

        graph_series: dict[str, dict[str, bool]] = {}
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
    Persist UI state in the current browser tab's sessionStorage.
    """

    def __init__(self, valid_tabs: set[str], default_tab: str) -> None:
        self._valid_tabs = valid_tabs
        self._default_tab = default_tab
        self._save_lock = asyncio.Lock()

    async def load(self) -> UIState:
        """
        Load the current browser tab's saved UI state.
        """
        value = await ui.run_javascript(
            f'''(() => {{
                try {{
                    return JSON.parse(sessionStorage.getItem({_STORAGE_KEY!r}) || 'null');
                }} catch {{
                    return null;
                }}
            }})()'''
        )
        return UIState.from_dict(value, self._valid_tabs, self._default_tab)

    async def save(self, state: UIState) -> None:
        """
        Save a UI state snapshot for the current browser tab.

        Args:
            state: Current UI state to persist.
        """
        async with self._save_lock:
            payload = json.dumps(state.to_dict())
            await ui.run_javascript(
                f'sessionStorage.setItem({_STORAGE_KEY!r}, {json.dumps(payload)})'
            )
