import asyncio
from dataclasses import dataclass
from datetime import date
from functools import partial
from typing import Optional, List, Callable, Awaitable, Dict, Sequence, TypeAlias

from nicegui import ui, app, events
from nicegui.element import Element
from nicegui.elements.button import Button
from nicegui.elements.label import Label
from nicegui.elements.mixins.content_element import ContentElement

from solala.constants import Constants
from solala.control_loop import control_loop
from solala.logger import LOGGER
from solala.resources import IMAGE_FILES, RESOURCES, CSS_FILES
from solala.server import server_log
from solala.server.css_colours import Colours, css_colours, rgba
from solala.server.day_navigator import DayNavigator
from solala.server.icons import analytics_name_to_icon_url
from solala.server.page_session import PageSession
from solala.server.page_updaters import BatteryButtonUpdater, InverterButtonUpdater, InfographicUpdater, \
    SolarForecastUpdater, PriceForecastUpdater, ChartUpdater, StatusUpdater, RegistersUpdater
from solala.server.server_infographic import CLICK_ID_HOME, CLICK_ID_SUN, CLICK_ID_GRID, CLICK_ID_BATTERY, \
    CLICK_ID_INVERTER
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


def _json_page(name: str) -> ContentElement:
    """
    Prepare a page to show JSON data.

    Args:
        name: name of the page

    Returns:
        The content element to use for adding the rendered JSON data.
    """
    return _json_multi_page(name)[0]


def _json_multi_page(*names: str) -> List[ContentElement]:
    """
    Prepare a page to show multiple JSON data.
    """
    result: List[ContentElement] = []
    ui.add_head_html(_HEAD_HTML)
    with ui.element('div').classes('solala-page'):
        _page_header()

        with ui.column():
            for name in names:
                with ui.card():
                    ui.label(name).classes('text-h6')
                    registers_element = ui.code(language='nothing').classes('text-sm w-full grow')
                    result.append(registers_element)

    return result


def _page_header(ext: str = '', link: bool = True) -> None:
    """
    NiceGui snippet to add the Solala title to the page.
    Args:
        ext: A string to append to the title.
        link: Whether to create a link to the home page or not
    """
    with ui.element('div').classes('solala-header'):

        with ui.element('div').classes('solala-brand'):
            if link:
                with ui.link(target='/'):
                    image = ui.image('/images/solala.svg')
            else:
                image = ui.image('/images/solala.svg')
            image.classes('w-12 h-12 bg-transparent')

            with ui.element('div'):
                ui.label(f'{Constants.APP_NAME}{ext}').classes('solala-brand-name')
                ui.label(Constants.APP_SUBTITLE).classes('solala-brand-subtitle')


def _control_header(title: str) -> None:
    with ui.element('div').classes('control-header'):
        with ui.element('div').classes('control-title'):
            # ui.label(icon).classes('control-title-icon')
            ui.label(title)
        # with ui.element('div').classes('control-state'):
        #     ui.element('div').classes('control-state-dot')
        #     ui.label(state)


def _button_classes(button, primary=False, wide=False) -> None:
    classes = 'solala-button'
    if wide:
        classes += ' wide'
    button.classes(classes)
    if primary:
        button.props('color=primary')
    else:
        button.props('color=grey')
    return button


def _analytics_link(name: str, target: str) -> None:
    with ui.link(target=target).classes('analytics-link'):
        ui.image(analytics_name_to_icon_url(name)).classes('analytics-icon')
        ui.label(name)


async def _ui_control_buttons(session: PageSession) -> None:
    """
    Add the control buttons to the UI (if Constants.CONTROLS_ENABLED is True).
    """
    if not Constants.CONTROLS_ENABLED:
        return

    with ui.element('div').classes('control-column'):
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
                battery_cheap_force_discharge = ui.button('CHEAP ⇒ FORCE CHARGE').classes('solala-button')

                battery_force_charge.classes('wide')
                battery_force_discharge.classes('wide')
                battery_charge_only.classes('wide')
                battery_discharge_only.classes('wide')
                battery_cheap_force_discharge.classes('wide')

            updater = BatteryButtonUpdater(
                battery_enable=battery_enable,
                battery_disable=battery_disable,
                battery_force_charge=battery_force_charge,
                battery_force_discharge=battery_force_discharge,
                battery_charge_only=battery_charge_only,
                battery_discharge_only=battery_discharge_only,
                battery_cheap_force_discharge=battery_cheap_force_discharge,
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


def _infographic_click(element, select_tab) -> None:
    click_id: Optional[str] = element.args
    if click_id == CLICK_ID_GRID:
        asyncio.create_task(select_tab('Grid'))
    elif click_id == CLICK_ID_SUN:
        asyncio.create_task(select_tab('Solar'))
    elif click_id in (CLICK_ID_INVERTER, CLICK_ID_HOME, CLICK_ID_BATTERY):
        pass


def _update_loop_status(loop_status_light: Element, loop_status_label: Label) -> None:
    overdue: float = control_loop.loop_check_overdue()
    if overdue > Constants.LOOP_TIME:
        loop_status_light.classes(
            replace='solala-loop-status-light solala-loop-status-stale'
        )
        loop_status_light.tooltip('Control loop appears to be stalled')
        loop_status_label.set_text('stalled')
        loop_status_label.classes(
            replace='solala-loop-status-label solala-loop-status-stale'
        )
    elif overdue == 0:
        loop_status_light.classes(
            replace='solala-loop-status-light solala-loop-status-live'
        )
        loop_status_light.tooltip('Control loop appears to be active')
        loop_status_label.set_text('live')
        loop_status_label.classes(
            replace='solala-loop-status-label solala-loop-status-live'
        )
    else:
        # Leave it as it is
        pass


def _day_navigation(
        swipe_area: ui.Area,
        change_day: Callable[[int], Awaitable[None]],
        set_day: Callable[[date], Awaitable[None]],
):
    # Handler for swipe actions
    async def handle_swipe(event) -> None:
        direction = event.args
        if direction == 'left':
            await change_day(1)
        elif direction == 'right':
            await change_day(-1)

    swipe_area.on(
        'touchstart',
        js_handler="""(e) => {
            if (!e.changedTouches.length) return;

            const touch = e.changedTouches[0];
            e.currentTarget.dataset.startX = touch.clientX;
            e.currentTarget.dataset.startY = touch.clientY;
        }""",
    )

    swipe_area.on(
        'touchend',
        handle_swipe,
        js_handler="""(e) => {
            if (!e.changedTouches.length) return;

            const touch = e.changedTouches[0];
            const startX = Number(e.currentTarget.dataset.startX);
            const startY = Number(e.currentTarget.dataset.startY);

            // Ignore gestures if the starting position was not recorded.
            if (!Number.isFinite(startX) ||
                !Number.isFinite(startY)) return;

            const dx = touch.clientX - startX;
            const dy = touch.clientY - startY;

            // Require a deliberate horizontal swipe.
            if (Math.abs(dx) >= 60 &&
                Math.abs(dx) > Math.abs(dy) * 1.5) {
                emit(dx < 0 ? 'left' : 'right');
            }
        }""",
    )

    async def handle_key(e: events.KeyEventArguments) -> None:
        if e.action.keydown:
            if e.key.arrow_left:
                await change_day(-1)
            elif e.key.arrow_right:
                await change_day(1)
            elif e.key.home:
                await set_day(date.today())

    ui.keyboard(on_key=handle_key, repeating=False)


# ====================================================================
#  Tabbed application
# ====================================================================

# Mount static files
app.add_static_files(url_path='/images', local_directory=str(IMAGE_FILES))
app.add_static_files(url_path='/css', local_directory=str(CSS_FILES))
app.add_static_file(url_path='/manifest.json', local_file=str(RESOURCES / 'manifest.json'))


async def _build_power_page(container: Element, session: PageSession) -> None:
    with container:
        with ui.element('div').classes('dashboard-card infographic-card'):
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('Power').classes('infographic-title')
                with ui.row().classes('items-center gap-2'):
                    loop_status_light = ui.element('div').classes(
                        'solala-loop-status-light solala-loop-status-stale'
                    )
                    loop_status_label = ui.label('active').classes(
                        'solala-loop-status-label solala-loop-status-stale'
                    )

                _update_loop_status(loop_status_light, loop_status_label)
                session.add_timer(
                    ui.timer(2.0, partial(_update_loop_status, loop_status_light, loop_status_label))
                )

                # Register the JavaScript to set the status light to stale when disconnected.
                # Explicitly ignore the awaitable response.
                _ = ui.run_javascript(f"""
                    const light = getHtmlElement({loop_status_light.id});
                    const label = getHtmlElement({loop_status_label.id});
                    window.socket.on('disconnect', () => {{
                        light.className = 'solala-loop-status-light solala-loop-status-stale';
                        light.title = 'Connection to Solala server lost';
                        label.textContent = 'stale';
                        label.className = 'solala-loop-status-label solala-loop-status-stale';
                    }});
                """)

            with ui.element('div').classes('infographic-container'):
                infographic = ui.html()
                # infographic.on(
                #     'click',
                #     handler=partial(_infographic_click, select_tab=select_tab),
                #     js_handler="(e) => emit(e.target.closest('rect')?.id)",
                # )
                updater = InfographicUpdater(infographic_element=infographic)
                session.add_task(asyncio.create_task(updater.update()))
                await session.add_control_listener(updater)

        if Constants.CONTROLS_ENABLED:
            with ui.element('div').classes('dashboard-card control-card'):
                await _ui_control_buttons(session)


async def _build_solar_page(container: Element, session: PageSession) -> None:
    with container:
        navigator = DayNavigator(enable_swipe_content=True)
        updaters = [
            SolarForecastUpdater(element, session)
            for element in navigator.get_elements()
        ]
        navigator.set_listeners(*(updater.set_day for updater in updaters))
        await navigator.set_day(date.today())
        for updater in updaters:
            await session.add_control_listener(updater)


async def _build_grid_page(container: Element, session: PageSession) -> None:
    with container:
        element = ui.element('div')
        updater = PriceForecastUpdater(element=element)
        session.add_task(asyncio.create_task(updater.update()))
        await session.add_control_listener(updater)


async def _build_graphs_page(container: Element, session: PageSession) -> None:
    with container:
        swipe_area = ui.element('div').classes('w-full').style('touch-action: pan-y;')
        with swipe_area:
            navigator = DayNavigator(auto_height=True)
            updaters = [
                ChartUpdater(element, session=session)
                for element in navigator.get_elements()
            ]
            navigator.set_listeners(*(updater.set_day for updater in updaters))
            await navigator.set_day(date.today())
            await navigator.initialise_auto_height()
            for updater in updaters:
                await session.add_database_listener(updater)


async def _build_status_page(container: Element, session: PageSession) -> None:
    with container:
        with ui.card().classes('w-full'):
            ui.label('Status').classes('text-h6')
            updater = StatusUpdater(
                status_element=ui.code(language='nothing').classes('text-sm w-full grow')
            )
            session.add_task(asyncio.create_task(updater.update()))
            await session.add_control_listener(updater)


async def _build_connection_page(container: Element, session: PageSession) -> None:
    with container:
        with ui.card().classes('w-full'):
            ui.label('Connection').classes('text-h6')
            connection_info: JSONDict = await control_loop.get_connection_info()
            json_as_str = render_json(
                connection_info, float_format='.2f', units=CONNECTION_UNITS
            )
            connection_element = ui.code(language='nothing').classes('text-sm w-full grow')
            connection_element.set_content(json_as_str)


async def _build_parameters_page(container: Element, session: PageSession) -> None:
    with container:
        with ui.column().classes('w-full'):
            with ui.card().classes('w-full'):
                ui.label('Policy').classes('text-h6')
                policy = ui.code(language='nothing').classes('text-sm w-full grow')
                policy_json: JSONDict = (await control_loop.get_control_mode()).to_json()
                policy.set_content(render_json(policy_json, units=PARAMETERS_UNITS))
            with ui.card().classes('w-full'):
                ui.label('Constants').classes('text-h6')
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
    with container:
        with ui.card().classes('w-full'):
            ui.label('Registers').classes('text-h6')
            registers_element = ui.code(language='nothing').classes('text-sm w-full grow')
            updater = RegistersUpdater(registers_element)
            session.add_task(asyncio.create_task(updater.update()))
            await session.add_control_listener(updater)


async def _build_log_page(container: Element, session: PageSession) -> None:
    with container:
        log_ui = ui.element('div').classes('solala-log w-full')
    server_log.add(log_ui)
    session.add_cleanup(partial(server_log.remove, log_ui))


Builder: TypeAlias = Callable[[Element, PageSession], Awaitable[None]]


@dataclass
class Tab:
    name: str
    icon_scale: float  # for visually balancing the size of the icons.
    icon_url: str
    builder: Builder


_TABS: Sequence[Tab] = (
    Tab('Power', 1.0, '/images/analytics-icons/power.svg', _build_power_page),
    Tab('Solar', 0.9, '/images/solala-black.svg', _build_solar_page),
    Tab('Grid', 1.0, '/images/analytics-icons/grid.svg', _build_grid_page),
    Tab('Graphs', 0.9, analytics_name_to_icon_url('Graphs'), _build_graphs_page),
    Tab('Status', 1.0, analytics_name_to_icon_url('Status'), _build_status_page),
    Tab('Connection', 0.9, analytics_name_to_icon_url('Connection'), _build_connection_page),
    Tab('Parameters', 0.9, analytics_name_to_icon_url('Parameters'), _build_parameters_page),
    Tab('Registers', 1.0, analytics_name_to_icon_url('Registers'), _build_registers_page),
    Tab('Log', 1.0, analytics_name_to_icon_url('Log'), _build_log_page),
)


class TabSelector:
    def __init__(
            self,
            colours: Colours,
            button_container: Element,
            content_container: Element,
    ) -> None:
        self.button_container: Element = button_container
        self.content_container: Element = content_container

        self.buttons: Dict[str, Button] = {}
        self.builder: Dict[str, Builder] = {}

        with self.button_container:
            for tab_def in _TABS:
                with ui.button().classes('solala-tab-button').props('color=white text-color=black') as button:
                    ui.image(tab_def.icon_url).classes('solala-tab-icon').style(
                        f'transform: scale({tab_def.icon_scale}); transform-origin: center;'
                    )
                    ui.label(tab_def.name).classes('text-xs')
                    self.buttons[tab_def.name] = button
                    self.builder[tab_def.name] = tab_def.builder
                    button.on_click(partial(self.select_tab, tab_def.name))

        self.active_tab: Optional[str] = None
        self.active_session: Optional[PageSession] = None
        self.colours: Colours = colours
        self._build_task: Optional[asyncio.Task] = None
        self._transition_lock = asyncio.Lock()

    async def select_tab(self, tab_name: str) -> None:
        async with self._transition_lock:
            if tab_name == self.active_tab:
                return

            await self._close_active_session()
            self.content_container.clear()
            self.active_tab = tab_name

            for name, button in self.buttons.items():
                if name == tab_name:
                    background = rgba(self.colours.tab, alpha=0.15)
                    button.props(f'color="{background}" text-color=black')
                    button.classes(add='solala-tab-button-active')
                else:
                    button.props('color=white text-color=black')
                    button.classes(remove='solala-tab-button-active')

            session = PageSession(self.colours)
            self.active_session = session
            self._build_task = asyncio.create_task(self._build_tab(tab_name, session))

    async def close_active_session(self) -> None:
        async with self._transition_lock:
            await self._close_active_session()

    async def _cancel_active_build(self) -> None:
        task = self._build_task
        self._build_task = None
        if task is None or task.done():
            return

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _close_active_session(self) -> None:
        await self._cancel_active_build()
        if self.active_session is not None:
            session = self.active_session
            self.active_session = None
            await session.close()

    async def _build_tab(self, tab_name: str, session: PageSession) -> None:
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
async def root_page():
    ui.add_head_html(_HEAD_HTML)
    colours: Colours = await css_colours()  # must come directly after add_head_html.

    with ui.element('div').classes('solala-page'):
        _page_header(link=False)

        with ui.element('div').classes('dashboard-card tab-navigation'):
            button_container = ui.grid(columns=3).classes('w-full gap-2')

        content_container = ui.element('div').classes('tab-content w-full')
        tab_selector = TabSelector(colours, button_container, content_container)

    ui.context.client.on_disconnect(tab_selector.close_active_session)
    first_tab_name: str = _TABS[0].name
    await tab_selector.select_tab(first_tab_name)
