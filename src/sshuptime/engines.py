"""Docker and Podman runtime strategies."""

import asyncio
import os
from pathlib import Path

from .config import SourceSettings
from .models import Resource
from .presentation import runtime_views
from .source_utils import docker_cpu, log_tail, memory_text, runtime_state, safe_json


class DockerCollector:
    """Read Docker resources through the blocking SDK in a worker thread."""

    name = "Docker"

    def __init__(self, settings: SourceSettings | None = None) -> None:
        self.settings = settings or SourceSettings()
        self.views = runtime_views("Containers", "Networks", "Volumes")

    def collect_sync(self) -> dict[str, list[Resource]]:
        """Read Docker inventory once, including stopped containers."""
        import docker
        from docker.errors import DockerException

        client = docker.from_env(timeout=self.settings.request_timeout)
        try:
            client.ping()
            containers: list[Resource] = []
            for index, item in enumerate(client.containers.list(all=True)):
                attrs = item.attrs or {}
                state = runtime_state(
                    item.status or (attrs.get("State") or {}).get("Status")
                )
                cpu = 0.0
                mem = None
                if state == "running":
                    try:
                        stats = item.stats(stream=False)
                        cpu = docker_cpu(stats)
                        mem = (stats.get("memory_stats") or {}).get("usage")
                    except DockerException:
                        pass
                logs = []
                if index < self.settings.max_log_items:
                    try:
                        logs = log_tail(
                            item.logs(tail=self.settings.log_lines, timestamps=True),
                            lines=self.settings.log_lines,
                            max_bytes=self.settings.log_bytes,
                        )
                    except DockerException:
                        pass
                containers.append(
                    Resource(
                        id=item.id,
                        name=item.name,
                        state=state,
                        cpu=cpu,
                        memory=memory_text(mem),
                        info=str((attrs.get("Config") or {}).get("Image") or ""),
                        manifest=safe_json(attrs),
                        logs=logs,
                    )
                )
            networks = [
                Resource(
                    id=n.id,
                    name=n.name,
                    state="active",
                    info=str((n.attrs or {}).get("Driver") or ""),
                    manifest=safe_json(n.attrs or {}),
                )
                for n in client.networks.list()
            ]
            volumes = [
                Resource(
                    id=v.name,
                    name=v.name,
                    state="mounted",
                    info=str((v.attrs or {}).get("Driver") or ""),
                    manifest=safe_json(v.attrs or {}),
                )
                for v in client.volumes.list()
            ]
            return {"Containers": containers, "Networks": networks, "Volumes": volumes}
        finally:
            client.close()

    async def collect(self) -> dict[str, list[Resource]]:
        """Run the blocking Docker SDK without blocking Textual."""
        return await asyncio.to_thread(self.collect_sync)


class PodmanCollector:
    """Read rootless or system Podman resources through its local socket."""

    name = "Podman"

    def __init__(
        self, socket_path: str | None = None, settings: SourceSettings | None = None
    ) -> None:
        self.settings = settings or SourceSettings()
        self.views = runtime_views("Containers", "Networks", "Volumes")
        socket_path = socket_path or self.settings.podman_socket
        candidates = (
            [socket_path]
            if socket_path
            else [
                os.environ.get("PODMAN_SOCKET"),
                f"/run/user/{os.getuid()}/podman/podman.sock",
                "/run/podman/podman.sock",
            ]
        )
        self.socket_path = next((p for p in candidates if p and Path(p).exists()), None)

    def collect_sync(self) -> dict[str, list[Resource]] | None:
        """Read Podman inventory or report a missing socket."""
        if not self.socket_path:
            return None
        from podman import PodmanClient

        with PodmanClient(
            base_url=f"unix://{self.socket_path}", timeout=self.settings.request_timeout
        ) as client:
            client.ping()
            containers = []
            for index, item in enumerate(client.containers.list(all=True, sparse=True)):
                attrs = item.attrs or {}
                state = runtime_state(item.status or attrs.get("State"))
                cpu = 0.0
                mem = None
                if state == "running":
                    try:
                        stats = item.stats(stream=False, decode=True)
                        cpu = float(stats.get("CPU", 0) or 0)
                        mem = stats.get("MemUsage") or stats.get("mem_usage")
                        if isinstance(mem, (list, tuple)):
                            mem = mem[0]
                        if not isinstance(mem, (int, float)):
                            mem = None
                    except Exception:  # noqa: BLE001,S110 - optional per-item observation  # nosec B110
                        pass
                logs = []
                if index < self.settings.max_log_items:
                    try:
                        logs = log_tail(
                            item.logs(tail=self.settings.log_lines, timestamps=True),
                            lines=self.settings.log_lines,
                            max_bytes=self.settings.log_bytes,
                        )
                    except Exception:  # noqa: BLE001,S110 - log permissions/drivers vary  # nosec B110
                        pass
                containers.append(
                    Resource(
                        id=item.id,
                        name=item.name,
                        state=state,
                        cpu=cpu,
                        memory=memory_text(mem),
                        info=str(attrs.get("Image") or ""),
                        manifest=safe_json(attrs),
                        logs=logs,
                    )
                )
            networks = [
                Resource(
                    id=n.id,
                    name=n.name,
                    state="active",
                    manifest=safe_json(n.attrs or {}),
                )
                for n in client.networks.list()
            ]
            volumes = [
                Resource(
                    id=v.name,
                    name=v.name,
                    state="mounted",
                    manifest=safe_json(v.attrs or {}),
                )
                for v in client.volumes.list()
            ]
            return {"Containers": containers, "Networks": networks, "Volumes": volumes}

    async def collect(self) -> dict[str, list[Resource]] | None:
        """Run the blocking Podman SDK without blocking Textual."""
        return await asyncio.to_thread(self.collect_sync)
