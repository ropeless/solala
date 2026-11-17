"""
Provide the persistent master alarm and browser-side freshness monitoring.
"""

import json
from collections.abc import Awaitable, Callable
from datetime import datetime

from nicegui import ui

from solala.constants import Constants
from solala.control_loop import control_loop
from solala.control_loop.control_health import HealthIssue, Severity


def _alarm_state(previous: str) -> tuple[str, tuple[HealthIssue, ...]]:
    """
    Select the server-confirmed alarm state, preserving overdue hysteresis.

    Args:
        previous: Previous server-confirmed state.

    Returns:
        Alarm label and the current health-issue snapshot.
    """
    severity, issues = control_loop.get_control_health()
    overdue = control_loop.loop_check_overdue()
    if overdue > Constants.OVERDUE_THRESHOLD.total_seconds():
        return 'STALLED', issues
    if overdue > 0 and previous == 'STALLED':
        return 'STALLED', issues
    return severity.name, issues


class MasterAlarm:
    """
    Own the page-header alarm, details dialog and client heartbeat timer.

    A browser watchdog displays DISCONNECTED when server updates stop. A
    server-confirmed STALLED state is never inferred from network silence.
    """

    def __init__(self, select_tab: Callable[[str], Awaitable[None]]) -> None:
        self._select_tab = select_tab
        self._state = 'DISCONNECTED'
        self._issues: tuple[HealthIssue, ...] = ()
        with ui.button().props('flat no-caps').classes('solala-master-alarm solala-alarm-disconnected') as button:
            self._label = ui.label('DISCONNECTED')
        self._button_id = button.id
        self._label_id = self._label.id
        button.on_click(self._open_details)

        with ui.dialog() as self._dialog, ui.card().classes('w-full').style('max-width: 520px'):
            ui.label('System health').classes('text-h6')
            self._details = ui.column().classes('w-full gap-2')
            with ui.row().classes('w-full justify-end'):
                ui.button('Log', on_click=self._open_log).props('flat')
                ui.button('Close', on_click=self._dialog.close).props('flat')

        # Keep this timer alive across tab switches; root_page owns its cleanup.
        self._timer = ui.timer(2.0, self._refresh)
        self._initialise_browser()
        self._refresh()

    def _initialise_browser(self) -> None:
        """
        Install one browser watchdog and socket listener for this page.
        """
        script = f"""
            (() => {{
                const key = 'solalaMasterAlarm';
                window[key]?.close();
                const button = getHtmlElement({self._button_id});
                const label = getHtmlElement({self._label_id});
                let lastResponse = 0;
                let awaitingResponse = true;
                const disconnected = () => {{
                    awaitingResponse = true;
                    button.className = 'q-btn q-btn-item non-selectable no-outline q-btn--flat q-btn--rectangle q-btn--actionable q-focusable q-hoverable no-caps solala-master-alarm solala-alarm-disconnected';
                    label.textContent = 'DISCONNECTED';
                }};
                const onDisconnect = () => disconnected();
                const onConnect = () => {{
                    awaitingResponse = true;
                    disconnected();
                }};
                window.socket.on('disconnect', onDisconnect);
                window.socket.on('connect', onConnect);
                const watchdog = window.setInterval(() => {{
                    if (Date.now() - lastResponse > 6500) disconnected();
                }}, 1000);
                window[key] = {{
                    receive(state) {{
                        if (!window.socket.connected) return;
                        lastResponse = Date.now();
                        awaitingResponse = false;
                        button.classList.remove(
                            'solala-alarm-normal', 'solala-alarm-caution',
                            'solala-alarm-warning', 'solala-alarm-stalled',
                            'solala-alarm-disconnected'
                        );
                        button.classList.add('solala-alarm-' + state.toLowerCase());
                        label.textContent = state;
                    }},
                    close() {{
                        window.clearInterval(watchdog);
                        window.socket.off('disconnect', onDisconnect);
                        window.socket.off('connect', onConnect);
                    }}
                }};
                disconnected();
            }})();
        """
        _ = ui.run_javascript(script)

    def _refresh(self) -> None:
        """
        Send a fresh server-confirmed state to the browser.
        """
        self._state, self._issues = _alarm_state(self._state)
        _ = ui.run_javascript(
            f'window.solalaMasterAlarm?.receive({json.dumps(self._state)});'
        )

    def _open_details(self) -> None:
        """
        Show the current alarm state and active issue details.
        """
        self._state, self._issues = _alarm_state(self._state)
        self._details.clear()
        with self._details:
            ui.label(f'Status: {self._state}').classes('text-subtitle1')
            if self._state == 'STALLED':
                ui.label('Suspected total loss of hardware control. Check the Solala log.')
            elif self._state == 'WARNING':
                ui.label('Hardware control failure or uncertainty detected.')
            elif self._state == 'CAUTION':
                ui.label('Noncritical functionality is impaired.')
            elif self._state == 'NORMAL':
                ui.label('Hardware control and reporting appear to be working correctly.')
            if not self._issues:
                ui.label('No active operational issues reported.').classes('text-grey-7')
            for issue in self._issues:
                with ui.card().classes('w-full'):
                    ui.label(f'{issue.severity.name}: {issue.message}').classes('text-weight-medium')
                    ui.label(f'First: {issue.first_seen.astimezone().strftime("%Y-%m-%d %H:%M:%S")}').classes('text-caption')
                    ui.label(f'Last: {issue.last_seen.astimezone().strftime("%Y-%m-%d %H:%M:%S")}').classes('text-caption')
                    ui.label(f'Occurrences: {issue.occurrences}').classes('text-caption')
        self._dialog.open()

    async def _open_log(self) -> None:
        """
        Close details and navigate to the Log tab.
        """
        self._dialog.close()
        await self._select_tab('Log')

    def close(self) -> None:
        """
        Cancel the client-owned timer.
        """
        self._timer.cancel()
