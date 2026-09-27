"""Live terminal dashboard; data collection is injected at the boundary."""

import asyncio
import re
from collections import deque
from datetime import UTC, datetime
from typing import ClassVar

from rich.json import JSON
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.theme import Theme
from textual.widgets import (
    DataTable,
    Footer,
    Input,
    Label,
    RichLog,
    Sparkline,
    Static,
    TabbedContent,
    TabPane,
)

from .collectors import DemoCollector
from .models import CategoryView, Collector, FieldName, Resource, Snapshot
from .presentation import default_view
from .themes import DEFAULT_THEME, OBSERVATORY, text_style

BAD = {"crashed", "failed", "error", "notready", "unhealthy"}
GOOD = {"running", "active", "ready", "mounted", "registered"}
MEMORY_UNITS = {"B": 1, "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3, "TIB": 1024**4}


def memory_bytes(value: str) -> float:
    """Convert displayed binary memory sizes for numeric table sorting."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([KMGT]?i?B)\s*", value, re.IGNORECASE)
    if match is None:
        return -1
    unit = (
        match.group(2)
        .upper()
        .replace("KB", "KIB")
        .replace("MB", "MIB")
        .replace("GB", "GIB")
        .replace("TB", "TIB")
    )
    return float(match.group(1)) * MEMORY_UNITS.get(unit, 1)


def field_value(
    resource: Resource, field: FieldName, *, for_sort: bool = False
) -> str | float:
    """Read one display field from a resource without runtime-specific UI code."""
    if field in {"time", "summary"}:
        when, separator, summary = resource.info.partition(" · ")
        return (
            (when if separator else "—")
            if field == "time"
            else (summary if separator else resource.info)
        )
    if field == "cpu":
        return resource.cpu
    if field == "memory":
        return memory_bytes(resource.memory) if for_sort else resource.memory
    if field == "command":
        return (
            str(resource.manifest.get("command", resource.name))
            if for_sort
            else resource.name
        )
    if field in {"schedule", "user", "last_run"}:
        value = str(resource.manifest.get(field, "—"))
        return "" if for_sort and value == "—" else value
    return str(getattr(resource, field))


class Inventory(Horizontal):
    """Scrollable inventory with a persistent selection and live inspector."""

    def __init__(
        self, category: str, presentation: CategoryView | None = None, **kwargs
    ):
        super().__init__(**kwargs)
        self.category = category
        self.presentation = presentation or default_view(category)
        self.resources: dict[str, Resource] = {}
        self.selected: str | None = None
        self.filter_text = ""
        self.errors_only = False
        self.sort_cpu = False
        self.sort_column: int | None = None
        self.sort_descending = False
        self.headers = tuple(column.title for column in self.presentation.columns)

    def compose(self) -> ComposeResult:
        with Vertical(classes="inventory-list"):
            yield Label(self.category.upper(), classes="block-title")
            yield DataTable(cursor_type="row", zebra_stripes=True)
            yield Static("", classes="count")
        with Vertical(classes="inspector"):
            yield Label("INSPECTOR / select a row", classes="block-title")
            with TabbedContent():
                with TabPane("Details"), VerticalScroll():
                    yield Static("No selection", classes="details", markup=False)
                with TabPane(
                    self.presentation.history_title,
                    id="resource-history",
                ):
                    yield RichLog(
                        classes="logs", wrap=False, markup=False, max_lines=1000
                    )
                with TabPane("JSON"), VerticalScroll():
                    yield Static("{}", classes="manifest")

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns(*self.headers)

    def update_resources(self, resources: list[Resource]) -> None:
        self.resources = {r.id: r for r in resources}
        self.render_rows()

    def render_rows(self) -> None:
        table = self.query_one(DataTable)
        rows = [
            r
            for r in self.resources.values()
            if self.filter_text.casefold()
            in f"{r.name} {r.id} {r.state} {r.info}".casefold()
            and (not self.errors_only or r.state.lower() in BAD)
        ]
        sort_column = self.sort_column
        if sort_column is not None:
            rows.sort(
                key=lambda r: self.sort_value(r, sort_column),
                reverse=self.sort_descending,
            )
        else:
            rows.sort(
                key=lambda r: (
                    -r.cpu
                    if self.sort_cpu
                    else (r.state.lower() not in BAD, r.name.casefold())
                )
            )
        keys = [r.id for r in rows]
        old_keys = [str(k.value) for k in table.rows]
        if old_keys != keys:
            table.clear()
            for r in rows:
                table.add_row(*self.cells(r), key=r.id)
            if self.selected in keys:
                table.move_cursor(row=keys.index(self.selected), animate=False)
            else:
                self.selected = keys[0] if keys else None
        else:
            for r in rows:
                for column, value in zip(table.columns, self.cells(r)):
                    table.update_cell(r.id, column, value)
        order = ""
        if self.sort_column is not None:
            label = self.headers[self.sort_column]
            order = f" · {label} {'▼' if self.sort_descending else '▲'}"
        self.query_one(".count", Static).update(
            f" {len(rows)} visible / {len(self.resources)} total{order} · Click header to sort"
        )
        self.show_resource()

    def sort_value(self, resource: Resource, column: int) -> str | float:
        """Use the underlying value for each visible column, not its styled cell."""
        value = field_value(
            resource, self.presentation.columns[column].field, for_sort=True
        )
        return value.casefold() if isinstance(value, str) else value

    @on(DataTable.HeaderSelected)
    def sort_by_header(self, event: DataTable.HeaderSelected) -> None:
        column = event.column_index
        if self.sort_column == column:
            self.sort_descending = not self.sort_descending
        else:
            self.sort_column = column
            self.sort_descending = self.presentation.columns[column].descending_first
        self.update_sort_headers()

    def update_sort_headers(self) -> None:
        """Show the active direction in its header and redraw cached table cells."""
        table = self.query_one(DataTable)
        for index, (column, title) in enumerate(
            zip(table.columns.values(), self.headers)
        ):
            arrow = (
                f" {'▼' if self.sort_descending else '▲'}"
                if index == self.sort_column
                else ""
            )
            column.label = Text(f"{title}{arrow}")
        table.clear()
        self.render_rows()

    def cells(self, r: Resource) -> tuple:
        role = (
            "text-error"
            if r.state.lower() in BAD
            else "text-success"
            if r.state.lower() in GOOD
            else "text-warning"
        )
        cells = []
        for column in self.presentation.columns:
            value = field_value(r, column.field)
            if column.field == "state":
                cells.append(Text(f"● {value}", style=text_style(self.app, role)))
            elif column.field == "cpu":
                cells.append(f"{value:.1f}")
            else:
                cells.append(Text(str(value)))
        return tuple(cells)

    @on(DataTable.RowHighlighted)
    def select_resource(self, event) -> None:
        self.selected = str(event.row_key.value)
        self.show_resource()

    @on(DataTable.RowSelected)
    def open_resource(self, event) -> None:
        self.select_resource(event)
        if self.presentation.details == "cron":
            self.query_one(TabbedContent).active = "resource-history"

    def show_resource(self) -> None:
        r = self.resources.get(self.selected or "")
        if r and self.presentation.details == "error":
            details = (
                f"{r.name}\n{'━' * 28}\n\nSeverity  {r.state}\n\n{r.info}\n\nID  {r.id}"
            )
        elif r and self.presentation.details == "cron":
            manifest = r.manifest
            details = (
                f"{r.name}\n{'━' * 28}\n\n"
                f"Schedule  {manifest.get('schedule', '—')}\n"
                f"User      {manifest.get('user', '—')}\n"
                f"Last run  {manifest.get('last_run', '—')}\n\n"
                f"Command   {manifest.get('command', '—')}\n\n"
                f"Source    {manifest.get('source', '—')}\n"
                f"Line      {manifest.get('line', '—')}\n\n"
                "History records launches, not completion or success."
            )
        elif r:
            details = f"{r.name}\n{'━' * 28}\n\nState     {r.state}\nCPU       {r.cpu:.1f}%\nMemory    {r.memory}\n\n{r.info}\n\nID  {r.id}"
        else:
            details = (
                "No matching resources.\nTry clearing the filter or errors-only mode."
            )
        self.query_one(".details", Static).update(details)
        self.query_one(".manifest", Static).update(
            JSON.from_data(r.manifest) if r else "{}"
        )
        log = self.query_one(RichLog)
        scroll = log.scroll_y
        at_end = log.is_vertical_scroll_end
        log.clear()
        for line in r.logs if r else []:
            log.write(Text(line), scroll_end=at_end)
        if not r or not r.logs:
            log.write(
                "No launch history supplied by this collector."
                if self.presentation.details == "cron"
                else "No logs supplied by this collector.",
                scroll_end=at_end,
            )
        if not at_end:
            log.scroll_to(y=scroll, animate=False)


class UptimeApp(App):
    """Render injected snapshots as a live, keyboard-friendly Textual dashboard."""

    TITLE = "sshuptime"
    AUTO_FOCUS = None
    CSS_PATH = "dashboard.tcss"
    BINDINGS: ClassVar = [
        Binding("q", "quit", "Quit"),
        Binding("space", "pause", "Pause"),
        Binding("r", "refresh", "Refresh"),
        Binding("/", "search", "Filter"),
        Binding("e", "errors", "Errors"),
        Binding("s", "sort", "CPU sort"),
        Binding("t", "change_theme", "Theme"),
        Binding("escape", "clear", "Clear filter"),
    ]

    def __init__(
        self,
        collector: Collector | None = None,
        *,
        interval: float = 2,
        theme: str = DEFAULT_THEME,
    ):
        super().__init__()
        self.collector = collector or DemoCollector()
        self.is_demo = isinstance(self.collector, DemoCollector)
        self.interval = interval
        self.paused = False
        self.busy = False
        self.errors_only = False
        self.sort_cpu = False
        self.history: deque[float] = deque([0] * 40, maxlen=80)
        self.views: dict[tuple[str, str], Inventory] = {}
        self.topology: tuple = ()
        self.last_success = "never"
        self.event_history: deque[str] = deque(maxlen=300)
        self.register_theme(OBSERVATORY)
        self.theme = theme

    def compose(self) -> ComposeResult:
        yield Static(" ◈ SSHUPTIME  /  infrastructure observatory", id="brand")
        with Horizontal(id="identity"):
            yield Static(
                "HOST  —", id="identity-host", classes="identity-item", markup=False
            )
            yield Static(
                "IP  —", id="identity-ip", classes="identity-item", markup=False
            )
            yield Static(
                "LINUX  —", id="identity-linux", classes="identity-item", markup=False
            )
            yield Static(
                "KERNEL  —", id="identity-kernel", classes="identity-item", markup=False
            )
        yield Static("Connecting to collector…", id="connection", markup=False)
        with Horizontal(id="metrics"):
            for key in ("cpu", "memory", "disk", "uptime"):
                with Vertical(classes="metric"):
                    yield Static(key.upper(), classes="metric-label")
                    yield Static("—", id=f"metric-{key}", markup=False)
                    if key == "cpu":
                        yield Sparkline(list(self.history), id="cpu-history")
        yield Input(placeholder="/ filter by name, state, PID or context…", id="filter")
        yield TabbedContent(id="runtimes")
        with Vertical(id="events-box"):
            yield Label(
                "EVENT STREAM / latest collector observations", classes="block-title"
            )
            yield RichLog(id="events", max_lines=300, markup=False, wrap=True)
        yield Footer()

    def on_resize(self, event: Resize) -> None:
        self.screen.set_class(event.size.height < 35, "short")
        self.screen.set_class(event.size.width < 100, "narrow")

    def on_mount(self) -> None:
        self.theme_changed_signal.subscribe(self, self.refresh_theme)
        self.set_interval(self.interval, self.poll)
        self.poll()

    @work(group="collector", exit_on_error=False)
    async def poll(self) -> None:
        if self.paused or self.busy:
            return
        self.busy = True
        try:
            async with asyncio.timeout(10):
                snapshot = await self.collector.snapshot()
            if not self.paused:
                await self.apply_snapshot(snapshot)
        except Exception as exc:  # noqa: BLE001 - isolate user-supplied collectors
            self.query_one("#connection", Static).update(
                f" ● STALE / last success {self.last_success} · {type(exc).__name__}: {exc}"
            )
        finally:
            self.busy = False

    async def apply_snapshot(self, snapshot: Snapshot) -> None:
        topology = tuple(
            (
                runtime,
                tuple(
                    (
                        category,
                        snapshot.views.get(runtime, {})
                        .get(category, default_view(category))
                        .model_dump_json(),
                    )
                    for category in categories
                ),
            )
            for runtime, categories in snapshot.inventory.items()
        )
        if topology != self.topology:
            tabs = self.query_one("#runtimes", TabbedContent)
            active = tabs.active
            await tabs.clear_panes()
            self.views.clear()
            for i, (runtime, categories) in enumerate(snapshot.inventory.items()):
                nested = TabbedContent()
                pane = TabPane(runtime, nested, id=f"runtime-{i}")
                await tabs.add_pane(pane)
                for j, category in enumerate(categories):
                    presentation = snapshot.views.get(runtime, {}).get(
                        category, default_view(category)
                    )
                    view = Inventory(category, presentation)
                    self.views[runtime, category] = view
                    await nested.add_pane(
                        TabPane(category, view, id=f"category-{i}-{j}")
                    )
            if active and any(p.id == active for p in tabs.query(TabPane)):
                tabs.active = active
            self.topology = topology
        for key, label, value in (
            ("host", "HOST", snapshot.host_info.hostname),
            ("ip", "IP", snapshot.host_info.ip),
            ("linux", "LINUX", snapshot.host_info.linux),
            ("kernel", "KERNEL", snapshot.host_info.kernel),
        ):
            item = self.query_one(f"#identity-{key}", Static)
            item.update(f"{label}  {value}")
            item.tooltip = f"{label}: {value}"
        self.last_success = datetime.now(UTC).strftime("%H:%M:%S")
        mode = "DEMO · simulated telemetry" if self.is_demo else "LIVE"
        self.query_one("#connection", Static).update(
            f" ● {mode} / {snapshot.host}   ↻ {self.interval:g}s   updated {self.last_success}"
        )
        self.history.append(snapshot.cpu)
        self.query_one(Sparkline).data = list(self.history)
        for key, value in (
            ("cpu", snapshot.cpu),
            ("memory", snapshot.memory),
            ("disk", snapshot.disk),
        ):
            dots = round(max(0, min(100, value)) / 100 * 16)
            self.query_one(f"#metric-{key}", Static).update(
                f"{value:5.1f}%  {'⣿' * dots}{'⣀' * (16 - dots)}"
            )
        self.query_one("#metric-uptime", Static).update(snapshot.uptime)
        for (runtime, category), view in self.views.items():
            view.filter_text = self.query_one(Input).value
            view.errors_only = self.errors_only
            view.sort_cpu = self.sort_cpu
            view.update_resources(snapshot.inventory[runtime][category])
        self.event_history.extend(snapshot.events)
        self.render_events()

    def render_events(self) -> None:
        log = self.query_one("#events", RichLog)
        scroll = log.scroll_y
        follow = log.is_vertical_scroll_end
        log.clear()
        for event in self.event_history:
            is_error = any(
                word in event.lower()
                for word in ("crashed", "error", "failed", "backoff")
            )
            log.write(
                Text(
                    event,
                    style=text_style(self, "text-error" if is_error else "foreground"),
                ),
                scroll_end=follow,
            )
        if not follow:
            log.scroll_to(y=scroll, animate=False)

    def refresh_theme(self, theme: Theme) -> None:
        """Recolor Rich content too, including paused data and retained events."""
        for view in self.views.values():
            view.render_rows()
        self.render_events()

    @on(Input.Changed, "#filter")
    def filter_changed(self, event: Input.Changed) -> None:
        for view in self.views.values():
            view.filter_text = event.value
            view.render_rows()

    def action_search(self) -> None:
        self.query_one(Input).focus()

    def action_clear(self) -> None:
        self.query_one(Input).value = ""
        self.set_focus(None)

    def action_pause(self) -> None:
        self.paused = not self.paused
        if self.paused:
            self.query_one("#connection", Static).update(
                f" ⏸ PAUSED / last success {self.last_success} · Space to resume"
            )
        else:
            self.poll()

    def action_refresh(self) -> None:
        self.paused = False
        self.poll()

    def action_errors(self) -> None:
        self.errors_only = not self.errors_only
        self.notify(f"Errors only: {'on' if self.errors_only else 'off'}")
        for view in self.views.values():
            view.errors_only = self.errors_only
            view.render_rows()

    def action_sort(self) -> None:
        self.sort_cpu = not self.sort_cpu
        self.notify(
            "Sort: CPU descending" if self.sort_cpu else "Sort: errors first, then name"
        )
        for view in self.views.values():
            view.sort_cpu = self.sort_cpu
            view.sort_column = None
            view.update_sort_headers()
