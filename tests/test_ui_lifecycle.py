import asyncio
import unittest
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from solala.control.modes_and_policies import ControlMode, InverterMode, InverterPolicy
from solala.delegates.power_pricer.price import Price
from solala.server.css_colours import Colours
from solala.server.day_navigator import DayNavigator
from solala.server.graphs import PowerChart, EnergyChart
from solala.server.page_session import PageSession
from solala.server.page_updaters import (
    ChartUpdater, InverterButtonUpdater, PriceForecastUpdater, SolarForecastUpdater, StatusUpdater,
)
from solala.utils.json_extras import JSONValue


def _test_colours() -> Colours:
    """
    Provide concrete CSS colours for chart construction without a browser.
    """
    return Colours(*(['#123456'] * 10))


def _fake_echart(options: dict[str, JSONValue]) -> MagicMock:
    """
    Capture ECharts options without constructing NiceGUI UI elements.
    """
    chart = MagicMock()
    chart.options = options
    chart.classes.return_value = chart
    return chart


class InverterButtonTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Verify selection and status updates for the fixed-limit mode button.
    """

    async def test_fixed_limit_button_selects_manual_mode(self) -> None:
        fixed_limit = MagicMock()
        fixed_limit.text = 'FIXED LIMIT'
        zero_export = MagicMock()
        zero_export.text = 'ZERO EXPORT'
        policy = MagicMock()
        policy.text = 'NEG FEED-IN ⇒ ZERO EXPORT'
        updater = InverterButtonUpdater(
            {InverterMode.FIXED_LIMIT: fixed_limit, InverterMode.ZERO_EXPORT: zero_export},
            {InverterPolicy.NEG_FEED_IN_ZERO_EXPORT: policy},
        )
        click = fixed_limit.on_click.call_args.args[0]

        with patch('solala.server.page_updaters.control_loop.set_control', new_callable=AsyncMock) as set_control:
            await click()

        set_control.assert_awaited_once_with(
            inverter_mode=InverterMode.FIXED_LIMIT, inverter_policy=InverterPolicy.MANUAL,
        )
        fixed_limit.props.assert_called_with('color=blue')

        control = ControlMode(inverter_mode=InverterMode.FIXED_LIMIT, fixed_limit_pct=37.125)
        status = control.to_json()
        parameter = status['parameter']
        assert isinstance(parameter, dict)
        self.assertEqual(parameter['fixed_limit_pct'], 37.125)
        with patch('solala.server.page_updaters.control_loop.get_control_mode', return_value=control):
            await updater.update()
            fixed_limit.props.assert_called_with('color=blue')
            fixed_limit.props.set_optional.assert_called_with('aria-label', 'FIXED LIMIT, selected')
            policy.props.assert_called_with('color=grey-6')

            control.inverter_mode = InverterMode.ZERO_EXPORT
            control.inverter_policy = InverterPolicy.NEG_FEED_IN_ZERO_EXPORT
            await updater.update()
            fixed_limit.props.assert_called_with('color=grey-6')
            zero_export.props.assert_called_with('color=grey-7')
            zero_export.props.set_optional.assert_called_with('aria-label', 'ZERO EXPORT, selected by policy')
            policy.props.assert_called_with('color=blue')
            policy.props.set_optional.assert_called_with('aria-label', 'NEG FEED-IN ⇒ ZERO EXPORT, selected')

            control.inverter_policy = InverterPolicy.MANUAL
            await updater.update()
            zero_export.props.set_optional.assert_called_with('aria-label', 'ZERO EXPORT, selected')
            policy.props.set_optional.assert_called_with('aria-label', None)

            control.inverter_mode = InverterMode.FIXED_LIMIT
            await updater.update()
            zero_export.props.set_optional.assert_called_with('aria-label', None)


class GraphLegendTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Check native chart event registration and legend propagation.
    """

    async def test_echarts_legend_event_is_forwarded(self) -> None:
        on_change = AsyncMock()

        with patch('solala.server.graphs.ui.echart', side_effect=_fake_echart):
            power = PowerChart(_test_colours(), {'Solar': False}, on_change)
        chart = power.chart

        options = chart.options
        self.assertEqual(options['legend']['selected'], {'Solar': False})
        chart.on.assert_called_once()
        event_name, handler = chart.on.call_args.args
        self.assertEqual(event_name, 'chart:legendselectchanged')

        selected = {'Solar': True, 'Forecast': False}
        await handler(SimpleNamespace(args={'type': 'legendselectchanged', 'selected': selected}))
        on_change.assert_awaited_once_with('Power', selected)

    async def test_one_slide_updates_shared_state_and_all_slides(self) -> None:
        shared: dict[str, dict[str, bool]] = {}
        save_legend = AsyncMock()
        session = SimpleNamespace(graph_series=shared, on_legend_change=None, closed=False)
        updaters = [ChartUpdater.__new__(ChartUpdater) for _ in range(3)]
        for updater in updaters:
            updater._session = session
            updater._power_chart = MagicMock()
            updater._energy_chart = MagicMock()

        async def propagate(chart: str, selection: dict[str, bool]) -> None:
            """
            Apply the shared legend selection to every slide and persist it.
            """
            for slide in updaters:
                slide.sync_legend(chart, selection)
            await save_legend(chart, selection)

        session.on_legend_change = propagate
        selected = {'Solar': False, 'Forecast': True}
        await updaters[1]._legend_changed('Power', selected)

        self.assertEqual(shared['Power'], selected)
        for updater in updaters:
            updater._power_chart.set_selected_series.assert_called_once_with(selected)
            updater._energy_chart.set_selected_series.assert_not_called()
        save_legend.assert_awaited_once_with('Power', selected)

        await updaters[2]._legend_changed('Energy', {'Import': False})
        self.assertEqual(shared['Energy'], {'Import': False})
        for updater in updaters:
            updater._energy_chart.set_selected_series.assert_called_once_with({'Import': False})

    async def test_late_legend_change_does_not_modify_shared_state(self) -> None:
        shared = {'Power': {'Solar': True}}
        persist = AsyncMock()
        session = SimpleNamespace(graph_series=shared, on_legend_change=persist, closed=True)
        updater = ChartUpdater.__new__(ChartUpdater)
        updater._session = session

        await updater._legend_changed('Power', {'Solar': False})

        self.assertEqual(shared, {'Power': {'Solar': True}})
        persist.assert_not_awaited()

    def test_synchronising_chart_updates_legend_options(self) -> None:
        with patch('solala.server.graphs.ui.echart', side_effect=_fake_echart):
            power = PowerChart(_test_colours())

        chart = power.chart
        selections = {'Solar': False}
        power.set_selected_series(selections)
        self.assertEqual(chart.options['legend']['selected'], selections)
        chart.update.assert_called_once()

    def test_restored_selections_applied_to_energy_chart(self) -> None:
        with patch('solala.server.graphs.ui.echart', side_effect=_fake_echart):
            chart = EnergyChart(_test_colours(), {'Import': False}, AsyncMock()).chart

        self.assertEqual(chart.options['legend']['selected'],
                         {'Import': False})


class PageLifecycleTestCase(unittest.IsolatedAsyncioTestCase):
    """
    Ensure page-owned work is stopped before UI resources are discarded.
    """

    async def test_failed_price_refresh_drains_sibling_before_pending_refresh(self) -> None:
        """
        Verify a failed price fetch drains the sibling read before retrying.
        """
        await self._assert_price_refresh_drains_sibling(ValueError('fetch failed'))

    async def test_invalidated_price_refresh_drains_sibling_before_pending_refresh(self) -> None:
        """
        Verify an invalidated price forecast preserves the queued refresh.
        """
        await self._assert_price_refresh_drains_sibling(asyncio.CancelledError())

    async def test_invalidated_status_price_read_preserves_pending_refresh(self) -> None:
        """
        Verify a status rerun waits for cancellation of the interrupted snapshot.
        """
        session = PageSession(_test_colours(), AsyncMock())
        self.addAsyncCleanup(session.close)
        updater = StatusUpdater(MagicMock())
        power_started = asyncio.Event()
        power_stopped = asyncio.Event()
        invalidate = asyncio.Event()
        release_power = asyncio.Event()
        stopped_before_retry: list[bool] = []
        power = MagicMock()
        power.to_json.return_value = {'power': 100}
        price = MagicMock()
        price.to_json.return_value = {'price': 25}

        async def get_power() -> MagicMock:
            """
            Block the first power read and record when it stops relative to the retry.
            """
            if power_started.is_set():
                stopped_before_retry.append(power_stopped.is_set())
                return power
            power_started.set()
            try:
                await release_power.wait()
            finally:
                power_stopped.set()
            return power

        async def get_price() -> MagicMock:
            """
            Simulate current-price cache invalidation during the first read.
            """
            if not invalidate.is_set():
                await invalidate.wait()
                raise asyncio.CancelledError()
            return price

        with (
            patch('solala.control.control_loop.get_control_mode', return_value=ControlMode()),
            patch('solala.control.control_loop.get_power_status', side_effect=get_power),
            patch('solala.control.control_loop.get_price_now', side_effect=get_price),
            patch('solala.control.control_loop.get_consumers_status', return_value={}),
            patch('solala.server.page_session.LOGGER') as logger,
            patch.object(updater, '_update') as render,
        ):
            first = session.refresh(updater)
            try:
                await asyncio.wait_for(power_started.wait(), timeout=2)
                await session.refresh(updater)
                invalidate.set()
                await asyncio.wait_for(first, timeout=2)
                self.assertEqual(stopped_before_retry, [True])
            finally:
                invalidate.set()
                release_power.set()
                if power_started.is_set():
                    await asyncio.wait_for(power_stopped.wait(), timeout=2)

        logger.exception.assert_called_once()
        render.assert_called_once_with({
            'control': ControlMode().to_json(),
            'power': {'power': 100},
            'price': {'price': 25},
        })

    async def _assert_price_refresh_drains_sibling(self, failure: BaseException) -> None:
        """
        Check that the queued refresh starts only after the blocked sibling stops.
        """
        session = PageSession(_test_colours(), AsyncMock())
        self.addAsyncCleanup(session.close)
        updater = PriceForecastUpdater(MagicMock())
        started = asyncio.Event()
        stopped = asyncio.Event()
        allow_failure = asyncio.Event()
        release_fetch = asyncio.Event()
        stopped_before_retry: list[bool] = []

        async def fetch_prices() -> list[Price]:
            """
            Raise the supplied failure after the test queues a second refresh.
            """
            if not allow_failure.is_set():
                await allow_failure.wait()
                raise failure
            return []

        async def fetch_demand_window(_day: date) -> None:
            """
            Block the first demand read and record whether it stops before the retry.
            """
            if started.is_set():
                stopped_before_retry.append(stopped.is_set())
                return
            started.set()
            try:
                await release_fetch.wait()
            finally:
                stopped.set()

        with (
            patch('solala.server.page_updaters.control_loop.get_price_forecast', side_effect=fetch_prices),
            patch('solala.server.page_updaters.control_loop.get_demand_window', side_effect=fetch_demand_window),
            patch('solala.server.page_session.LOGGER') as logger,
            patch.object(updater, '_update') as render,
        ):
            first = session.refresh(updater)
            try:
                await asyncio.wait_for(started.wait(), timeout=2)
                await session.refresh(updater)
                allow_failure.set()
                await asyncio.wait_for(first, timeout=2)
                self.assertEqual(stopped_before_retry, [True])
            finally:
                allow_failure.set()
                release_fetch.set()
                if started.is_set():
                    await asyncio.wait_for(stopped.wait(), timeout=2)
        logger.exception.assert_called_once()
        render.assert_called_once_with([], None)

    async def test_price_forecast_retries_rendering_cached_data(self) -> None:
        """
        Verify a failed render retries with the same cached prices.
        """
        session = PageSession(_test_colours(), AsyncMock())
        updater = PriceForecastUpdater(MagicMock())
        forecast = [MagicMock()]
        self.addAsyncCleanup(session.close)
        with (
            patch('solala.server.page_updaters.control_loop.get_price_forecast', return_value=forecast),
            patch('solala.server.page_updaters.control_loop.get_demand_window', return_value=None),
            patch('solala.server.page_session.LOGGER') as logger,
            patch.object(updater, '_update', side_effect=[ValueError('render failed'), None]) as render,
        ):
            await session.refresh(updater)
            await session.refresh(updater)
            await session.refresh(updater)
        logger.exception.assert_called_once()
        self.assertEqual(render.call_count, 2)
        render.assert_called_with(forecast, None)

    async def test_price_forecast_redraws_when_only_demand_window_changes(self) -> None:
        """
        Verify demand highlights update while the forecast object stays the same.
        """
        session = PageSession(_test_colours(), AsyncMock())
        self.addAsyncCleanup(session.close)
        updater = PriceForecastUpdater(MagicMock())
        forecast = [MagicMock()]
        start = datetime(2026, 11, 26, 15, tzinfo=UTC)
        end = start + timedelta(hours=1)
        window = (start, end)
        with (
            patch('solala.server.page_updaters.control_loop.get_price_forecast', return_value=forecast),
            patch('solala.server.page_updaters.control_loop.get_demand_window',
                  side_effect=[None, window, (start, end), None]),
            patch.object(updater, '_update') as render,
        ):
            for _ in range(4):
                await session.refresh(updater)

        self.assertEqual(render.call_args_list, [call(forecast, None), call(forecast, window), call(forecast, None)])

    async def test_solar_forecast_retries_rendering_cached_data(self) -> None:
        """
        Verify a failed render retries with the same cached solar forecast.
        """
        session = PageSession(_test_colours(), AsyncMock())
        with patch.object(SolarForecastUpdater, '_show_loading'):
            updater = SolarForecastUpdater(MagicMock(), session)
        forecast = MagicMock()
        self.addAsyncCleanup(session.close)
        with (
            patch('solala.server.page_updaters.control_loop.get_solar_forecast', return_value=forecast),
            patch('solala.server.page_session.LOGGER') as logger,
            patch.object(updater, '_update', side_effect=[ValueError('render failed'), None]) as render,
        ):
            await session.refresh(updater)
            await session.refresh(updater)
            await session.refresh(updater)
        logger.exception.assert_called_once()
        self.assertEqual(render.call_count, 2)
        render.assert_called_with(forecast)

    async def test_graph_discards_refresh_for_superseded_day(self) -> None:
        """
        Verify only the current date is rendered after an overlapping selection.
        """
        first_day = date(2026, 11, 26)
        next_day = date(2026, 11, 27)
        started = asyncio.Event()
        release = asyncio.Event()
        updater = ChartUpdater.__new__(ChartUpdater)
        session = PageSession(_test_colours(), AsyncMock())
        updater._session = session
        updater._day = first_day
        updater._day_revision = 0
        first_result = MagicMock()
        next_result = MagicMock()

        async def get_data() -> MagicMock:
            """
            Block the old date's data until the new date is selected.
            """
            if updater.day == first_day:
                started.set()
                await release.wait()
                return first_result
            return next_result

        with (
            patch.object(updater, '_get_data', side_effect=get_data),
            patch.object(updater, '_show_loading'),
            patch.object(updater, '_update') as render,
        ):
            first = session.refresh(updater)
            await started.wait()
            try:
                updater.set_day(next_day)
                await asyncio.sleep(0)
                self.assertFalse(render.called)
                release.set()
                await first
                render.assert_called_once_with(next_result)
            finally:
                await session.close()

    async def test_session_closes_background_tasks_and_cleanup_once(self) -> None:
        session = PageSession(MagicMock(), AsyncMock())
        started = asyncio.Event()
        cancelled = asyncio.Event()
        cleanup = MagicMock()

        async def background() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        task = asyncio.create_task(background())
        session.add_task(task)
        session.add_cleanup(cleanup)
        await started.wait()
        await session.close()

        self.assertTrue(task.cancelled())
        self.assertTrue(cancelled.is_set())
        cleanup.assert_called_once_with()
        await session.close()
        cleanup.assert_called_once_with()

    async def test_navigator_keeps_slides_aligned_while_first_save_waits(self) -> None:
        """
        Verify the carousel stays aligned across overlapping selections and saves.
        """
        today = date(2026, 11, 26)
        one_day = timedelta(days=1)
        tomorrow = today + one_day
        final_day = tomorrow + one_day
        assigned = [today, tomorrow, today - one_day]
        save_started = asyncio.Event()
        release_save = asyncio.Event()
        navigator = DayNavigator.__new__(DayNavigator)
        navigator._day = today
        navigator._focus_slide = 0
        carousel = MagicMock()
        carousel.value = 0
        navigator._carousel = carousel

        async def save_day(day: date) -> None:
            """
            Pause persistence of the first date selection.
            """
            if day == tomorrow:
                save_started.set()
                await release_save.wait()

        def slide_updater(index: int) -> Callable[[date], None]:
            """
            Return a callback that records the date assigned to a slide.
            """
            def assign(day: date) -> None:
                """
                Record the selected date for this callback's slide.
                """
                assigned[index] = day

            return assign

        def display(slide: int) -> None:
            """
            Reflect a visible-slide change in the fake carousel.
            """
            carousel.value = slide

        navigator._on_day_change = save_day
        navigator._updaters = tuple(slide_updater(index) for index in range(3))
        with patch.object(navigator, 'refresh_day_label'), patch.object(navigator, '_set_display_slide', display):
            first = asyncio.create_task(navigator.set_day(tomorrow))
            await save_started.wait()
            try:
                self.assertEqual(assigned[navigator._focus_slide], tomorrow)
                await navigator.set_day(final_day)
            finally:
                release_save.set()
                await first

        self.assertEqual(navigator._day, final_day)
        self.assertEqual(navigator._display_slide, navigator._focus_slide)
        self.assertEqual(assigned[navigator._focus_slide], final_day)
        self.assertEqual(assigned[navigator._left_slide()], final_day - one_day)
        self.assertEqual(assigned[navigator._right_slide()], final_day + one_day)

    async def test_navigator_date_jump_takes_precedence_over_pending_swipe(self) -> None:
        """
        Verify a pending swipe cannot move the carousel after a date jump.
        """
        selected_day = date(2026, 12, 10)
        navigator = DayNavigator.__new__(DayNavigator)
        navigator._day = date(2026, 11, 26)
        navigator._focus_slide = 0
        save_day = AsyncMock()
        navigator._on_day_change = save_day
        left, focus, right = MagicMock(), MagicMock(), MagicMock()
        navigator._updaters = (focus, right, left)
        carousel = MagicMock()
        carousel.value = 1
        navigator._carousel = carousel

        def show_previous_slide() -> None:
            """
            Move the fake carousel back to its focused slide.
            """
            carousel.value = 0

        carousel.previous.side_effect = show_previous_slide
        with patch.object(navigator, 'refresh_day_label'):
            await navigator.set_day(selected_day)
            await navigator._on_slide_change()

        self.assertEqual(navigator._day, selected_day)
        self.assertEqual(navigator._display_slide, navigator._focus_slide)
        save_day.assert_awaited_once_with(selected_day)
        focus.assert_called_once_with(selected_day)
        left.assert_called_once_with(selected_day - timedelta(days=1))
        right.assert_called_once_with(selected_day + timedelta(days=1))

    async def test_page_session_reports_closed_state(self) -> None:
        session = PageSession(MagicMock(), AsyncMock())
        self.assertFalse(session.closed)
        await session.close()
        self.assertTrue(session.closed)

    async def test_closed_listener_ignores_late_updates(self) -> None:
        class Listener:
            calls = 0

            async def update(self) -> None:
                """
                Count calls so unexpected updates after closure are visible.
                """
                self.calls += 1

        session = PageSession(_test_colours(), AsyncMock())
        listener = Listener()
        queued = session.refresh(listener)
        await session.close()
        await queued
        self.assertEqual(listener.calls, 0)

    async def test_closing_listener_cancels_inflight_update(self) -> None:
        started = asyncio.Event()
        stopped = asyncio.Event()

        class Listener:
            @staticmethod
            async def update() -> None:
                """
                Wait until closure cancels the update, then signal completion.
                """
                started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

        session = PageSession(_test_colours(), AsyncMock())
        task = session.refresh(Listener())
        await started.wait()
        await session.close()

        self.assertTrue(task.cancelled())
        self.assertTrue(stopped.is_set())


if __name__ == '__main__':
    unittest.main()
