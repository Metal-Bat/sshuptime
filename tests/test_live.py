"""Behavioral tests for source isolation, inventory mapping, and redaction."""

from types import SimpleNamespace as Obj

import pytest

from sshuptime.live import (
    DockerCollector,
    KubernetesCollector,
    LiveCollector,
    PodmanCollector,
    safe_json,
)
from sshuptime.models import Resource


def test_redaction_and_container_mapping(monkeypatch):
    import docker

    class Container:
        def __init__(self, state):
            self.id = state
            self.name = f"app-{state}"
            self.status = state
            self.attrs = {
                "Config": {"Image": "app:v1", "Env": ["PASSWORD=hunter2"]},
                "ApiToken": "secret",
            }

        def stats(self, **kwargs):
            assert kwargs == {"stream": False}
            return {
                "cpu_stats": {
                    "cpu_usage": {"total_usage": 200},
                    "system_cpu_usage": 500,
                    "online_cpus": 2,
                },
                "precpu_stats": {
                    "cpu_usage": {"total_usage": 100},
                    "system_cpu_usage": 400,
                },
                "memory_stats": {"usage": 104857600},
            }

        def logs(self, **kwargs):
            return b"INFO ready\n"

    class Client:
        containers = Obj(
            list=lambda **kwargs: [Container("running"), Container("exited")]
        )
        networks = Obj(
            list=lambda: [Obj(id="net1", name="front", attrs={"Driver": "bridge"})]
        )
        volumes = Obj(list=lambda: [Obj(name="data", attrs={"Driver": "local"})])

        def ping(self):
            return True

        def close(self):
            pass

    monkeypatch.setattr(docker, "from_env", lambda **kwargs: Client())
    result = DockerCollector().collect_sync()
    assert [r.state for r in result["Containers"]] == ["running", "stopped"]
    assert result["Containers"][0].cpu == 200
    assert result["Containers"][0].memory == "100 MiB"
    assert result["Containers"][0].logs == ["INFO ready"]
    assert result["Containers"][0].manifest["Config"]["Env"] == "<redacted>"
    assert result["Containers"][0].manifest["ApiToken"] == "<redacted>"
    assert len(result["Networks"]) == len(result["Volumes"]) == 1
    assert safe_json({"password": "secret"}) == {"password": "<redacted>"}


def test_podman_socket_detection_and_mapping(tmp_path, monkeypatch):
    import podman

    socket = tmp_path / "podman.sock"
    socket.touch()

    class Client:
        containers = Obj(
            list=lambda **kwargs: [
                Obj(
                    id="pod1",
                    name="api",
                    status="exited",
                    attrs={"State": "exited", "Image": "api:v1"},
                    logs=lambda **kwargs: b"stopped\n",
                )
            ]
        )
        networks = Obj(list=list)
        volumes = Obj(list=list)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def ping(self):
            return True

    monkeypatch.setattr(podman, "PodmanClient", lambda **kwargs: Client())
    result = PodmanCollector(str(socket)).collect_sync()
    assert result is not None
    assert result["Containers"][0].state == "stopped"
    assert result["Containers"][0].logs == ["stopped"]


@pytest.mark.asyncio
async def test_kubernetes_mapping_and_logs(tmp_path, monkeypatch):
    from kubernetes_asyncio import client, config

    kubeconfig = tmp_path / "config"
    kubeconfig.touch()

    async def load_config(**kwargs):
        return None

    class ApiClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def sanitize_for_serialization(self, value):
            return {"name": value.metadata.name}

    waiting = Obj(state=Obj(waiting=Obj(reason="CrashLoopBackOff")))
    pod = Obj(
        metadata=Obj(uid="uid1", name="api", namespace="prod"),
        status=Obj(phase="Running", container_statuses=[waiting]),
        spec=Obj(node_name="node-a"),
    )
    node = Obj(
        metadata=Obj(uid="node1", name="node-a"),
        status=Obj(
            conditions=[Obj(type="Ready", status="True")],
            node_info=Obj(os_image="Linux"),
        ),
    )
    service = Obj(
        metadata=Obj(uid="service1", name="api", namespace="prod"),
        spec=Obj(type="ClusterIP"),
    )

    class CoreApi:
        def __init__(self, client):
            pass

        async def list_pod_for_all_namespaces(self, **kwargs):
            return Obj(items=[pod])

        async def list_node(self, **kwargs):
            return Obj(items=[node])

        async def list_service_for_all_namespaces(self, **kwargs):
            return Obj(items=[service])

        async def read_namespaced_pod_log(self, *args, **kwargs):
            return "ERROR retrying\n"

    monkeypatch.setattr(config, "load_kube_config", load_config)
    monkeypatch.setattr(client, "ApiClient", ApiClient)
    monkeypatch.setattr(client, "CoreV1Api", CoreApi)
    result = await KubernetesCollector(str(kubeconfig)).collect()
    assert result is not None
    assert result["Pods"][0].state == "crashed"
    assert result["Pods"][0].logs == ["ERROR retrying"]
    assert result["Nodes"][0].state == "ready"
    assert result["Services"][0].name == "api"


@pytest.mark.asyncio
async def test_host_and_source_failure_keep_inventory(monkeypatch):
    live = LiveCollector(podman_socket="/missing/socket", kubeconfig="/missing/config")

    async def docker_ok():
        return {
            "Containers": [Resource(id="id", name="app", state="running")],
            "Networks": [],
            "Volumes": [],
        }

    monkeypatch.setattr(live.docker, "collect", docker_ok)
    first = await live.snapshot()
    assert first.host
    assert first.inventory["System"]["Processes"]
    assert first.inventory["Docker"]["Containers"][0].name == "app"
    assert "Podman" not in first.inventory
    assert "Kubernetes" not in first.inventory

    async def docker_fail():
        raise ConnectionError("engine down")

    monkeypatch.setattr(live.docker, "collect", docker_fail)
    second = await live.snapshot()
    assert second.inventory["Docker"] == first.inventory["Docker"]
    assert "STALE: Docker" in second.host
    assert any("Docker unavailable" in event for event in second.events)
    third = await live.snapshot()
    assert not any("Docker unavailable" in event for event in third.events)
    monkeypatch.setattr(live.docker, "collect", docker_ok)
    restored = await live.snapshot()
    assert any("Docker connection restored" in event for event in restored.events)


@pytest.mark.asyncio
async def test_kubernetes_partial_permission_failure_keeps_pods(tmp_path, monkeypatch):
    from kubernetes_asyncio import client, config

    kubeconfig = tmp_path / "config"
    kubeconfig.touch()

    async def load_config(**kwargs):
        return None

    class ApiClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        def sanitize_for_serialization(self, value):
            return {"name": value.metadata.name}

    class CoreApi:
        def __init__(self, client):
            pass

        async def list_pod_for_all_namespaces(self, **kwargs):
            return Obj(
                items=[
                    Obj(
                        metadata=Obj(uid="pod1", name="api", namespace="prod"),
                        status=Obj(phase="Running", container_statuses=[]),
                        spec=Obj(node_name="node-a"),
                    )
                ]
            )

        async def list_node(self, **kwargs):
            raise PermissionError("nodes forbidden")

        async def list_service_for_all_namespaces(self, **kwargs):
            return Obj(items=[])

        async def read_namespaced_pod_log(self, *args, **kwargs):
            return "ready\n"

    monkeypatch.setattr(config, "load_kube_config", load_config)
    monkeypatch.setattr(client, "ApiClient", ApiClient)
    monkeypatch.setattr(client, "CoreV1Api", CoreApi)
    result = await KubernetesCollector(str(kubeconfig)).collect()
    assert result is not None
    assert result["Pods"][0].state == "running"
    assert result["Nodes"][0].state == "error"
    assert "forbidden" in result["Nodes"][0].info


@pytest.mark.asyncio
async def test_live_system_renders_in_compact_dashboard(monkeypatch):
    from textual.css.query import NoMatches
    from textual.widgets import DataTable

    from sshuptime.app import UptimeApp

    live = LiveCollector(podman_socket="/missing/socket", kubeconfig="/missing/config")

    async def unavailable():
        return None

    monkeypatch.setattr(live.docker, "collect", unavailable)
    app = UptimeApp(live, interval=3600)
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(100):
            await pilot.pause(0.05)
            view = app.views.get(("System", "Processes"))
            if view is None:
                continue
            try:
                table = view.query_one(DataTable)
            except NoMatches:
                continue
            if table.row_count:
                break
        assert ("System", "Processes") in app.views
        assert app.views["System", "Processes"].query_one(DataTable).row_count > 0
        assert not app.is_demo


@pytest.mark.asyncio
async def test_journal_errors_are_newest_first_and_include_details(monkeypatch):
    import asyncio
    import json

    from sshuptime.live import SystemCollector

    entries = [
        {
            "__CURSOR": "first",
            "__REALTIME_TIMESTAMP": "1700000000000000",
            "_SYSTEMD_UNIT": "network.service",
            "MESSAGE": "link down",
            "PRIORITY": "3",
        },
        {
            "__CURSOR": "second",
            "__REALTIME_TIMESTAMP": "1700000001000000",
            "_SYSTEMD_UNIT": "disk.service",
            "MESSAGE": "I/O error",
            "PRIORITY": "3",
        },
    ]

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return "\n".join(json.dumps(entry) for entry in entries).encode(), b""

    async def fake_exec(*args, **kwargs):
        assert "--boot" in args
        assert "--priority=err" in args
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    rows = await SystemCollector()._read_journal()
    assert [row.id for row in rows] == ["second", "first"]
    assert rows[0].name == "disk.service"
    assert rows[0].state == "error"
    assert "I/O error" in rows[0].info
    assert rows[0].manifest["PRIORITY"] == "3"


@pytest.mark.asyncio
async def test_unreadable_journal_is_visible(monkeypatch):
    import asyncio

    from sshuptime.live import SystemCollector

    class FakeProcess:
        returncode = 1

        async def communicate(self):
            return b"", b"Permission denied"

    async def fake_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    rows = await SystemCollector()._read_journal()
    assert rows[0].state == "unavailable"
    assert "Permission denied" in rows[0].info


def test_primary_ip_prefers_default_route(monkeypatch):
    import socket

    import psutil

    import sshuptime.live as live_module

    monkeypatch.setattr(live_module, "default_route_interfaces", lambda: ["wlan0"])
    monkeypatch.setattr(
        psutil,
        "net_if_stats",
        lambda: {"docker0": Obj(isup=True), "wlan0": Obj(isup=True)},
    )
    monkeypatch.setattr(
        psutil,
        "net_if_addrs",
        lambda: {
            "docker0": [Obj(family=socket.AF_INET, address="172.17.0.1")],
            "wlan0": [Obj(family=socket.AF_INET, address="192.168.1.59")],
        },
    )
    assert live_module.primary_ip() == "192.168.1.59"


@pytest.mark.asyncio
async def test_failed_service_is_in_system_errors_even_without_journal_rows(
    monkeypatch,
):
    from sshuptime.live import SystemCollector

    system = SystemCollector()
    monkeypatch.setattr(
        system,
        "_read_host",
        lambda: {
            "host": "test",
            "host_info": Obj(
                hostname="test", ip="192.0.2.5", linux="Linux", kernel="6.0"
            ),
            "uptime": "1h",
            "cpu": 1,
            "memory": 2,
            "disk": 3,
            "processes": [],
        },
    )

    async def failed_services():
        return [Resource(id="backup.service", name="backup.service", state="failed")]

    async def empty_journal():
        return []

    async def sample_cron():
        return [Resource(id="cron:1", name="/bin/job", state="registered")]

    monkeypatch.setattr(system, "_read_services", failed_services)
    monkeypatch.setattr(system, "_read_journal", empty_journal)
    monkeypatch.setattr(system.cron, "collect", sample_cron)
    _, inventory = await system.collect()
    assert inventory["Errors"][0].name == "backup.service"
    assert inventory["Errors"][0].state == "failed"
    assert inventory["Cron"][0].name == "/bin/job"
