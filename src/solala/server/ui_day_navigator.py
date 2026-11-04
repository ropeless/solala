import asyncio
from datetime import date, timedelta
from typing import Callable, Awaitable, List, TypeAlias, Sequence, Dict

from nicegui import ui, events
from nicegui.element import Element

from solala.constants import GUI_DATE_FORMAT

_ONE_DAY = timedelta(days=1)

Listener: TypeAlias = Callable[[date], Awaitable[None]]


class DayNavigator:
    def __init__(self):
        # Set to a valid date but not near today.
        # This is so when `self.set_day(today)` is called, it will cause all updates to happen.
        self._day: date = date(year=1901, month=12, day=31)
        self._slide: int = 0
        self._listeners: Dict[int, Listener] = {}

        # Date and navigation row
        with ui.row().classes('items-center gap-2 w-full'):
            # Date
            ui.button(
                icon='calendar_today',
                on_click=self._show_dialog,
            ).props('flat round').style('color: #6b7280 !important')
            self.date_element = ui.label().classes('text-sm w-30 text-gray-500')

            button_classes = '!w-8 !h-8 min-w-0 shrink-0'

            # Previous day
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
                self.day_status = ui.label('today').classes('text-sm text-gray-500').set_visibility(False)
                self.today_button = ui.button(
                    'back to today',
                    on_click=lambda: self.set_day(date.today()),
                ).props(
                    'flat dense no-caps color=primary'
                ).classes(
                    'text-sm min-h-0 px-0 py-1'
                )

            # Next day
            ui.button(
                icon='chevron_right',
                on_click=lambda: self.change_day(1),
            ).props('flat round color=primary').classes(
                button_classes
            ).tooltip('Next day')

        with ui.carousel(animated=True, arrows=True, navigation=True).props(
                'swipeable'
        ).classes('w-full h-screen') as self._carousel:
            with ui.carousel_slide('0'):
                element_0 = ui.element('div').classes('w-full h-screen')
            with ui.carousel_slide('1'):
                element_1 = ui.element('div').classes('w-full h-screen')
            with ui.carousel_slide('2'):
                element_2 = ui.element('div').classes('w-full h-screen')
        self._elements: List[Element] = [element_0, element_1, element_2]

        self._carousel.on_value_change(self._on_slide_change)
        ui.keyboard(on_key=self._handle_key, repeating=False)

        with ui.dialog(value=False) as dialog:
            with ui.card():
                self._date_picker = ui.date(
                    value=self._day.isoformat(),
                    on_change=self._dialog_day_changed,
                )
        self._dialog = dialog

    def get_elements(self) -> Sequence[Element]:
        """
        What element need a listener to update them
        """
        return tuple(self._elements)

    def set_listeners(self, *listeners: Listener) -> None:
        """
        Set listeners for each element
        """
        if len(listeners) != len(self._elements):
            raise ValueError(f'need {len(listeners)} listeners')
        for i in range(len(self._elements)):
            self._listeners[id(self._elements[i])] = listeners[i]

    async def change_day(self, delta: int) -> None:
        await self.set_day(self._day + timedelta(days=delta))

    async def set_day(self, day: date) -> None:
        day_shift: int = (day - self._day).days
        if day_shift == 0:
            return

        self.date_element.set_text(day.strftime(GUI_DATE_FORMAT))
        today = date.today()
        self.day_status.set_visibility(day == today)
        self.today_button.set_visibility(day != today)

        if day_shift == -1:
            self._rotate_slides(-1)
            asyncio.create_task(self._update_element(self._left_element, day - _ONE_DAY))
        elif day_shift == 1:
            self._rotate_slides(1)
            asyncio.create_task(self._update_element(self._right_element, day + _ONE_DAY))
        else:
            await self._update_element(self._focus_element, day)
            asyncio.create_task(self._update_element(self._left_element, day - _ONE_DAY))
            asyncio.create_task(self._update_element(self._right_element, day + _ONE_DAY))

        self._day = day
        self._slide = self._slide_num

    async def _update_element(self, element: Element, day: date) -> None:
        await self._listeners[id(element)](day)

    @property
    def _slide_num(self) -> int:
        return int(str(self._carousel.value))

    def _rotate_slides(self, delta: int) -> None:
        self._carousel.set_value(str((self._slide_num + delta) % 3))

    @property
    def _left_element(self) -> Element:
        return self._elements[(self._slide_num - 1) % 3]

    @property
    def _focus_element(self) -> Element:
        return self._elements[self._slide_num]

    @property
    def _right_element(self) -> Element:
        return self._elements[(self._slide_num + 1) % 3]

    async def _on_slide_change(self):
        delta: int = self._slide - self._slide_num
        await self.change_day(delta)

    async def _show_dialog(self) -> None:
        cur_date = self._day.isoformat()
        if cur_date != self._date_picker.value:
            # This will cause the dialog to open
            self._date_picker.value = cur_date
            await asyncio.sleep(0)
        else:
            await self._dialog.open()

    async def _dialog_day_changed(self, event: events.ValueChangeEventArguments) -> None:
        if event.value:
            selected_date = date.fromisoformat(event.value)
        else:
            # The picker has cleared its selection.
            selected_date = self._day

        await self._dialog.close()

        if selected_date != self._day:
            await self.set_day(selected_date)

    async def _handle_key(self, e: events.KeyEventArguments) -> None:
        if e.action.keydown:
            if e.key.arrow_left:
                await self.change_day(-1)
            elif e.key.arrow_right:
                await self.change_day(1)
            elif e.key.home:
                await self.set_day(date.today())
