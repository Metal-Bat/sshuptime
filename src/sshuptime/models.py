"""Validated collector data and the dashboard's presentation contract."""

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class Resource(BaseModel):
    """One stable, inspectable resource returned by a collector."""

    id: str
    name: str
    state: str
    cpu: float = 0
    memory: str = "—"
    info: str = ""
    manifest: dict[str, Any] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)


class HostInfo(BaseModel):
    """Identity fields shown in the dashboard header."""

    hostname: str = "—"
    ip: str = "—"
    linux: str = "—"
    kernel: str = "—"


FieldName = Literal[
    "name",
    "state",
    "cpu",
    "memory",
    "info",
    "time",
    "summary",
    "schedule",
    "user",
    "command",
    "last_run",
]


class ColumnSpec(BaseModel):
    """A visible table column and the resource field it displays."""

    title: str
    field: FieldName
    descending_first: bool = False


class CategoryView(BaseModel):
    """Presentation supplied with a collector's category."""

    columns: tuple[ColumnSpec, ...]
    details: Literal["resource", "error", "cron"] = "resource"
    history_title: str = "Logs"


class Snapshot(BaseModel):
    """A complete frame of host readings, inventories, and their presentation."""

    model_config = ConfigDict(validate_assignment=True)

    host: str
    uptime: str
    cpu: float
    memory: float
    disk: float
    inventory: dict[str, dict[str, list[Resource]]]
    views: dict[str, dict[str, CategoryView]] = Field(default_factory=dict)
    events: list[str] = Field(default_factory=list)
    host_info: HostInfo = Field(default_factory=HostInfo)


class Collector(Protocol):
    """Source of complete frames for the Textual dashboard."""

    async def snapshot(self) -> Snapshot:
        """Return a complete frame or raise to keep the prior frame visible."""
        ...


class RuntimeStrategy(Protocol):
    """An independently available runtime source with its own view definitions."""

    name: str
    views: dict[str, CategoryView]

    async def collect(self) -> dict[str, list[Resource]] | None:
        """Return inventory or None when this source is not present."""
        ...
