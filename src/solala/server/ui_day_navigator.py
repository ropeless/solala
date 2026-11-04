from datetime import date, timedelta
from typing import Callable, Awaitable, Optional

from nicegui import ui, events

from solala.constants import GUI_DATE_FORMAT


class DayNavigator:

    def __init__(self):
        self._day: date = date.today()
        self._listener: Optional[Callable[[date], Awaitable[None]]] = None

        # Date and navigation row
        with ui.row().classes('items-center gap-2 w-full'):
            # Date
            ui.button(
                icon='calendar_today',
                on_click=self._show_dialog,
            ).props('flat round').style('color: #6b7280 !important')
            self.date_element = ui.label().classes('text-sm w-30 text-gray-500')

            # Previous day
            button_classes = '!w-8 !h-8 min-w-0 shrink-0'

            ui.button(
                icon='chevron_left',
                on_click=lambda: self.change_day(-1),
            ).props('flat round color=primary').classes(
                button_classes
            ).tooltip('Previous day')

            # "today" or "back to today"
            with ui.row().classes(
                    'items-center justify-center gap-0 h-8 w-23'
            ):
                self.day_status = ui.label('today').classes('text-sm text-gray-500')
                self.today_button = ui.button(
                    'back to today',
                    on_click=lambda: self.set_day(date.today()),
                ).props(
                    'flat dense no-caps color=primary'
                ).classes(
                    'text-sm min-h-0 px-0 py-1'
                ).set_visibility(False)

            # Next day
            ui.button(
                icon='chevron_right',
                on_click=lambda: self.change_day(1),
            ).props('flat round color=primary').classes(
                button_classes
            ).tooltip('Next day')

        ui.keyboard(on_key=self._handle_key, repeating=False)

        with ui.dialog() as dialog:
            with ui.card():
                self._date_picker = ui.date(
                    value=self._day.isoformat(),
                    on_change=self._dialog_day_changed,
                )
        self._dialog = dialog

    def set_listener(self, listener: Callable[[date], Awaitable[None]]):
        self._listener = listener

    def configure_swipe_area(self, swipe_area: ui.Area):
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
            self._handle_swipe,
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

    async def change_day(self, delta: int) -> None:
        await self.set_day(self._day + timedelta(days=delta))

    async def set_day(self, day: date) -> None:
        self._day = day
        self.date_element.set_text(day.strftime(GUI_DATE_FORMAT))
        today = date.today()
        self.day_status.set_visibility(day == today)
        self.today_button.set_visibility(day != today)
        if self._listener is not None:
            await self._listener(day)

    async def _show_dialog(self) -> None:
        self._date_picker.value = self._day.isoformat()
        await self._dialog.open()

    async def _dialog_day_changed(self, event: events.ValueChangeEventArguments) -> None:
        if event.value is not None:
            selected_date = date.fromisoformat(event.value)
            await self._dialog.close()
            await self.set_day(selected_date)

    async def _handle_swipe(self, event) -> None:
        direction = event.args
        if direction == 'left':
            await self.change_day(1)
        elif direction == 'right':
            await self.change_day(-1)

    async def _handle_key(self, e: events.KeyEventArguments) -> None:
        if e.action.keydown:
            if e.key.arrow_left:
                await self.change_day(-1)
            elif e.key.arrow_right:
                await self.change_day(1)
            elif e.key.home:
                await self.set_day(date.today())
