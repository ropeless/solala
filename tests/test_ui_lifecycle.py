import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from solala.server.css_colours import Colours
from solala.server.day_navigator import DayNavigator
from solala.server.graphs import PowerChart, EnergyChart
from solala.server.page_session import PageSession, _SessionListener
from solala.server.page_updaters import ChartUpdater


def _test_colours() -> Colours:
    """
    Provide concrete CSS colours for chart construction without a browser.
    """
    return Colours(*(['#123456'] * 10))


def _fake_echart(options: dict) -> MagicMock:
    """
    Capture ECharts options without constructing NiceGUI UI elements.
    """
    chart = MagicMock()
    chart.options = options
    chart.classes.return_value = chart
    return chart


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

        async def propagate(chart: str, selected: dict[str, bool]) -> None:
            for updater in updaters:
                updater.sync_legend(chart, selected)
            await save_legend(chart, selected)

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
            chart = PowerChart(_test_colours()).chart

        chart.options['legend']['selected'] = {}
        selections = {'Solar': False}
        # Exercise the existing chart instance without a running browser.
        chart_wrapper = PowerChart.__new__(PowerChart)
        chart_wrapper.chart = chart
        chart_wrapper.set_selected_series(selections)
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

    async def test_navigator_neighbour_updates_are_session_owned(self) -> None:
        session = PageSession(MagicMock(), AsyncMock())
        navigator = DayNavigator.__new__(DayNavigator)
        navigator._track_task = session.add_task
        started = asyncio.Event()
        finished = asyncio.Event()

        async def update() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

        navigator._schedule_update(update())
        await started.wait()
        await session.close()
        self.assertTrue(finished.is_set())

    async def test_navigator_cancels_task_if_registration_fails(self) -> None:
        navigator = DayNavigator.__new__(DayNavigator)
        tracked_tasks: list[asyncio.Task[None]] = []

        def reject(task: asyncio.Task[None]) -> None:
            tracked_tasks.append(task)
            raise RuntimeError('Session closed')

        navigator._track_task = reject
        ran = False

        async def update() -> None:
            nonlocal ran
            ran = True

        with self.assertRaisesRegex(RuntimeError, 'Session closed'):
            navigator._schedule_update(update())

        await asyncio.sleep(0)
        self.assertEqual(len(tracked_tasks), 1)
        self.assertTrue(tracked_tasks[0].cancelled())
        self.assertFalse(ran)

    async def test_page_session_reports_closed_state(self) -> None:
        session = PageSession(MagicMock(), AsyncMock())
        self.assertFalse(session.closed)
        await session.close()
        self.assertTrue(session.closed)

    async def test_closed_listener_ignores_late_updates(self) -> None:
        underlying = MagicMock()
        underlying.update = AsyncMock()
        listener = _SessionListener(underlying)
        await listener.close()
        await listener.update()
        underlying.update.assert_not_awaited()

    async def test_closing_listener_cancels_inflight_update(self) -> None:
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def update() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        underlying = MagicMock()
        underlying.update = update
        listener = _SessionListener(underlying)
        task = asyncio.create_task(listener.update())
        await started.wait()
        await listener.close()

        self.assertTrue(task.cancelled())
        self.assertTrue(stopped.is_set())


if __name__ == '__main__':
    unittest.main()
