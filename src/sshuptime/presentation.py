"""Small view definitions supplied by collectors to the dashboard."""

from .models import CategoryView, ColumnSpec

RESOURCE_VIEW = CategoryView(
    columns=(
        ColumnSpec(title="NAME / PID", field="name"),
        ColumnSpec(title="STATE", field="state"),
        ColumnSpec(title="CPU %", field="cpu", descending_first=True),
        ColumnSpec(title="MEMORY", field="memory", descending_first=True),
        ColumnSpec(title="CONTEXT", field="info"),
    )
)

ERROR_VIEW = CategoryView(
    columns=(
        ColumnSpec(title="SOURCE", field="name"),
        ColumnSpec(title="SEVERITY", field="state"),
        ColumnSpec(title="TIME", field="time"),
        ColumnSpec(title="SUMMARY", field="summary"),
    ),
    details="error",
)

CRON_VIEW = CategoryView(
    columns=(
        ColumnSpec(title="SCHEDULE", field="schedule"),
        ColumnSpec(title="USER", field="user"),
        ColumnSpec(title="COMMAND", field="command"),
        ColumnSpec(title="LAST RUN", field="last_run", descending_first=True),
    ),
    details="cron",
    history_title="History",
)


def default_view(category: str) -> CategoryView:
    """Choose a presentation when a custom collector supplies none."""
    return {"Errors": ERROR_VIEW, "Cron": CRON_VIEW}.get(category, RESOURCE_VIEW)


def runtime_views(*categories: str) -> dict[str, CategoryView]:
    """Build a runtime's category definitions in its display order."""
    return {category: default_view(category) for category in categories}
