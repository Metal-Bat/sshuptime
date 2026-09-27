import asyncio

import pytest
from textual.widgets import DataTable, Input, RichLog, Static

from sshuptime.app import UptimeApp
from sshuptime.collectors import DemoCollector


async def settled(pilot, app):
    for _ in range(100):
        await pilot.pause(0.02)
        if app.views and not app.busy:
            return
    raise AssertionError("Dashboard did not load")


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(160, 48), (80, 24)])
async def test_inventory_filter_selection_and_controls(size):
    app = UptimeApp(interval=3600)
    async with app.run_test(size=size) as pilot:
        await settled(pilot, app)
        assert len(app.views) == 13
        view = app.views["Docker", "Containers"]
        table = view.query_one(DataTable)
        assert table.row_count == 5
        assert view.selected == "worker-03"
        app.query_one(Input).value = "postgres"
        await pilot.pause()
        assert table.row_count == 1
        assert view.selected == "postgres"
        app.action_clear()
        await pilot.pause()
        app.action_errors()
        assert table.row_count == 1
        app.action_errors()
        app.action_sort()
        assert table.row_count == 5
        app.action_pause()
        assert app.paused
        app.action_refresh()
        await settled(pilot, app)
        assert not app.paused


@pytest.mark.asyncio
async def test_failure_retains_data_and_runtime_discovery_changes():
    class ChangingCollector(DemoCollector):
        fail = False
        minimal = False

        async def snapshot(self):
            if self.fail:
                raise RuntimeError("connection lost")
            result = await super().snapshot()
            if self.minimal:
                result.inventory = {
                    "System": {"Processes": result.inventory["System"]["Processes"]}
                }
            return result

    collector = ChangingCollector()
    app = UptimeApp(collector, interval=3600)
    async with app.run_test() as pilot:
        await settled(pilot, app)
        collector.fail = True
        app.poll()
        await pilot.pause(0.1)
        assert "STALE" in str(app.query_one("#connection", Static).content)
        assert app.views["Docker", "Containers"].query_one(DataTable).row_count == 5
        collector.fail = False
        collector.minimal = True
        app.poll()
        await settled(pilot, app)
        assert list(app.views) == [("System", "Processes")]


@pytest.mark.asyncio
async def test_slow_collector_does_not_overlap():
    class SlowCollector(DemoCollector):
        calls = 0

        async def snapshot(self):
            self.calls += 1
            await asyncio.sleep(0.1)
            return await super().snapshot()

    collector = SlowCollector()
    app = UptimeApp(collector, interval=3600)
    async with app.run_test() as pilot:
        app.poll()
        app.poll()
        await settled(pilot, app)
        assert collector.calls == 1


@pytest.mark.asyncio
async def test_mouse_inspection_json_and_selection_survives_refresh():
    from textual.widgets import TabbedContent

    app = UptimeApp(interval=3600)
    async with app.run_test(size=(140, 42)) as pilot:
        await settled(pilot, app)
        view = app.views["Docker", "Containers"]
        table = view.query_one(DataTable)
        await pilot.click(table, offset=(6, 2))
        assert view.selected == "api-01"
        assert "api-01" in str(view.query_one(".details", Static).content)
        inspector_tabs = view.query_one(TabbedContent)
        inspector_tabs.active = list(inspector_tabs.query("TabPane"))[-1].id
        await pilot.pause()
        assert view.query_one(".manifest", Static).visible
        app.poll()
        await settled(pilot, app)
        assert view.selected == "api-01"
        assert app.query_one("#events").size.height > 0


@pytest.mark.asyncio
async def test_theme_picker_recolors_paused_data_without_losing_selection():
    app = UptimeApp(interval=3600)
    async with app.run_test(size=(140, 42)) as pilot:
        await settled(pilot, app)
        view = app.views["Docker", "Containers"]
        table = view.query_one(DataTable)
        await pilot.click(table, offset=(6, 2))
        app.action_pause()
        events = list(app.event_history)
        original_background = app.screen.styles.background
        await pilot.press("t")
        await pilot.pause()
        await pilot.press("n", "o", "r", "d")
        await pilot.pause(0.3)
        await pilot.press("enter")
        await pilot.pause()
        assert app.theme == "nord"
        assert app.screen.styles.background != original_background
        assert app.paused
        assert view.selected == "api-01"
        assert list(app.event_history) == events
        state_cell = table.get_row("worker-03")[1]
        assert state_cell.style.color is not None
        # Also exercise a light palette without resuming collection.
        dark_state_style = state_cell.style
        app.theme = "textual-light"
        await pilot.pause()
        assert not app.current_theme.dark
        assert table.get_row("worker-03")[1].style != dark_state_style
        assert view.selected == "api-01"


@pytest.mark.asyncio
async def test_all_registered_themes_render_including_ansi():
    app = UptimeApp(interval=3600)
    async with app.run_test() as pilot:
        await settled(pilot, app)
        app.action_pause()
        for theme in app.available_themes:
            app.theme = theme
            await pilot.pause(0.01)
            assert app.views["Docker", "Containers"].query_one(DataTable).row_count == 5


@pytest.mark.asyncio
async def test_host_identity_strip_is_populated_in_compact_view():
    app = UptimeApp(interval=3600)
    async with app.run_test(size=(80, 24)) as pilot:
        await settled(pilot, app)
        assert "atlas-prod-01" in str(app.query_one("#identity-host", Static).content)
        assert "10.42.1.17" in str(app.query_one("#identity-ip", Static).content)
        assert "Debian" in str(app.query_one("#identity-linux", Static).content)
        assert "6.12.0" in str(app.query_one("#identity-kernel", Static).content)
        assert app.query_one("#identity").size.height == 1


@pytest.mark.asyncio
async def test_system_errors_tab_uses_error_columns_and_inspector():
    app = UptimeApp(interval=3600)
    async with app.run_test(size=(140, 42)) as pilot:
        await settled(pilot, app)
        view = app.views["System", "Errors"]
        table = view.query_one(DataTable)
        assert len(table.columns) == 4
        assert [str(column.label) for column in table.columns.values()] == [
            "SOURCE",
            "SEVERITY",
            "TIME",
            "SUMMARY",
        ]
        assert "2026-09-27" in str(table.get_row("journal-demo-1")[2])
        view.selected = "journal-demo-1"
        view.show_resource()
        details = str(view.query_one(".details", Static).content)
        assert "disk I/O retry" in details
        assert "CPU" not in details


@pytest.mark.asyncio
async def test_cron_row_opens_history_and_keeps_job_details():
    from textual.widgets import TabbedContent

    app = UptimeApp(interval=3600)
    async with app.run_test(size=(140, 42)) as pilot:
        await settled(pilot, app)
        view = app.views["System", "Cron"]
        table = view.query_one(DataTable)
        assert [str(column.label) for column in table.columns.values()] == [
            "SCHEDULE",
            "USER",
            "COMMAND",
            "LAST RUN",
        ]
        assert table.row_count == 2
        runtimes = app.query_one("#runtimes", TabbedContent)
        runtimes.active = "runtime-3"
        await pilot.pause()
        runtimes.query_one("#runtime-3").query_one(
            TabbedContent
        ).active = "category-3-3"
        await pilot.pause()
        await pilot.click(table, offset=(5, 1))
        await pilot.pause()
        assert view.query_one(TabbedContent).active == "resource-history"
        assert view.selected == "demo-cron-backup"
        assert "0 2 * * *" in str(view.query_one(".details", Static).content)
        assert "launched by cron" in "\n".join(
            str(line) for line in view.query_one(".logs", RichLog).lines
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(140, 42), (80, 24)])
async def test_clicking_headers_sorts_and_preserves_selection_on_refresh(size):
    app = UptimeApp(interval=3600)
    async with app.run_test(size=size) as pilot:
        await settled(pilot, app)
        view = app.views["Docker", "Containers"]
        table = view.query_one(DataTable)
        assert view.selected == "worker-03"
        await pilot.click(table, offset=(3, 0))
        await pilot.pause()
        assert view.sort_column == 0
        assert next(iter(table.rows)).value == "api-01"
        assert view.selected == "worker-03"
        assert str(next(iter(table.columns.values())).label) == "NAME / PID ▲"
        assert "NAME / PID ▲" in str(view.query_one(".count", Static).content)
        assert "NAME&#160;/&#160;PID&#160;▲" in app.export_screenshot()

        await pilot.click(table, offset=(3, 0))
        await pilot.pause()
        assert next(iter(table.rows)).value == "worker-03"
        assert str(next(iter(table.columns.values())).label) == "NAME / PID ▼"
        assert "NAME / PID ▼" in str(view.query_one(".count", Static).content)
        app.poll()
        await settled(pilot, app)
        assert next(iter(table.rows)).value == "worker-03"
        assert view.selected == "worker-03"


@pytest.mark.asyncio
async def test_header_sort_uses_numeric_cpu_and_memory_and_scopes_to_view():
    from sshuptime.models import Resource

    app = UptimeApp(interval=3600)
    async with app.run_test(size=(140, 42)) as pilot:
        await settled(pilot, app)
        view = app.views["Docker", "Containers"]
        table = view.query_one(DataTable)
        view.update_resources(
            [
                Resource(
                    id="small", name="small", state="running", cpu=9, memory="900 MiB"
                ),
                Resource(
                    id="large", name="large", state="stopped", cpu=12, memory="2 GiB"
                ),
            ]
        )

        def choose(column):
            key = list(table.columns)[column]
            view.sort_by_header(
                DataTable.HeaderSelected(table, key, column, table.columns[key].label)
            )

        choose(2)
        assert [key.value for key in table.rows] == ["large", "small"]
        choose(2)
        assert [key.value for key in table.rows] == ["small", "large"]
        choose(3)
        assert [key.value for key in table.rows] == ["large", "small"]
        assert str(list(table.columns.values())[3].label) == "MEMORY ▼"
        choose(1)
        assert [key.value for key in table.rows] == ["small", "large"]
        assert str(list(table.columns.values())[3].label) == "MEMORY"
        assert str(list(table.columns.values())[1].label) == "STATE ▲"
        choose(1)
        assert [key.value for key in table.rows] == ["large", "small"]
        assert app.views["System", "Processes"].sort_column is None
        app.action_sort()
        assert view.sort_column is None
        assert str(list(table.columns.values())[1].label) == "STATE"


@pytest.mark.asyncio
async def test_cron_and_error_headers_sort_their_visible_fields():
    app = UptimeApp(interval=3600)
    async with app.run_test(size=(140, 42)) as pilot:
        await settled(pilot, app)
        for category, column, first in (
            ("Cron", 3, "demo-cron-backup"),
            ("Errors", 2, "journal-demo-1"),
        ):
            view = app.views["System", category]
            table = view.query_one(DataTable)
            key = list(table.columns)[column]
            view.sort_by_header(
                DataTable.HeaderSelected(table, key, column, table.columns[key].label)
            )
            assert next(iter(table.rows)).value == first
