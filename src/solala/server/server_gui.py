"""
Implement the NiceGUI interface.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date
from functools import partial
from typing import Coroutine, Any

from nicegui import ui, app, events
from nicegui.element import Element
from nicegui.elements.button import Button

from solala.constants import Constants
from solala.control_loop import control_loop
from solala.logger import LOGGER
from solala.resources import IMAGE_FILES, RESOURCES, CSS_FILES
from solala.server import infographic
from solala.server import server_log
from solala.server.css_colours import Colours, css_colours, rgba
from solala.server.day_navigator import DayNavigator
from solala.server.icons import analytics_name_to_icon_url
from solala.server.infographic import CLICK_ID_HOME, CLICK_ID_SUN, CLICK_ID_GRID, CLICK_ID_BATTERY, \
    CLICK_ID_INVERTER
from solala.server.master_alarm import MasterAlarm
from solala.server.page_session import PageSession
from solala.server.page_updaters import BatteryButtonUpdater, InverterButtonUpdater, InfographicUpdater, \
    SolarForecastUpdater, PriceForecastUpdater, ChartUpdater, StatusUpdater, RegistersUpdater
from solala.server.ui_state import UIState, UIStateStorage
from solala.server.units_lookup import CONNECTION_UNITS, PARAMETERS_UNITS, CONSTANTS_UNITS
from solala.utils.json_extras import JSONDict, render_json

# --------------------------------------------------------------------
# Main styling
# --------------------------------------------------------------------

_HEAD_HTML = r'''
<link rel="manifest" href="/manifest.json">
<link rel="stylesheet" href="/css/solala.css">
<link rel="icon" type="image/png" href="/images/solala-32x32.png">
'''


def _page_header() -> Element:
    """
    Build the persistent Solala page header and return its alarm container.
    """
    with ui.element('div').classes('solala-header'):
        with ui.element('div').classes('solala-brand'):
            image = ui.image('/images/solala.svg')
            image.classes('w-12 h-12 bg-transparent')

            with ui.element('div'):
                ui.label(Constants.APP_NAME).classes('solala-brand-name')
                ui.label(Constants.APP_SUBTITLE).classes('solala-brand-subtitle')

        return ui.element('div').classes('solala-alarm-container')


def _control_header(title: str) -> None:
    """
    Add a titled header to a dashboard control card.

    Args:
        title: Heading displayed above the controls.
    """
    with ui.element('div').classes('control-header'):
        with ui.element('div').classes('dashboard-card-title'):
            ui.label(title)


async def _ui_control_buttons(session: PageSession) -> None:
    """
    Build battery and inverter controls and register their status listeners.

    Args:
        session: Session that owns the control listeners.
    """
    # ======================================================
    # BATTERY
    # ======================================================

    with ui.element('div').classes('dashboard-card control-card'):
        _control_header('Battery')
        with ui.element('div').classes('control-buttons'):
            battery_enable = ui.button('ENABLE').classes('solala-button')
            battery_disable = ui.button('DISABLE').classes('solala-button')
            battery_force_charge = ui.button('FORCE CHARGE').classes('solala-button')
            battery_force_discharge = ui.button('FORCE DISCHARGE').classes('solala-button')
            battery_charge_only = ui.button('CHARGE ONLY').classes('solala-button')
            battery_discharge_only = ui.button('DISCHARGE ONLY').classes('solala-button')
            battery_cheap_force_charge = ui.button('CHEAP ⇒ FORCE CHARGE').classes('solala-button')

            battery_force_charge.classes('wide')
            battery_force_discharge.classes('wide')
            battery_charge_only.classes('wide')
            battery_discharge_only.classes('wide')
            battery_cheap_force_charge.classes('wide')

        updater = BatteryButtonUpdater(
            battery_enable=battery_enable,
            battery_disable=battery_disable,
            battery_force_charge=battery_force_charge,
            battery_force_discharge=battery_force_discharge,
            battery_charge_only=battery_charge_only,
            battery_discharge_only=battery_discharge_only,
            battery_cheap_force_charge=battery_cheap_force_charge,
        )
        await updater.update()  # call synchronously to avoid flicker
        await session.add_control_listener(updater)

    # ======================================================
    # INVERTER
    # ======================================================

    with ui.element('div').classes('dashboard-card control-card'):
        _control_header('Inverter')
        with ui.element('div').classes('control-buttons'):
            inverter_enable = ui.button('ENABLE').classes('solala-button')
            inverter_disable = ui.button('DISABLE').classes('solala-button')
            inverter_zero_export = ui.button('ZERO EXPORT').classes('solala-button')
            inverter_neg_feed_in_zero_export = ui.button('NEG FEED-IN ⇒ ZERO EXPORT').classes(
                'solala-button')

            inverter_zero_export.classes('wide')
            inverter_neg_feed_in_zero_export.classes('wide')

        updater = InverterButtonUpdater(
            inverter_enable=inverter_enable,
            inverter_disable=inverter_disable,
            inverter_zero_export=inverter_zero_export,
            inverter_neg_feed_in_zero_export=inverter_neg_feed_in_zero_export,
        )
        await updater.update()  # call synchronously to avoid flicker
        await session.add_control_listener(updater)


def _infographic_click(
        element: events.GenericEventArguments,
        select_tab: Callable[[str], Coroutine[Any, Any, None]],
) -> None:
    """
    Navigate to the price or solar tab when its infographic region is clicked.

    Args:
        element: Click event containing the SVG region identifier.
        select_tab: Asynchronous tab-selection callback.
    """
    click_id: str | None = element.args
    if click_id == CLICK_ID_GRID:
        asyncio.create_task(select_tab(_PRICE_TAB))
    elif click_id == CLICK_ID_SUN:
        asyncio.create_task(select_tab(_SOLAR_TAB))
    elif click_id in (CLICK_ID_INVERTER, CLICK_ID_HOME, CLICK_ID_BATTERY):
        # More may be implemented in the future
        pass


# ====================================================================
#  Tabbed application
# ====================================================================

# Mount static files
app.add_static_files(url_path='/images', local_directory=str(IMAGE_FILES))
app.add_static_files(url_path='/css', local_directory=str(CSS_FILES))
app.add_static_file(url_path='/manifest.json', local_file=str(RESOURCES / 'manifest.json'))


async def _build_power_page(container: Element, session: PageSession) -> None:
    """
    Build the power-flow infographic and controls.
    """
    with container:
        with ui.element('div').classes('dashboard-card infographic-card'):
            ui.label('Power').classes('dashboard-card-title')

            with ui.element('div').classes('infographic-container'):
                infographic_element = ui.html(
                    '<div class="infographic-loading">loading power schematic...</div>'
                ).style(
                    f'width: {infographic.WIDTH}px; '
                    f'height: {infographic.HEIGHT}px; '
                    'flex: 0 0 auto;'
                )
                infographic_element.on(
                    'click',
                    handler=partial(_infographic_click, select_tab=session.select_tab),
                    js_handler="(e) => emit(e.target.closest('rect')?.id)",
                )
                updater = InfographicUpdater(infographic_element=infographic_element)
                session.add_task(asyncio.create_task(updater.update()))
                await session.add_control_listener(updater)

        if Constants.CONTROLS_ENABLED:
            await _ui_control_buttons(session)


async def _build_solar_page(container: Element, session: PageSession) -> None:
    """
    Build the date-navigable solar forecast with session-owned listeners.
    """
    with container:
        navigator = DayNavigator(
            title='Solar Forecast',
            enable_swipe_content=True,
            on_day_change=session.on_day_change,
            track_task=session.add_task,
        )
        updaters = [
            SolarForecastUpdater(element, session)
            for element in navigator.get_elements()
        ]
        navigator.set_listeners(*(updater.set_day for updater in updaters))
        await navigator.set_day(session.initial_day or date.today())
        session.add_timer(ui.timer(60, navigator.refresh_day_label))
        await navigator.initialise_auto_height()
        for updater in updaters:
            await session.add_control_listener(updater)


async def _build_price_page(container: Element, session: PageSession) -> None:
    """
    Build the price forecast table and register its refresh listener.
    """
    with container:
        # Match the Solar Forecast's title/content wrapper so the date rows
        # start at the same vertical position.
        with ui.element('div'):
            ui.label('Price Forecast').classes('dashboard-card-title')
            element = ui.element('div')

        updater = PriceForecastUpdater(element=element)
        session.add_task(asyncio.create_task(updater.update()))
        await session.add_control_listener(updater)


async def _build_graphs_page(container: Element, session: PageSession) -> None:
    """
    Build daily charts with date navigation and database-loop updates.
    """
    with container:
        swipe_area = ui.element('div').classes('w-full').style('touch-action: pan-y;')
        with swipe_area:
            navigator = DayNavigator(
                title='Daily Graphs',
                on_day_change=session.on_day_change,
                track_task=session.add_task,
            )
            updaters = [
                ChartUpdater(element, session=session)
                for element in navigator.get_elements()
            ]
            persist_legend = session.on_legend_change

            async def sync_legend(chart: str, selected: dict[str, bool]) -> None:
                for updater in updaters:
                    updater.sync_legend(chart, selected)
                if persist_legend is not None:
                    await persist_legend(chart, selected)

            session.on_legend_change = sync_legend
            navigator.set_listeners(*(updater.set_day for updater in updaters))
            await navigator.set_day(session.initial_day or date.today())
            session.add_timer(ui.timer(60, navigator.refresh_day_label))
            await navigator.initialise_auto_height()
            for updater in updaters:
                await session.add_database_listener(updater)


async def _build_status_page(container: Element, session: PageSession) -> None:
    """
    Build the formatted control-loop status display.
    """
    with container:
        with ui.card().classes('w-full'):
            ui.label('Status').classes('dashboard-card-title')
            updater = StatusUpdater(
                status_element=ui.code(language='nothing').classes('text-sm w-full grow')
            )
            session.add_task(asyncio.create_task(updater.update()))
            await session.add_control_listener(updater)


async def _build_connection_page(container: Element, _: PageSession) -> None:
    """
    Display the current connection information as formatted JSON.
    """
    with container:
        with ui.card().classes('w-full'):
            ui.label('Connection').classes('dashboard-card-title')
            connection_info: JSONDict = await control_loop.get_connection_info()
            json_as_str = render_json(
                connection_info, float_format='.2f', units=CONNECTION_UNITS
            )
            connection_element = ui.code(language='nothing').classes('text-sm w-full grow')
            connection_element.set_content(json_as_str)


async def _build_parameters_page(container: Element, _: PageSession) -> None:
    """
    Display the active control policy and configured constants.
    """
    with container:
        with ui.column().classes('w-full'):
            with ui.card().classes('w-full'):
                ui.label('Policy').classes('dashboard-card-title')
                policy = ui.code(language='nothing').classes('text-sm w-full grow')
                policy_json: JSONDict = (await control_loop.get_control_mode()).to_json()
                policy.set_content(render_json(policy_json, units=PARAMETERS_UNITS))
            with ui.card().classes('w-full'):
                ui.label('Constants').classes('dashboard-card-title')
                consts = ui.code(language='nothing').classes('text-sm w-full grow')
                constants_json: JSONDict = control_loop.Constants.to_json()
                consts.set_content(
                    render_json(
                        constants_json,
                        remove_key_underscores=False,
                        units=CONSTANTS_UNITS,
                    )
                )


async def _build_registers_page(container: Element, session: PageSession) -> None:
    """
    Build the register display and register its refresh listener.
    """
    with container:
        with ui.card().classes('w-full'):
            ui.label('Registers').classes('dashboard-card-title')
            updater = RegistersUpdater(
                session,
                initial_filter=session.register_filter,
                on_filter_change=session.on_register_filter_change,
            )
            await session.add_control_listener(updater)
            await updater.update()


async def _build_log_page(container: Element, session: PageSession) -> None:
    """
    Build the log console and unregister it when the session closes.
    """
    with container:
        with ui.row().classes('w-full items-center justify-between'):
            ui.label('Log Console').classes('dashboard-card-title')
            ui.button(icon='content_copy').props('round flat size=sm').classes(
                'opacity-50 hover:opacity-100'
            ).tooltip('Copy log contents').on(
                'click',
                js_handler="""() => {
                    const log = document.querySelector('.solala-log');
                    if (log) navigator.clipboard.writeText(log.innerText);
                }""",
            )
        log_ui = ui.element('div').classes('solala-log w-full')
    server_log.add(log_ui)
    session.add_cleanup(partial(server_log.remove, log_ui))


# Asynchronous builder for a tab's content and session resources.
type Builder = Callable[[Element, PageSession], Awaitable[None]]


@dataclass
class Tab:
    """
    Describe a tab's label, icon presentation, and content builder.
    """
    name: str
    icon_scale: float  # for visually balancing the size of the icons.
    icon_url: str
    builder: Builder


_TABS: Sequence[Tab] = (
    Tab('Power', 1.0, '/images/analytics-icons/power.svg', _build_power_page),
    Tab('Solar', 0.9, '/images/solala-black.svg', _build_solar_page),
    Tab('Price', 1.0, '/images/analytics-icons/grid.svg', _build_price_page),
    Tab('Graphs', 0.9, analytics_name_to_icon_url('Graphs'), _build_graphs_page),
    Tab('Status', 1.0, analytics_name_to_icon_url('Status'), _build_status_page),
    Tab('Connection', 0.9, analytics_name_to_icon_url('Connection'), _build_connection_page),
    Tab('Parameters', 0.9, analytics_name_to_icon_url('Parameters'), _build_parameters_page),
    Tab('Registers', 1.0, analytics_name_to_icon_url('Registers'), _build_registers_page),
    Tab('Log', 1.0, analytics_name_to_icon_url('Log'), _build_log_page),
)

_FIRST_TAB: str = _TABS[0].name
_SOLAR_TAB: str = _TABS[1].name
_PRICE_TAB: str = _TABS[2].name


class TabSelector:
    """
    Manage tab selection, asynchronous construction, and session clean-up.

    Tab transitions are serialised by a lock. Each selected tab receives a
    new `PageSession`, and any previous build and session are closed before
    the next tab is constructed.
    """

    def __init__(
            self,
            colours: Colours,
            button_container: Element,
            content_container: Element,
            state_storage: UIStateStorage,
    ) -> None:
        self.content_container: Element = content_container
        self._state_storage = state_storage
        self._state = UIState(tab=_FIRST_TAB)

        self.buttons: dict[str, Button] = {}
        self.builder: dict[str, Builder] = {}

        with button_container:
            for tab_def in _TABS:
                with ui.button().classes('solala-tab-button').props('color=white text-color=black') as button:
                    ui.image(tab_def.icon_url).classes('solala-tab-icon').style(
                        f'transform: scale({tab_def.icon_scale}); transform-origin: center;'
                    )
                    ui.label(tab_def.name).classes('text-xs')
                    self.buttons[tab_def.name] = button
                    self.builder[tab_def.name] = tab_def.builder
                    button.on_click(partial(self.select_tab, tab_def.name))

        self.active_tab: str | None = None
        self.active_session: PageSession | None = None
        self.colours: Colours = colours
        self._build_task: asyncio.Task[None] | None = None
        self._transition_lock = asyncio.Lock()

    def restore_state(self, state: UIState) -> None:
        """
        Supply the state loaded for this browser page before initial selection.
        """
        self._state = state

    async def select_tab(self, tab_name: str, *, restored_day: date | None = None) -> None:
        """
        Select a tab, cancelling and cleaning up the previous tab first.

        Args:
            tab_name: Name of a configured tab.
            restored_day: Date restored after a browser refresh, if available.
        """
        async with self._transition_lock:
            if tab_name == self.active_tab:
                return

            await self._close_active_session()
            self.content_container.clear()
            self.active_tab = tab_name
            self._state.tab = tab_name
            self._state.displayed_day = restored_day if tab_name in (_SOLAR_TAB, 'Graphs') else None
            await self._state_storage.save(self._state)

            for name, button in self.buttons.items():
                if name == tab_name:
                    background = rgba(self.colours.tab, alpha=0.15)
                    button.props(f'color="{background}" text-color=black')
                    button.classes(add='solala-tab-button-active')
                else:
                    button.props('color=white text-color=black')
                    button.classes(remove='solala-tab-button-active')

            async def save_day(day: date) -> None:
                if self.active_session is session:
                    self._state.displayed_day = day
                    await self._state_storage.save(self._state)

            filter_save_task: asyncio.Task[None] | None = None

            async def persist_register_filter() -> None:
                while True:
                    pattern = self._state.register_filter
                    await self._state_storage.save(self._state)
                    if pattern == self._state.register_filter:
                        return

            def save_register_filter(pattern: str) -> None:
                nonlocal filter_save_task
                if self.active_session is not session or session.closed:
                    return
                self._state.register_filter = pattern
                if filter_save_task is None or filter_save_task.done():
                    filter_save_task = asyncio.create_task(persist_register_filter())
                    session.add_task(filter_save_task)

            async def save_legend(chart: str, selected: dict[str, bool]) -> None:
                if self.active_session is session:
                    self._state.graph_series[chart] = selected.copy()
                    await self._state_storage.save(self._state)

            session = PageSession(
                self.colours, self.select_tab,
                initial_day=restored_day,
                on_day_change=save_day if tab_name in (_SOLAR_TAB, 'Graphs') else None,
                graph_series=self._state.graph_series,
                on_legend_change=save_legend if tab_name == 'Graphs' else None,
                register_filter=self._state.register_filter,
                on_register_filter_change=save_register_filter if tab_name == 'Registers' else None,
            )
            self.active_session = session
            self._build_task = asyncio.create_task(self._build_tab(tab_name, session))

    async def close_active_session(self) -> None:
        """
        Close the active tab session, serialised with tab transitions.
        """
        async with self._transition_lock:
            await self._close_active_session(flush_filter=False)

    async def _cancel_active_build(self) -> None:
        """
        Cancel and await an unfinished tab construction task.
        """
        task = self._build_task
        self._build_task = None
        if task is None or task.done():
            return

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _close_active_session(self, *, flush_filter: bool = True) -> None:
        """
        Stop tab construction and release resources owned by its session.
        """
        await self._cancel_active_build()
        if self.active_session is not None:
            session = self.active_session
            self.active_session = None
            await session.close()
            if flush_filter and self.active_tab == 'Registers':
                # Flush the final filter after cancelling any pending session-owned save.
                await self._state_storage.save(self._state)

    async def _build_tab(self, tab_name: str, session: PageSession) -> None:
        """
        Build a tab and display an error panel if construction fails.
        """
        builder = self.builder[tab_name]
        try:
            await builder(self.content_container, session)
        except asyncio.CancelledError:
            await session.close()
            raise
        except Exception:
            await session.close()
            if self.active_session is session:
                self.active_session = None
                LOGGER.exception('Error building %s tab', tab_name)
                with self.content_container:
                    with ui.card().classes('w-full'):
                        ui.label(f'Unable to display {tab_name}').classes('text-h6')
                        ui.label('See the Solala log for details.').classes('text-sm text-gray-500')


@ui.page('/')
async def root_page() -> None:
    """
    Initialise the root page and select its initial tab.

    The active session is closed when the NiceGUI client disconnects.
    """
    ui.add_head_html(_HEAD_HTML)
    colours: Colours = await css_colours()  # must come directly after add_head_html.

    with ui.element('div').classes('solala-page'):
        alarm_container = _page_header()

        with ui.element('div').classes('dashboard-card tab-navigation'):
            button_container = ui.grid(columns=3).classes('w-full gap-2')

        content_container = ui.element('div').classes('tab-content w-full')
        state_storage = UIStateStorage(ui.context.client, {tab.name for tab in _TABS}, _FIRST_TAB)
        tab_selector = TabSelector(colours, button_container, content_container, state_storage)

    with alarm_container:
        master_alarm = MasterAlarm(tab_selector.select_tab)

    ui.context.client.on_disconnect(master_alarm.close)
    ui.context.client.on_disconnect(tab_selector.close_active_session)
    state = await state_storage.load()
    tab_selector.restore_state(state)
    await tab_selector.select_tab(state.tab, restored_day=state.displayed_day)
