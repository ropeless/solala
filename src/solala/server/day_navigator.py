import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import date, timedelta

from nicegui import ui, events
from nicegui.element import Element

from solala.constants import GUI_DATE_FORMAT

_ONE_DAY = timedelta(days=1)

type Updater = Callable[[date], Awaitable[None]]

_SENTINEL_DATE: date = date(year=1901, month=12, day=31)  # a valid date but not near today.

_CAROUSEL_PROPS = 'infinite transition-next="slide-left" transition-prev="slide-right"'


class DayNavigator:
    """
    Navigate dated content using three reusable carousel slides.

    The user provides each slide with an asynchronous updater that populates the slide's
    content for the selected, previous, or next day. The carousel supports date-picker,
    button, swipe, and keyboard navigation.
    """
    def __init__(
            self,
            *,
            enable_swipe_content: bool = False,
            enable_swipe_navigator: bool = True,
            enable_arrow_keys: bool = True,
            auto_height: bool = False,
            title: str = ''
    ) -> None:
        """
        Create a carousel of infinite cards, where each card represents a date.

        The navigator consists of a date navigation bar with a content slide below that.

        The navigator works by keeping s ring of three carousel slides. At any point of time
        one slide is the current display day (focus slide) with the other two being the previous
        and next day (left slide and right slide).

        The contents of each slide is maintained by an element "Updater" which is set for a particular
        slide content element and called when required to update its content to a particular day.

        The carousel can be operated either via the IU or programmatically so there is a distinction
        between the slide we last set to the focus slide (self._focus_slide) and the slide currently
        on display (self._display_slide).

        Args:
            enable_swipe_content: Enable horizontal swipes over slide content.
            enable_swipe_navigator: Enable horizontal swipes over the date bar.
            enable_arrow_keys: Enable left arrow, right arrow, and home key navigation.
            auto_height: Allow the carousel to follow its active slide's height.
                Call `initialise_auto_height()` after the client is ready.
            title: Optional heading above the date navigator.
        """

        self._day: date = _SENTINEL_DATE
        self._focus_slide: int = 0
        self._updaters: Sequence[Updater] = ()  # mapping from slide number to `updater`
        self._touch_start_x: float | None = None  # for our own swipe detection
        self._auto_height_id = f'solala-carousel-{id(self)}' if auto_height else None

        with ui.element('div'):
            if title != '':
                ui.label(title).classes('dashboard-card-title')

            # Date and navigation row
            navigator_row = ui.row().classes('items-center gap-2 w-full')
            with navigator_row:
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

        carousel = ui.carousel(animated=True, arrows=True, navigation=False). \
            props(_CAROUSEL_PROPS).classes('w-full')
        if self._auto_height_id is not None:
            carousel.props(f'id={self._auto_height_id}')
        with carousel as self._carousel:
            with ui.carousel_slide('0'):
                element_0 = ui.element('div').classes('w-full')
            with ui.carousel_slide('1'):
                element_1 = ui.element('div').classes('w-full')
            with ui.carousel_slide('2'):
                element_2 = ui.element('div').classes('w-full')
        self._elements: tuple(Element, Element, Element) = (element_0, element_1, element_2)

        self._carousel.on_value_change(self._on_slide_change)
        self._carousel.on('transition', self._on_carousel_transition)

        with ui.dialog(value=False) as dialog:
            with ui.card():
                self._date_picker = ui.date(
                    value=self._day.isoformat(),
                    on_change=self._dialog_day_changed,
                )
        self._dialog = dialog

        if enable_swipe_content:
            self._add_swipe_handler(self._carousel)
        if enable_swipe_navigator:
            self._add_swipe_handler(navigator_row)

        if enable_arrow_keys:
            ui.keyboard(on_key=self._handle_key, repeating=False)

    async def initialise_auto_height(self) -> None:
        """
        Install browser observers to follow the active slide's content height.

        Has no effect when `auto_height` was disabled at construction.
        """
        if self._auto_height_id is None:
            return

        await ui.run_javascript(f"""
            (() => {{
                const carousel = document.getElementById('{self._auto_height_id}');
                if (!carousel || carousel.dataset.autoHeightInitialised) return;
                carousel.dataset.autoHeightInitialised = 'true';
                const panel = () => carousel.querySelector('.q-panel');
                const updateHeight = () => {{
                    const currentPanel = panel();
                    if (!currentPanel) return;
                    const slide = currentPanel.querySelector('.q-carousel__slide');
                    if (!slide) return;
                    const contentHeight = Math.ceil(slide.scrollHeight);
                    const controls = carousel.querySelector('.q-carousel__navigation');
                    const controlsHeight = controls ? Math.ceil(controls.getBoundingClientRect().height) + 12 : 0;
                    carousel.style.height = (contentHeight + controlsHeight) + 'px';
                    currentPanel.style.height = 'auto';
                    currentPanel.style.overflow = 'visible';
                }};
                const resizeObserver = new ResizeObserver(() => requestAnimationFrame(updateHeight));
                const observe = () => {{
                    const currentPanel = panel();
                    const slide = currentPanel?.querySelector('.q-carousel__slide');
                    if (currentPanel) resizeObserver.observe(currentPanel);
                    if (slide) resizeObserver.observe(slide);
                    updateHeight();
                }};
                const mutationObserver = new MutationObserver(() => requestAnimationFrame(observe));
                mutationObserver.observe(carousel, {{subtree: true, childList: true, attributes: true, attributeFilter: ['class']}});
                observe();
            }})();
        """)

    def get_elements(self) -> tuple[Element, Element, Element]:
        """
        Return the three slide content elements in updater order.

        Returns:
            Elements coindexed with the callbacks passed to `set_listeners()`.
        """
        return self._elements

    def set_listeners(self, *listeners: Updater) -> None:
        """
        Register one asynchronous updater for each slide content element.

        Args:
            listeners: Three callbacks coindexed with `get_elements()`.
                Each callback receives the date its slide should display.

        Raises:
            ValueError: If the number of callbacks is not three.
        """
        if len(listeners) != len(self._elements):
            raise ValueError(f'need {len(listeners)} listeners')
        self._updaters = tuple(listeners)

    async def change_day(self, delta: int) -> None:
        """
        Navigate relative to the currently selected date.

        Args:
            delta: Number of days to move; negative values move backwards.
        """
        await self.set_day(self._day + timedelta(days=delta))

    async def set_day(self, day: date) -> None:
        """
        Select a date and refresh the required carousel slides.

        Adjacent dates reuse the existing slides; larger jumps refresh all
        three. Neighbouring slide refreshes are scheduled asynchronously.

        Args:
            day: Date to display.
        """
        # This is how many days are being requested to change from the current day.
        # If this is -1, 0, or +1 then there is not much to do. Otherwise, we
        # will need to change all three slides.
        day_shift: int = (day - self._day).days

        # The user may have already changed the slide, keep a note of that
        vis_delta: int = ((self._display_slide - self._focus_slide + 1) % 3) - 1

        # Update the navigator state
        self.date_element.set_text(day.strftime(GUI_DATE_FORMAT))
        today = date.today()
        self.day_status.set_visibility(day == today)
        self.today_button.set_visibility(day != today)
        self._day = day

        # Update the carousel state

        if day_shift == 0:
            # The focus slide is the day being requested
            if vis_delta != 0:
                # Somehow we being requested to keep the current focus slide but
                # visually there has been a change. We just change the visual slide back.
                self._set_display_slide(self._focus_slide)
            # Nothing more to do
            return

        if day_shift == -1:
            self._focus_slide = self._left_slide()
            self._set_display_slide(self._focus_slide)
            asyncio.create_task(self._update_element(self._left_slide(), day - _ONE_DAY))

        elif day_shift == 1:
            self._focus_slide = self._right_slide()
            self._set_display_slide(self._focus_slide)
            asyncio.create_task(self._update_element(self._right_slide(), day + _ONE_DAY))

        else:
            # Just recreate all three slides
            await self._update_element(self._focus_slide, day)
            asyncio.create_task(self._update_element(self._right_slide(), day + _ONE_DAY))
            asyncio.create_task(self._update_element(self._left_slide(), day - _ONE_DAY))

    def _add_swipe_handler(self, element: Element) -> None:
        element.on(
            'touchstart',
            self._on_touch_start,
            js_handler='(e) => emit(e.touches[0]?.clientX ?? null)',
        )
        element.on(
            'touchend',
            self._on_touch_end,
            js_handler='(e) => emit(e.changedTouches[0]?.clientX ?? null)',
        )
        element.on(
            'touchcancel',
            lambda _: setattr(self, '_touch_start_x', None),
        )

    @property
    def _display_slide(self) -> int:
        """
        Return the slide index currently shown by the carousel.
        """
        return int(str(self._carousel.value))

    def _set_display_slide(self, slide: int) -> None:
        """
        Navigate visually to a slide without changing the selected date.

        Args:
            slide: Index of the slide to display.
        """
        match self._display_slide, slide:
            case 0, 1:
                self._carousel_next()
            case 0, 2:
                self._carousel_previous()
            case 1, 2:
                self._carousel_next()
            case 1, 0:
                self._carousel_previous()
            case 2, 0:
                self._carousel_next()
            case 2, 1:
                self._carousel_previous()

    def _carousel_next(self) -> None:
        self._carousel.props('infinite transition-next="slide-left" transition-prev="slide-left"')
        self._carousel.next()

    def _carousel_previous(self) -> None:
        self._carousel.props('infinite transition-next="slide-right" transition-prev="slide-right"')
        self._carousel.previous()

    def _left_slide(self) -> int:
        """
        Return the slide index preceding the focus slide.
        """
        return (self._focus_slide - 1) % 3

    def _right_slide(self) -> int:
        """
        Return the slide index following the focus slide.
        """
        return (self._focus_slide + 1) % 3

    async def _update_element(self, slide_number: int, day: date) -> None:
        """
        Invoke the registered updater for a slide, if available.

        Args:
            slide_number: Index of the slide content element to update.
            day: Date that the slide should display.
        """
        if len(self._updaters) == 0:
            # updaters not yet set
            return
        updater: Updater = self._updaters[slide_number]
        await updater(day)

    async def _on_slide_change(self) -> None:
        """
        Handle carousel changes initiated by the user or by code.

        Only a change away from the focus slide triggers date navigation.
        """
        delta: int = ((self._display_slide - self._focus_slide + 1) % 3) - 1
        if delta != 0:
            # The user changed the slide we need to react.
            await self.change_day(delta)

    def _on_touch_start(self, e: events.GenericEventArguments) -> None:
        self._touch_start_x = e.args

    def _on_touch_end(self, e: events.GenericEventArguments) -> None:
        if self._touch_start_x is None or e.args is None:
            return

        delta = float(e.args) - self._touch_start_x
        self._touch_start_x = None

        # Ignore short movements
        if abs(delta) < 50:
            return

        if delta < 0:
            self._carousel_next()
        else:
            self._carousel_previous()

    def _on_carousel_transition(self, _: events.GenericEventArguments) -> None:
        # Restore default carousel props
        self._carousel.props(_CAROUSEL_PROPS)

    async def _show_dialog(self) -> None:
        """
        Open the date picker, synchronising its value with the selected day.
        """
        cur_date = self._day.isoformat()
        if cur_date != self._date_picker.value:
            # This will cause the dialogue to open
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
            if e.key.arrow_right:
                self._carousel_next()
            elif e.key.arrow_left:
                self._carousel_previous()
            elif e.key.home:
                await self.set_day(date.today())
