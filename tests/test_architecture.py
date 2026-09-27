"""Tests for injected source strategies and presentation definitions."""

import pytest
from pydantic import BaseModel, ValidationError
from textual.widgets import DataTable

from sshuptime.app import UptimeApp
from sshuptime.config import SourceSettings
from sshuptime.live import (
    DockerCollector,
    KubernetesCollector,
    LiveCollector,
    PodmanCollector,
)
from sshuptime.models import CategoryView, ColumnSpec, HostInfo, Resource, Snapshot


def test_collector_models_are_validated_pydantic_models():
    assert issubclass(Resource, BaseModel)
    assert issubclass(Snapshot, BaseModel)
    with pytest.raises(ValidationError):
        Resource(id="job", name="job", state="running", cpu="not a number")
    first = Resource(id="one", name="one", state="running")
    second = Resource(id="two", name="two", state="running")
    first.logs.append("only first")
    assert second.logs == []


@pytest.mark.asyncio
async def test_injected_runtime_strategy_keeps_its_view_and_last_data(monkeypatch):
    settings = SourceSettings(request_timeout=1.25)
    view = CategoryView(columns=(ColumnSpec(title="TASK", field="name"),))

    class Strategy:
        name = "Tasks"

        def __init__(self):
            self.views = {"Queue": view}
            self.fail = False

        async def collect(self):
            if self.fail:
                raise ConnectionError("offline")
            return {"Queue": [Resource(id="task-1", name="backup", state="running")]}

    strategy = Strategy()
    collector = LiveCollector(settings=settings, strategies=(strategy,))
    assert collector.system.settings is collector.settings

    async def host():
        return (
            {
                "host": "test",
                "host_info": HostInfo(hostname="test"),
                "uptime": "1h",
                "cpu": 1,
                "memory": 2,
                "disk": 3,
            },
            {"Processes": []},
        )

    monkeypatch.setattr(collector.system, "collect", host)
    fresh = await collector.snapshot()
    assert fresh.views["Tasks"]["Queue"] == view
    assert fresh.inventory["Tasks"]["Queue"][0].name == "backup"
    strategy.fail = True
    stale = await collector.snapshot()
    assert stale.inventory["Tasks"] == fresh.inventory["Tasks"]
    assert "STALE: Tasks" in stale.host


@pytest.mark.asyncio
async def test_custom_presentation_controls_visible_columns():
    view = CategoryView(
        columns=(
            ColumnSpec(title="STATUS", field="state"),
            ColumnSpec(title="WORK", field="name"),
        )
    )

    class Collector:
        async def snapshot(self):
            return Snapshot(
                host="test",
                uptime="1h",
                cpu=1,
                memory=2,
                disk=3,
                inventory={
                    "Custom": {
                        "Jobs": [Resource(id="job", name="backup", state="running")]
                    }
                },
                views={"Custom": {"Jobs": view}},
            )

    app = UptimeApp(Collector(), interval=3600)
    async with app.run_test() as pilot:
        for _ in range(100):
            await pilot.pause(0.02)
            if app.views and not app.busy:
                break
        table = app.views["Custom", "Jobs"].query_one(DataTable)
        assert [str(column.label) for column in table.columns.values()] == [
            "STATUS",
            "WORK",
        ]
        assert str(table.get_row("job")[1]) == "backup"


def test_source_settings_reach_each_runtime(monkeypatch, tmp_path):
    import docker

    socket = tmp_path / "podman.sock"
    socket.touch()
    settings = SourceSettings(
        request_timeout=1.25,
        podman_socket=str(socket),
        kubeconfig=str(tmp_path / "config"),
        kube_context="staging",
    )
    seen = {}

    class Client:
        containers = type("Items", (), {"list": lambda self, **kwargs: []})()
        networks = type("Items", (), {"list": lambda self: []})()
        volumes = type("Items", (), {"list": lambda self: []})()

        def ping(self):
            return True

        def close(self):
            pass

    def connect(**kwargs):
        seen.update(kwargs)
        return Client()

    monkeypatch.setattr(docker, "from_env", connect)
    assert DockerCollector(settings).collect_sync()["Containers"] == []
    assert seen["timeout"] == 1.25
    assert PodmanCollector(settings=settings).socket_path == str(socket)
    kube = KubernetesCollector(settings=settings)
    assert (kube.kubeconfig, kube.context) == (str(tmp_path / "config"), "staging")
